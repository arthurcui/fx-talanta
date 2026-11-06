import http.client
import json
import shutil
import ssl
import subprocess
import threading
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from test_dashboard import TOKEN, chat

from fx_talanta.advisor.provider import MODEL
from fx_talanta.advisor.provider_ledger import ProviderBudget
from fx_talanta.clock import FakeClock
from fx_talanta.dashboard.app import Dashboard
from fx_talanta.dashboard.demo import AT, demo
from fx_talanta.dashboard.server import configure_tls, make_server

BUDGET = ProviderBudget(
    max_calls=1,
    reserve_per_call_usd="0.02",
    total_reserved_usd="0.02",
    basis="synthetic bounded integration",
)


def response(payload):
    data = json.loads(json.loads(payload)["input"])
    return json.dumps(
        dict(
            status="completed",
            model=MODEL,
            usage=dict(input_tokens=100, output_tokens=20),
            output=[
                dict(
                    type="message",
                    content=[
                        dict(
                            type="output_text",
                            text=json.dumps(
                                dict(
                                    decision="EXPLAIN",
                                    citation_ids=[data["citations"][0]["record_id"]],
                                    reason="EVIDENCE_SELECTED",
                                )
                            ),
                        )
                    ],
                )
            ],
        )
    ).encode()


def build(tmp_path, transport=response):
    return Dashboard(
        demo(), tmp_path, TOKEN, FakeClock(AT), model_budget=BUDGET, model_transport=transport
    )


def test_model_persistence_budget_and_conflicting_retry(tmp_path):
    calls = []

    def transport(payload):
        calls.append(payload)
        assert b"demo-view" not in payload and TOKEN.encode() not in payload
        return response(payload)

    app = build(tmp_path, transport)
    request = chat()
    first = app.explain(request)
    assert first["status"] == "EXPLAIN" and not first["execution_enabled"]
    assert app.explain(request) == first
    with pytest.raises(ValueError):
        app.explain({**request, "question": "different"})
    assert app.explain(chat())["reason"] == "BUDGET_EXHAUSTED"
    app.close()
    app = build(tmp_path, transport)
    try:
        app.clock.advance(timedelta(minutes=1))
        assert app.explain(request) == first
        assert len(calls) == 1 and app.model.ledger.status()["reserved_calls"] == 1
        assert app.history()["total"] == 2
    finally:
        app.close()
    with pytest.raises(ValueError, match="budget"):
        Dashboard(
            demo(),
            tmp_path,
            TOKEN,
            FakeClock(AT),
            model_budget=BUDGET.model_copy(update={"max_calls": 2}),
            model_transport=transport,
        )


def test_interrupted_finish_stays_spent_after_restart(tmp_path, monkeypatch):
    calls = []
    app = build(tmp_path, lambda p: (calls.append(p), response(p))[1])
    request = chat()

    def fail(*args):
        raise OSError("fixture commit failure")

    monkeypatch.setattr(app.model.ledger, "finish", fail)
    with pytest.raises(OSError):
        app.explain(request)
    app.close()
    app = build(tmp_path, lambda p: (calls.append(p), response(p))[1])
    try:
        app.clock.advance(timedelta(minutes=1))
        assert app.explain(request)["reason"] == "OUTCOME_UNKNOWN_NO_RESEND"
        assert len(calls) == 1 and app.model.ledger.status()["unresolved_calls"] == 1
        assert app.explain(chat())["reason"] == "BUDGET_EXHAUSTED"
    finally:
        app.close()


@pytest.mark.parametrize("failure", ["malformed", "invented", "network", "expiry"])
def test_provider_failures_never_enable_commands(tmp_path, failure):
    app = None

    def transport(payload):
        if failure == "network":
            raise OSError("fixture outage")
        if failure == "expiry":
            app.clock.advance(timedelta(seconds=21))
        raw = response(payload)
        if failure == "malformed":
            return b"{}"
        if failure == "invented":
            original = json.loads(json.loads(payload)["input"])["citations"][0]["record_id"]
            return raw.replace(original.encode(), str(uuid4()).encode())
        return raw

    app = build(tmp_path, transport)
    try:
        result = app.explain(chat())
        assert result["status"] == "HOLD" and not result["execution_enabled"]
        assert app.advisor.gateway is None
    finally:
        app.close()


def test_concurrent_http_monitoring_and_duplicate_no_resend(tmp_path):
    entered, release = threading.Event(), threading.Event()
    calls = []

    def transport(payload):
        calls.append(payload)
        entered.set()
        assert release.wait(5)
        return response(payload)

    app = build(tmp_path, transport)
    server = make_server(app)
    worker = threading.Thread(target=server.serve_forever)
    worker.start()

    def request(method, path, data=None):
        conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
        conn.request(
            method,
            path,
            json.dumps(data) if data else None,
            {"Authorization": "Bearer " + TOKEN, "Content-Type": "application/json"},
        )
        result = conn.getresponse()
        raw = result.read()
        conn.close()
        return result.status, json.loads(raw)

    payload = chat()
    outcomes = []
    sender = threading.Thread(
        target=lambda: outcomes.append(request("POST", "/api/explain", payload))
    )
    try:
        sender.start()
        assert entered.wait(3)
        assert request("GET", "/api/overview")[0] == 200
        assert request("POST", "/api/explain", payload)[1]["reason"] == "OUTCOME_UNKNOWN_NO_RESEND"
        assert request("POST", "/api/order", {})[0] == 404
        release.set()
        sender.join(5)
        assert outcomes[0][0] == 200 and len(calls) == 1
    finally:
        release.set()
        sender.join(5)
        server.shutdown()
        server.server_close()
        worker.join()
        app.close()


def test_study_failure_preserves_success_and_deduplicates(tmp_path):
    app = build(tmp_path)
    raw = Path("tests/fixtures/m5/matched-study.json").read_bytes()
    try:
        first = app.upload_study(raw)
        assert app.upload_study(raw) == first
        with pytest.raises(ValueError):
            app.upload_study(b"{}")
        assert app.study() == first
        assert app.repo.conn.execute("SELECT count(*) FROM studies").fetchone()[0] == 1
    finally:
        app.close()


def test_tls_loopback_host_origin_and_certificate_verification(tmp_path):
    openssl = shutil.which("openssl") or str(Path("C:/Program Files/Git/usr/bin/openssl.exe"))
    cert, key = tmp_path / "cert.pem", tmp_path / "key.pem"
    subprocess.run(
        [
            openssl,
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-keyout",
            str(key),
            "-out",
            str(cert),
            "-days",
            "1",
            "-subj",
            "/CN=localhost",
            "-addext",
            "subjectAltName=IP:127.0.0.1",
        ],
        check=True,
        capture_output=True,
    )
    app = build(tmp_path / "state")
    server = make_server(app)
    assert configure_tls(server, cert, key) == "https"
    worker = threading.Thread(target=server.serve_forever)
    worker.start()
    try:
        context = ssl.create_default_context(cafile=str(cert))
        conn = http.client.HTTPSConnection(
            "127.0.0.1", server.server_port, context=context, timeout=5
        )
        conn.request(
            "GET",
            "/api/overview",
            headers={
                "Authorization": "Bearer " + TOKEN,
                "Origin": f"https://127.0.0.1:{server.server_port}",
            },
        )
        result = conn.getresponse()
        assert result.status == 200
        result.read()
        conn.close()
        conn = http.client.HTTPSConnection(
            "127.0.0.1", server.server_port, context=context, timeout=5
        )
        conn.request(
            "GET",
            "/api/overview",
            headers={"Authorization": "Bearer " + TOKEN, "Origin": "http://127.0.0.1"},
        )
        result = conn.getresponse()
        assert result.status == 403
        result.read()
        conn.close()
    finally:
        server.shutdown()
        server.server_close()
        worker.join()
        app.close()


def test_model_disabled_and_expiry_are_denied(tmp_path):
    disabled = Dashboard(demo(), tmp_path / "off", TOKEN, FakeClock(AT))
    try:
        with pytest.raises(PermissionError):
            disabled.explain(chat())
    finally:
        disabled.close()
    app = None
    calls = []

    def transport(payload):
        calls.append(payload)
        app.clock.advance(timedelta(hours=9))
        return response(payload)

    app = build(tmp_path / "expiry", transport)
    try:
        with pytest.raises(PermissionError):
            app.explain(chat())
        assert len(calls) == 1
        assert app.model.ledger.status()["reserved_calls"] == 1
    finally:
        app.close()


def test_broker_binding_cannot_change_on_resume(tmp_path):
    from test_dashboard_broker import observation

    from fx_talanta.dashboard.broker_view import BrokerView

    _, config = observation()
    app = Dashboard(
        demo(), tmp_path, TOKEN, FakeClock(AT), broker_view=BrokerView(config, "unused")
    )
    app.close()
    with pytest.raises(ValueError, match="rebind"):
        Dashboard(demo(), tmp_path, TOKEN, FakeClock(AT))
