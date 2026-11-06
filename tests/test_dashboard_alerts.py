import hashlib
import json
import ssl
import threading
from datetime import timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from test_dashboard import TOKEN
from test_dashboard_service import certificates

from fx_talanta.clock import FakeClock
from fx_talanta.dashboard.alerts import AlertConfig, HTTPSReceiver, ReceiverHTTPError
from fx_talanta.dashboard.app import Dashboard
from fx_talanta.dashboard.demo import AT, demo


class Receiver:
    def __init__(self, mode="accepted"):
        self.mode = mode
        self.calls = []

    def request(self, method, payload, sha):
        self.calls.append((method, payload, sha))
        if self.mode == "timeout" or self.mode == "lost-reply" and method == "POST":
            raise TimeoutError("private exception must not be persisted")
        if self.mode == "malformed":
            return {"status": "ACCEPTED"}
        return dict(
            id=payload["id"],
            digest=sha,
            status="REJECTED" if self.mode == "rejected" else "ACCEPTED",
        )


def config(**changes):
    return AlertConfig(
        endpoint="https://alerts.invalid/fx",
        token_file="not-read-with-fixture-transport",
        expires_at=AT + timedelta(minutes=5),
        **changes,
    )


def build(path, receiver, clock=None, cfg=None):
    return Dashboard(
        demo(),
        path,
        TOKEN,
        clock or FakeClock(AT),
        alert_config=cfg or config(),
        alert_transport=receiver,
    )


def incident(app, value="STALE"):
    with app.repo.lock:
        app.monitor.transitions(
            {"quote-fixture": value},
            app.clock.now(),
            {"default": "PRIVATE EVIDENCE MUST NOT BE SENT"},
        )
    app.notifications.pump()


def test_receiver_ack_and_local_ack_are_separate_and_wire_is_minimal(tmp_path):
    receiver = Receiver()
    app = build(tmp_path, receiver)
    try:
        incident(app)
        app.alerts.pump()
        assert app.alerts.summary()["states"] == {"DELIVERED": 1}
        assert app.notifications.summary()["unacknowledged"] == 1
        sent = receiver.calls[0][1]
        assert set(sent) == {
            "version",
            "id",
            "incident_id",
            "observed_at",
            "message",
            "source_sha256",
            "execution_enabled",
        }
        assert "PRIVATE" not in json.dumps(sent) and not sent["execution_enabled"]
        assert app.alerts.summary()["recent"][0]["receipt_sha"]
        app.notifications.acknowledge({"id": sent["incident_id"]})
        app.alerts.pump()
        assert len(receiver.calls) == 1
        assert app.notifications.summary()["unacknowledged"] == 0
    finally:
        app.close()


def test_lost_reply_reconciles_by_get_after_restart_without_reposting(tmp_path):
    receiver = Receiver("lost-reply")
    clock = FakeClock(AT)
    app = build(tmp_path, receiver, clock)
    incident(app)
    app.alerts.pump()
    assert app.alerts.summary()["states"] == {"UNKNOWN": 1}
    app.close()
    app = build(tmp_path, receiver, clock)
    try:
        app.alerts.pump()
        app.alerts.pump()
        assert [c[0] for c in receiver.calls] == ["POST", "GET"]
        assert app.alerts.summary()["states"] == {"DELIVERED": 1}
    finally:
        app.close()


def test_committed_send_reservation_is_recovered_without_post(tmp_path):
    receiver = Receiver("timeout")
    app = build(tmp_path, receiver)
    incident(app)
    app.alerts.pump()
    with app.repo.conn:
        app.repo.conn.execute("UPDATE alert_delivery SET state='SENDING'")
    app.close()
    receiver.mode = "accepted"
    app = build(tmp_path, receiver)
    try:
        app.alerts.pump()
        assert [c[0] for c in receiver.calls] == ["POST", "GET"]
        assert any(r["method"] == "RECOVERY" for r in app.alerts.summary()["recent"])
    finally:
        app.close()


@pytest.mark.parametrize(
    "mode,expected", [("timeout", "UNKNOWN"), ("malformed", "UNKNOWN"), ("rejected", "REJECTED")]
)
def test_failure_is_not_success_and_lookup_attempts_are_bounded(tmp_path, mode, expected):
    receiver = Receiver(mode)
    app = build(tmp_path, receiver)
    try:
        incident(app)
        for _ in range(8):
            app.alerts.pump()
        assert app.alerts.summary()["states"] == {expected: 1}
        assert sum(c[0] == "POST" for c in receiver.calls) == 1
        assert sum(c[0] == "GET" for c in receiver.calls) == (0 if mode == "rejected" else 3)
        assert "private exception" not in repr(app.alerts.summary())
    finally:
        app.close()


def test_limits_deadline_clock_and_binding_cannot_reset(tmp_path):
    receiver = Receiver()
    clock = FakeClock(AT)
    cfg = config(max_messages=1)
    app = build(tmp_path, receiver, clock, cfg)
    incident(app)
    app.alerts.pump()
    incident(app, "UNKNOWN")
    app.alerts.pump()
    assert app.alerts.summary()["states"] == {"DELIVERED": 1, "LIMIT_REACHED": 1}
    app.close()
    with pytest.raises(ValueError, match="rebind"):
        build(tmp_path, receiver, clock, config(max_messages=2))
    app = build(tmp_path, receiver, clock, cfg)
    try:
        clock._now -= timedelta(seconds=1)
        with pytest.raises(ValueError, match="rollback"):
            app.alerts.pump()
        assert app.alerts.summary()["status"] == "CLOCK_INVALID"
        clock._now = AT + timedelta(minutes=6)
        incident(app, "EXPIRED")
        app.alerts.pump()
        assert app.alerts.summary()["status"] == "EXPIRED"
        assert len(receiver.calls) == 1
    finally:
        app.close()


def test_no_historical_backlog_on_first_enable_and_restores_cannot_send(tmp_path):
    app = Dashboard(demo(), tmp_path, TOKEN, FakeClock(AT))
    incident(app)
    app.close()
    receiver = Receiver()
    app = build(tmp_path, receiver)
    app.alerts.pump()
    assert receiver.calls == []
    app.close()
    (tmp_path / "restored-inspection-only.json").write_text(
        json.dumps(dict(status="VERIFIED_INSPECTION_ONLY"))
    )
    with pytest.raises(PermissionError, match="restored"):
        build(tmp_path, receiver)
    app = Dashboard(demo(), tmp_path, TOKEN, FakeClock(AT))
    try:
        assert app.notifications.summary()["external"]["status"] == "NOT_CONFIGURED"
    finally:
        app.close()


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://example.com/fx",
        "https://user:pass@example.com/fx",
        "https://example.com/fx?key=x",
        "https://example.com/fx#key",
        "https://example.com/fx/",
    ],
)
def test_endpoint_constraints(endpoint):
    with pytest.raises(ValueError):
        AlertConfig(endpoint=endpoint, token_file="fixture", expires_at=AT + timedelta(minutes=1))


def test_actual_tls_auth_receipt_lookup_and_redirect_refusal(tmp_path):
    certificates(tmp_path)
    token = "fixture-receiver-secret-at-least-32-characters"
    token_file = tmp_path / "private-token"
    token_file.write_text(token)
    calls = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            calls.append((self.command, self.path, self.headers["Authorization"]))
            if self.path == "/redirect":
                self.send_response(302)
                self.send_header("Location", "/never")
                self.end_headers()
                return
            body = json.dumps(
                dict(
                    id=payload["id"], digest=self.headers["X-FX-Content-SHA256"], status="ACCEPTED"
                )
            ).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            calls.append((self.command, self.path, self.headers["Authorization"]))
            body = json.dumps(
                dict(
                    id=self.path.rsplit("/", 1)[1],
                    digest=self.headers["X-FX-Content-SHA256"],
                    status="ACCEPTED",
                )
            ).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(tmp_path / "server.pem", tmp_path / "server.key")
    server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        cfg = AlertConfig(
            endpoint=f"https://127.0.0.1:{server.server_port}/fx",
            token_file=str(token_file),
            ca_file=str(tmp_path / "ca.pem"),
            expires_at=AT + timedelta(hours=1),
        )
        transport = HTTPSReceiver(cfg)
        payload = {"id": "fixture-id"}
        sha = hashlib.sha256(b"fixture").hexdigest()
        assert transport.request("POST", payload, sha)["status"] == "ACCEPTED"
        assert transport.request("GET", payload, sha)["digest"] == sha
        with pytest.raises(ReceiverHTTPError) as error:
            HTTPSReceiver(
                cfg.model_copy(update={"endpoint": cfg.endpoint.replace("/fx", "/redirect")})
            ).request("POST", payload, sha)
        assert error.value.status == 302
        assert len(calls) == 3 and all(c[2] == "Bearer " + token for c in calls)
        with pytest.raises(ssl.SSLError):
            HTTPSReceiver(cfg.model_copy(update={"ca_file": None})).request("POST", payload, sha)
        assert len(calls) == 3
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_clock_rollback_during_send_retains_uncertainty(tmp_path):
    clock = FakeClock(AT)

    class Rollback(Receiver):
        def request(self, method, payload, sha):
            reply = super().request(method, payload, sha)
            clock._now -= timedelta(seconds=1)
            return reply

    app = build(tmp_path, Rollback(), clock)
    try:
        incident(app)
        app.alerts.pump()
        summary = app.alerts.summary()
        assert summary["status"] == "CLOCK_INVALID"
        assert summary["states"] == {"UNKNOWN": 1}
        assert summary["recent"][0]["reason"] == "CLOCK_ROLLBACK"
        assert summary["recent"][0]["receipt_sha"] is None
    finally:
        app.close()


def test_concurrent_pumps_do_not_duplicate_send(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    started, release = threading.Event(), threading.Event()

    class Slow(Receiver):
        def request(self, method, payload, sha):
            started.set()
            assert release.wait(5)
            return super().request(method, payload, sha)

    receiver = Slow()
    app = build(tmp_path, receiver)
    try:
        incident(app)
        with ThreadPoolExecutor(2) as pool:
            first = pool.submit(app.alerts.pump)
            assert started.wait(5)
            pool.submit(app.alerts.pump).result(timeout=2)
            assert app.alerts.summary()["states"] == {"SENDING": 1}
            release.set()
            first.result(timeout=5)
        assert len(receiver.calls) == 1
    finally:
        release.set()
        app.close()
