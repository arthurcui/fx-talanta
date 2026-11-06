import http.client
import shutil
import socket
import ssl
import subprocess
import threading
import time
from datetime import timedelta

import pytest
from test_dashboard import TOKEN

from fx_talanta.clock import FakeClock
from fx_talanta.dashboard.app import Dashboard
from fx_talanta.dashboard.demo import AT, demo
from fx_talanta.dashboard.server import configure_tls, make_server, validate_access
from fx_talanta.dashboard.service import InspectionService


def build(path):
    return Dashboard(demo(), path, TOKEN, FakeClock(AT))


def test_sampling_without_http_and_spool_restart_idempotence(tmp_path):
    app = build(tmp_path)
    service = InspectionService(app)
    app.service = service
    try:
        service.sample()
        first = app.notifications.summary()
        assert first["total"] > 0 and first["undelivered"] == 0
        assert service.status()["status"] == "UNAVAILABLE"  # no running worker
        hashes = {p.name: p.read_bytes() for p in (tmp_path / "notifications").iterdir()}
        app.clock.advance(timedelta(seconds=20))
        service.sample()
        assert app.notifications.summary()["total"] > first["total"]
        for name, raw in hashes.items():
            assert (tmp_path / "notifications" / name).read_bytes() == raw
        item = first["events"][0]["event"]["id"]
        app.notifications.acknowledge({"id": item})
        total = app.notifications.summary()["total"]
    finally:
        app.close()
    app = Dashboard(demo(), tmp_path, TOKEN, FakeClock(AT + timedelta(seconds=20)))
    try:
        InspectionService(app).sample()
        assert app.notifications.summary()["total"] == total
        row = app.repo.conn.execute(
            "SELECT acknowledged FROM notifications WHERE id=?", (item,)
        ).fetchone()
        assert row[0]
    finally:
        app.close()


def test_delivery_failure_is_retained_and_retry_does_not_overwrite(tmp_path):
    app = build(tmp_path)
    try:
        app.overview()
        path = tmp_path / "notifications" / "incident-1.json"
        path.write_bytes(b"conflict")
        app.notifications.pump()
        assert app.notifications.summary()["undelivered"] == 1
        with pytest.raises(ValueError):
            app.notifications.acknowledge({"id": 1})
        assert path.read_bytes() == b"conflict"
        path.unlink()
        app.notifications.pump()
        assert app.notifications.summary()["undelivered"] == 0
        original = path.read_bytes()
        with app.repo.conn:
            app.repo.conn.execute("UPDATE notifications SET delivered=0 WHERE id=1")
        app.notifications.pump()
        assert path.read_bytes() == original
        path.write_bytes(b"changed-after-delivery")
        with pytest.raises(ValueError):
            app.notifications.acknowledge({"id": 1})
    finally:
        app.close()


def test_backlog_delivers_beyond_one_page(tmp_path):
    app = build(tmp_path)
    try:
        for i in range(225):
            app.monitor.transitions({"fixture": str(i)}, AT, {"default": "fixture"})
        for _ in range(3):
            app.notifications.pump()
        value = app.notifications.summary()
        assert value["total"] == 225 and value["undelivered"] == 0 and len(value["events"]) == 100
    finally:
        app.close()


def test_worker_stops_and_failure_is_not_healthy(tmp_path, monkeypatch):
    app = build(tmp_path)
    service = InspectionService(app, 1)
    app.service = service
    try:
        service.start()
        limit = time.monotonic() + 3
        while service.last_success is None and time.monotonic() < limit:
            time.sleep(0.01)
        assert service.status()["status"] == "RECENT"

        def fail():
            raise OSError("fixture")

        monkeypatch.setattr(app, "overview", fail)
        limit = time.monotonic() + 3
        while not service.failed and time.monotonic() < limit:
            time.sleep(0.01)
        assert service.status()["status"] == "UNAVAILABLE"
    finally:
        service.stop()
        app.close()
    assert not service.thread.is_alive()


@pytest.mark.parametrize(
    "changes",
    [
        {"certificate": None, "key": None},
        {"client_ca": None},
        {"origin": None},
        {"operator": True},
        {"origin": "http://localhost:8443"},
        {"origin": "https://user@localhost"},
        {"origin": "https://localhost/path"},
        {"origin": "https://localhost:99999"},
    ],
)
def test_remote_access_rejects_incomplete_or_unsafe_config(changes):
    args = dict(
        bind="0.0.0.0",
        origin="https://localhost:8443",
        certificate="cert",
        key="key",
        client_ca="ca",
    )
    args.update(changes)
    with pytest.raises(ValueError):
        validate_access(**args)


def certificates(path):
    openssl = shutil.which("openssl") or "C:/Program Files/Git/usr/bin/openssl.exe"

    def run(*args):
        subprocess.run([openssl, *args], cwd=path, check=True, capture_output=True)

    run(
        "req",
        "-x509",
        "-newkey",
        "rsa:2048",
        "-nodes",
        "-keyout",
        "ca.key",
        "-out",
        "ca.pem",
        "-days",
        "1",
        "-subj",
        "/CN=TestCA",
        "-addext",
        "basicConstraints=critical,CA:TRUE",
        "-addext",
        "keyUsage=critical,keyCertSign,cRLSign",
    )
    for name in ("server", "client", "other"):
        if name == "other":
            run(
                "req",
                "-x509",
                "-newkey",
                "rsa:2048",
                "-nodes",
                "-keyout",
                name + ".key",
                "-out",
                name + ".pem",
                "-days",
                "1",
                "-subj",
                "/CN=Untrusted",
            )
            continue
        run(
            "req",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-keyout",
            name + ".key",
            "-out",
            name + ".csr",
            "-subj",
            "/CN=" + name,
        )
        extension = (
            "subjectAltName=IP:127.0.0.1\nextendedKeyUsage=serverAuth\n"
            if name == "server"
            else "extendedKeyUsage=clientAuth\n"
        )
        (path / (name + ".ext")).write_text(extension)
        run(
            "x509",
            "-req",
            "-in",
            name + ".csr",
            "-CA",
            "ca.pem",
            "-CAkey",
            "ca.key",
            "-CAcreateserial",
            "-out",
            name + ".pem",
            "-days",
            "1",
            "-extfile",
            name + ".ext",
        )


def test_actual_mutual_tls_requires_cert_and_bearer_and_exact_origin(tmp_path):
    certificates(tmp_path)
    app = build(tmp_path / "state")
    server = make_server(app)
    configure_tls(server, tmp_path / "server.pem", tmp_path / "server.key", tmp_path / "ca.pem")
    origin = f"https://127.0.0.1:{server.server_port}"
    server.public_origin = origin
    thread = threading.Thread(target=server.serve_forever)
    thread.start()

    def call(cert=None, token=TOKEN, request_origin=origin, host=None):
        context = ssl.create_default_context(cafile=str(tmp_path / "ca.pem"))
        if cert:
            context.load_cert_chain(tmp_path / (cert + ".pem"), tmp_path / (cert + ".key"))
        conn = http.client.HTTPSConnection(
            "127.0.0.1", server.server_port, context=context, timeout=3
        )
        try:
            headers = {
                "Authorization": "Bearer " + token,
                "Origin": request_origin,
                "X-Forwarded-Host": "ignored.invalid",
            }
            if host:
                headers["Host"] = host
            conn.request("GET", "/api/overview", headers=headers)
            response = conn.getresponse()
            response.read()
            return response.status
        finally:
            conn.close()

    try:
        for cert in (None, "other"):
            with pytest.raises((ssl.SSLError, ConnectionError, http.client.RemoteDisconnected)):
                call(cert)
        # A client that never handshakes occupies only one bounded worker.
        with socket.create_connection(("127.0.0.1", server.server_port), timeout=3):
            assert call("client") == 200
        assert call("client", token="wrong") == 403
        assert call("client", request_origin="https://wrong.invalid") == 403
        assert call("client", host="wrong.invalid") == 403
        app.clock.advance(timedelta(hours=9))
        assert call("client") == 403
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
        app.close()


def test_remote_factory_refuses_plaintext_before_binding(tmp_path):
    app = build(tmp_path)
    try:
        with pytest.raises(ValueError):
            make_server(app, bind="0.0.0.0")
    finally:
        app.close()


def test_notification_backup_restore_preserves_files_and_receipts(tmp_path):
    from fx_talanta.dashboard.recovery import backup, restore

    source = tmp_path / "source"
    app = build(source)
    InspectionService(app).sample()
    app.notifications.acknowledge({"id": 1})
    expected = (source / "notifications" / "incident-1.json").read_bytes()
    app.close()
    backup(source, tmp_path / "backup")
    restore(tmp_path / "backup", tmp_path / "restore")
    restored = build(tmp_path / "restore")
    try:
        assert (tmp_path / "restore" / "notifications" / "incident-1.json").read_bytes() == expected
        receipt = next(
            e for e in restored.notifications.summary()["events"] if e["event"]["id"] == 1
        )
        assert receipt["acknowledged"] and receipt["delivered"]
    finally:
        restored.close()


def test_loopback_does_not_allow_operator_public_origin_configuration():
    with pytest.raises(ValueError):
        validate_access(
            "127.0.0.1", "https://inspection.example", "cert", "key", "ca", operator=True
        )
