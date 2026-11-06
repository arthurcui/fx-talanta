import hashlib
import http.client
import json
import socket
import sqlite3
import ssl
import threading

import pytest
from test_dashboard_service import certificates

from fx_talanta.dashboard import deployment as d
from fx_talanta.dashboard import recovery
from fx_talanta.dashboard.demo import demo
from fx_talanta.dashboard.server import BoundedServer
from fx_talanta.dashboard.sessions import Owner
from fx_talanta.provider_pipeline import status_lock


@pytest.fixture(scope="module")
def material(tmp_path_factory):
    path = tmp_path_factory.mktemp("deployment-material")
    certificates(path)
    (path / "snapshot.json").write_text(demo().model_dump_json(), encoding="utf-8")
    (path / "owner.json").write_text(
        Owner.create("owner", "isolated-fixture-passphrase").model_dump_json(), encoding="utf-8"
    )
    return path


def spec(material, state, **changes):
    values = dict(
        port=8443,
        public_origin="https://127.0.0.1:8443",
        state=state,
        mode="NEW",
        minimum_certificate_hours=1,
        files={
            k: material / v
            for k, v in dict(
                snapshot="snapshot.json",
                owner="owner.json",
                server_cert="server.pem",
                server_key="server.key",
                server_ca="ca.pem",
            ).items()
        },
    )
    values.update(changes)
    return d.Spec(**values)


def test_offline_preflight_has_no_network_or_state_writes(material, tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("preflight opened a socket")

    monkeypatch.setattr(socket, "socket", forbidden)
    profile = d.seal(spec(material, tmp_path / "state"))
    report = d.check(profile)
    assert not profile.state.exists()
    assert report["status"] == "READY_FOR_EXPLICIT_LAUNCH"
    assert not report["full_M5_complete"] and not report["target_host_qualified"]
    assert str(material) not in json.dumps(report)
    assert "password_hash" not in json.dumps(report)


@pytest.mark.parametrize(
    "changes",
    [
        {"public_origin": "https://wrong.example:8443"},
        {"minimum_certificate_hours": 72},
        {"bind": "0.0.0.0"},
        {"public_origin": "http://127.0.0.1:8443"},
        {"port": 443},
        {"execution_enabled": True},
        {"enable_alert_delivery": True},
        {"model_key_file": "secret"},
    ],
)
def test_rejects_unsafe_or_unverified_profile(material, tmp_path, changes):
    with pytest.raises((ValueError, ssl.SSLError)):
        d.seal(spec(material, tmp_path / "state", **changes))


@pytest.mark.parametrize(
    "role,replacement", [("server_key", "other.key"), ("server_ca", "other.pem")]
)
def test_rejects_wrong_tls_material(material, tmp_path, role, replacement):
    source = spec(material, tmp_path / "state")
    files = {**source.files, role: material / replacement}
    with pytest.raises(ssl.SSLError):
        d.seal(source.model_copy(update={"files": files}))


def test_artifact_and_package_pins_and_state_modes(material, tmp_path, monkeypatch):
    profile = d.seal(spec(material, tmp_path / "state"))
    with pytest.raises(ValueError, match="fingerprint"):
        d.check(profile.model_copy(update={"hashes": {**profile.hashes, "owner": "0" * 64}}))
    monkeypatch.setattr(d, "package_digest", lambda: "1" * 64)
    with pytest.raises(ValueError, match="package"):
        d.check(profile)
    monkeypatch.undo()
    profile.state.mkdir()
    with pytest.raises(ValueError, match="NEW"):
        d.check(profile)
    with pytest.raises(sqlite3.OperationalError):
        d.seal(spec(material, tmp_path / "missing", mode="RESUME"))
    with pytest.raises(ValueError, match="outside"):
        spec(material, material)


def test_launch_https_stop_backup_restore_resume(material, tmp_path, monkeypatch):
    # Use the real serve/worker/SQLite/TLS path, replacing only the blocking loop.
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    profile = d.seal(
        spec(material, tmp_path / "state", port=port, public_origin=f"https://127.0.0.1:{port}")
    )
    original = BoundedServer.serve_forever
    observations = []

    def bounded_loop(server):
        worker = threading.Thread(target=original, args=(server,), daemon=True)
        worker.start()
        try:
            context = ssl.create_default_context(cafile=material / "ca.pem")
            conn = http.client.HTTPSConnection("127.0.0.1", port, context=context, timeout=5)
            conn.request("GET", "/")
            response = conn.getresponse()
            observations.append(response.status)
            response.read()
            conn.close()
            conn = http.client.HTTPSConnection("127.0.0.1", port, context=context, timeout=5)
            conn.request(
                "POST",
                "/api/session",
                json.dumps({"username": "owner", "password": "isolated-fixture-passphrase"}),
                headers={
                    "Content-Type": "application/json",
                    "Origin": profile.public_origin,
                    "X-FX-Session": "1",
                },
            )
            response = conn.getresponse()
            assert response.status == 200
            assert json.loads(response.read())["execution_enabled"] is False
            cookie = response.getheader("Set-Cookie").split(";")[0]
            conn.close()
            conn = http.client.HTTPSConnection("127.0.0.1", port, context=context, timeout=5)
            conn.request("GET", "/api/operator/state", headers={"Cookie": cookie})
            response = conn.getresponse()
            assert response.status == 403
            response.read()
            conn.close()
            with pytest.raises((OSError, BlockingIOError)):
                recovery.backup(active[0], tmp_path / "while-running")
        finally:
            server.shutdown()
            worker.join(timeout=5)
        assert not worker.is_alive()

    active = [profile.state]
    monkeypatch.setattr(BoundedServer, "serve_forever", bounded_loop)
    d.launch(profile)
    assert observations == [200]
    with status_lock(profile.state / "dashboard.lock"):
        pass  # launch released ownership after stopping the worker/listener.
    recovery.backup(profile.state, tmp_path / "backup")
    recovery.verify(tmp_path / "backup")
    result = recovery.restore(tmp_path / "backup", tmp_path / "restored")
    assert not result["authority_restored"]
    assert not any(p.suffix in {".pem", ".key"} for p in (tmp_path / "backup").rglob("*"))
    resumed = d.seal(
        spec(
            material,
            tmp_path / "restored",
            port=port,
            public_origin=f"https://127.0.0.1:{port}",
            mode="RESUME",
        )
    )
    with sqlite3.connect(resumed.state / "inspection.sqlite") as conn:
        conn.execute("UPDATE broker_view_binding SET payload='unexpected external binding'")
    with pytest.raises(ValueError, match="external view"):
        d.check(resumed)
    with sqlite3.connect(resumed.state / "inspection.sqlite") as conn:
        conn.execute("UPDATE broker_view_binding SET payload='DISABLED'")
    active[0] = resumed.state
    d.launch(resumed)
    assert observations == [200, 200]
    marker = resumed.state / "restored-inspection-only.json"
    marker.write_text('{"status":"INCOMPLETE"}', encoding="utf-8")
    with pytest.raises(ValueError, match="incomplete"):
        d.check(resumed)


def test_cli_failure_never_prints_secret_or_private_paths(material, tmp_path, monkeypatch, capsys):
    source = tmp_path / "secret-input.json"
    source.write_text('{"secret":"DO-NOT-ECHO"}', encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        ["deployment", "seal", "--input", str(source), "--output", str(tmp_path / "out.json")],
    )
    with pytest.raises(SystemExit) as error:
        d.main()
    assert error.value.code == 1
    output = capsys.readouterr()
    assert "DO-NOT-ECHO" not in output.err and str(tmp_path) not in output.err
    assert not (tmp_path / "out.json").exists()


def test_report_output_is_exclusive(material, tmp_path, monkeypatch):
    profile = d.seal(spec(material, tmp_path / "state"))
    source, output = tmp_path / "profile.json", tmp_path / "report.json"
    source.write_text(profile.model_dump_json(), encoding="utf-8")
    output.write_text("preserved", encoding="utf-8")
    before = hashlib.sha256(output.read_bytes()).hexdigest()
    monkeypatch.setattr(
        "sys.argv", ["deployment", "check", "--input", str(source), "--output", str(output)]
    )
    with pytest.raises(SystemExit):
        d.main()
    assert hashlib.sha256(output.read_bytes()).hexdigest() == before
