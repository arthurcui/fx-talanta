"""Full demo request transport remains incapable of authorizing an order."""

from datetime import UTC, datetime

import pytest

from fx_talanta.connected_shadow.authority import Authority
from fx_talanta.demo.coordinator import DemoCoordinator
from fx_talanta.demo.projection import project
from fx_talanta.demo.wire import decode_request, encode_request
from fx_talanta.safety.control import LossState
from fx_talanta.shadow.store import SQLiteStore
from fx_talanta.shadow.wire import Frame, digest
from fx_talanta.shadow.work import assess
from tests.test_connected_listener import tls_material as tls_material
from tools.fixtures.demo_execution_fixtures import ACCOUNT, example
from tools.fixtures.shadow_fixtures import CLIENT, KEY, NOW, POLICY, RELEASE

INC = "1" * 64


def make(path):
    authority = Authority(
        SQLiteStore(path / "authority.db", bootstrap=True), ACCOUNT, bootstrap=True
    )
    authority.claim(CLIENT, INC, NOW)
    return DemoCoordinator(
        SQLiteStore(path / "backend.db", bootstrap=True),
        authority,
        ACCOUNT,
        CLIENT,
        INC,
        1,
        RELEASE,
        POLICY,
        KEY,
        lambda: NOW,
        initial=LossState(
            day=datetime.fromtimestamp(NOW / 1000, UTC).date(),
            start="10000",
            units="10000",
            owner_pause=False,
        ),
        bootstrap=True,
        clock_error_ms=10,
    )


def restart(c):
    return DemoCoordinator(
        c.store,
        c.authority,
        ACCOUNT,
        CLIENT,
        INC,
        1,
        RELEASE,
        POLICY,
        KEY,
        lambda: NOW,
        expected_tip=c.checkpoint(),
    )


def call(c, op="PULL", payload="", nonce="a" * 64, now=NOW):
    raw = Frame("C2S", c.scope, CLIENT, nonce, now, now + 5000, op, payload).encode(KEY)
    out = c.exchange(raw, now)
    return Frame.decode(
        out, KEY, direction="S2C", scope=c.scope, client=CLIENT, now=now, nonce=nonce
    )


def receipt(work, reason="TRADING_DISABLED", state="REJECTED"):
    return "\t".join(["demo-receipt/1", assess(work, NOW).encode().hex(), reason, state, "0"])


@pytest.mark.parametrize("action", ["ENTER", "CLOSE", "TIGHTEN_STOP", "CANCEL"])
def test_roundtrip_complete_action_not_simulator(tmp_path, action):
    c = make(tmp_path)
    e, s = example(action)
    assert decode_request(encode_request(e)) == e
    c.publish(e, s, NOW)
    response = call(c)
    parts = response.payload.split("\t")
    assert parts[0] == "demo-execution/1"
    assert decode_request(bytes.fromhex(parts[1]).decode()) == e
    dg = bytes.fromhex(parts[2]).decode().split("\t")
    reference = bytes.fromhex(dg[1]).decode()
    assert reference == project(e, s)
    r = receipt(reference)
    c = restart(c)
    ack = call(c, "REPORT", r, "b" * 64)
    assert ack.payload == digest(r)
    assert call(c, "REPORT", r, "b" * 64) == ack
    assert call(c, nonce="c" * 64).operation == "EMPTY"
    status = c.status(NOW)
    assert not status["demo_order_acceptance"] and status["orders_sent"] == 0
    assert status["native_execution_results"][0]["state"] == "REJECTED"
    # Risk acceptance and native refusal are separate durable facts.
    assert status["shadow_results"][0]["reason"] == "ACCEPTED"


@pytest.mark.parametrize("state", ["ACKNOWLEDGED", "FILLED", "SUBMITTING", "PROTECTED"])
def test_cannot_report_orders_in_disabled_release(tmp_path, state):
    c = make(tmp_path)
    e, s = example()
    c.publish(e, s, NOW)
    call(c)
    with pytest.raises(ValueError, match="DISABLED_EXECUTION"):
        call(c, "REPORT", receipt(project(e, s), state=state), "b" * 64)


def test_full_receipt_conflict_and_nonce_conflict(tmp_path):
    c = make(tmp_path)
    e, s = example()
    c.publish(e, s, NOW)
    call(c)
    original = receipt(project(e, s))
    call(c, "REPORT", original, "b" * 64)
    changed = receipt(project(e, s), reason="NOT_OWNED")
    with pytest.raises(ValueError, match="NONCE_CONFLICT"):
        call(c, "REPORT", changed, "b" * 64)
    with pytest.raises(ValueError, match="EXECUTION_RECEIPT_CONFLICT"):
        call(c, "REPORT", changed, "c" * 64)


def test_report_intent_survives_reply_commit_interruption(tmp_path, monkeypatch):
    c = make(tmp_path)
    e, s = example()
    c.publish(e, s, NOW)
    call(c)
    r = receipt(project(e, s))
    original = c.backend.exchange

    def interrupted(raw, now):
        original(raw, now)
        raise OSError("synthetic lost reply")

    monkeypatch.setattr(c.backend, "exchange", interrupted)
    with pytest.raises(OSError):
        call(c, "REPORT", r, "b" * 64)
    # Deliberately obtain the new durable tip from external recovery inspection.
    with c.store.transaction() as events:
        tip = events.tip
    c = DemoCoordinator(
        c.store,
        c.authority,
        ACCOUNT,
        CLIENT,
        INC,
        1,
        RELEASE,
        POLICY,
        KEY,
        lambda: NOW,
        expected_tip=tip,
    )
    with pytest.raises(ValueError, match="NONCE_CONFLICT"):
        call(c, "REPORT", receipt(project(e, s), reason="NOT_OWNED"), "b" * 64)
    assert call(c, "REPORT", r, "b" * 64).operation == "ACK"


def test_account_binding_and_snapshot_are_not_rewritten():
    e, s = example()
    from fx_talanta.domain.ea_protocol import Envelope

    forged = Envelope.seal(
        e.payload.model_copy(
            update={"account": e.payload.account.model_copy(update={"venue": "SIMULATOR"})}
        )
    )
    with pytest.raises(ValueError):
        encode_request(forged)
    with pytest.raises(ValueError, match="SNAPSHOT_REQUEST_MISMATCH"):
        project(e, s.model_copy(update={"quote_age_ms": 123}))


@pytest.mark.integration
def test_postgres_demo_native_receipt_and_recovery(settings):
    from dataclasses import replace
    from pathlib import Path
    from uuid import uuid4

    from fx_talanta.connected_shadow.authority import PostgresAuthorityStore
    from fx_talanta.domain.models import Environment
    from fx_talanta.shadow.store import PostgresStore
    from fx_talanta.storage.bootstrap import bootstrap

    configured = replace(settings, namespace="fx_demo_" + uuid4().hex[:10])
    bootstrap(configured, paper_account=ACCOUNT)
    dsn = configured.runtime_dsn(Environment.PAPER)
    authority = Authority(PostgresAuthorityStore(dsn, ACCOUNT), ACCOUNT, bootstrap=True)
    authority.claim(CLIENT, INC, NOW)
    store = PostgresStore(dsn, ACCOUNT, uuid4())
    c = DemoCoordinator(
        store,
        authority,
        ACCOUNT,
        CLIENT,
        INC,
        1,
        RELEASE,
        POLICY,
        KEY,
        lambda: NOW,
        bootstrap=True,
        initial=LossState(
            day=datetime.fromtimestamp(NOW / 1000, UTC).date(),
            start="10000",
            units="10000",
            owner_pause=False,
        ),
    )
    c.publish(*example(), NOW)
    call(c)
    native = (Path(__file__).parent / "fixtures/demo/demo-receipt.txt").read_text().strip()
    ack = call(c, "REPORT", native, "b" * 64)
    c = restart(c)
    assert call(c, "REPORT", native, "b" * 64) == ack
    assert call(c, "REPORT", native, "c" * 64).payload == digest(native)
    assert len(c.status(NOW)["native_execution_results"]) == 1
    assert c.status(NOW)["native_execution_results"][0]["reason"] == "TRADING_DISABLED"
    state = (Path(__file__).parent / "fixtures/demo/demo-state.txt").read_text().strip()
    ack = call(c, "REPORT", state, "d" * 64, now=NOW + 30)
    c = restart(c)
    assert call(c, "REPORT", state, "d" * 64, now=NOW + 30) == ack
    assert len(c.status(NOW + 30)["broker_states"]) == 1
    with c.store.transaction() as events:
        assert c._ledger(events).hard_halt


def test_actual_native_receipt_matches_independent_python_risk(tmp_path):
    from pathlib import Path

    c = make(tmp_path)
    c.publish(*example(), NOW)
    call(c)
    native = (Path(__file__).parent / "fixtures/demo/demo-receipt.txt").read_text().strip()
    assert call(c, "REPORT", native, "b" * 64).payload == digest(native)
    assert c.status(NOW)["shadow_results"][0]["reason"] == "ACCEPTED"
    assert c.status(NOW)["native_execution_results"][0]["reason"] == "TRADING_DISABLED"


def test_source_pinned_native_evidence_and_disabled_gate(historical_source):
    import hashlib
    import json
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    report = json.loads((root / "docs/evidence/m2-demo-execution.json").read_text())
    for name, expected in report["native_dependency_sha256"].items():
        assert hashlib.sha256(historical_source(name, expected)).hexdigest() == expected
    for name, expected in report["artifacts_sha256"].items():
        assert hashlib.sha256((root / name).read_bytes()).hexdigest() == expected
    assert report["native_check_count"] >= 30
    assert not report["execution_enabled"] and not report["demo_order_acceptance"]
    code = (root / "mql5/demo/NativePort.mqh").read_text()
    assert "const bool FX_DEMO_SUBMISSION_AUTHORIZED=false;" in code
    assert "return FX_DEMO_SUBMISSION_AUTHORIZED &&" in code


@pytest.mark.parametrize(
    "body", ["demo-receipt/1\t00\tX\tREJECTED\t0", "demo-receipt/1\tzz\tX\tREJECTED\t0"]
)
def test_malformed_native_report_is_rejected(tmp_path, body):
    c = make(tmp_path)
    with pytest.raises(ValueError):
        call(c, "REPORT", body, "e" * 64)


def test_demo_journal_cannot_be_opened_as_reference_backend(tmp_path):
    from fx_talanta.shadow.backend import Backend

    c = make(tmp_path)
    with pytest.raises(ValueError, match="BINDING_CONFLICT"):
        Backend(c.store, ACCOUNT, CLIENT, RELEASE, POLICY, KEY)


def test_https_demo_receipt_lost_ack_and_restart(tmp_path, tls_material):
    import http.client
    import ssl
    import threading
    from pathlib import Path

    from fx_talanta.connected_shadow.listener import listener
    from fx_talanta.shadow.backend import Application

    c = make(tmp_path)
    c.publish(*example(), NOW)
    app = Application(c, lambda: NOW + 30)
    drop = [False]

    def drop_once():
        value, drop[0] = drop[0], False
        return value

    cert, key = tls_material
    server = listener(app, cert, key, drop_response=drop_once)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.02})
    thread.start()
    context = ssl.create_default_context(cafile=str(cert))

    def request(op, payload, nonce):
        body = Frame("C2S", c.scope, CLIENT, nonce, NOW + 30, NOW + 5030, op, payload).encode(KEY)
        conn = http.client.HTTPSConnection(*server.server_address, context=context, timeout=2)
        try:
            conn.request("POST", "/v1/shadow", body, {"Content-Type": "application/octet-stream"})
            response = conn.getresponse()
            data = response.read()
            assert response.status == 200
            return Frame.decode(
                data, KEY, direction="S2C", scope=c.scope, client=CLIENT, now=NOW + 30, nonce=nonce
            )
        finally:
            conn.close()

    try:
        assert request("PULL", "", "a" * 64).payload.startswith("demo-execution/1\t")
        native = (Path(__file__).parent / "fixtures/demo/demo-receipt.txt").read_text().strip()
        drop[0] = True
        with pytest.raises(http.client.RemoteDisconnected):
            request("REPORT", native, "b" * 64)
        app.backend = restart(c)
        assert request("REPORT", native, "b" * 64).payload == digest(native)
        assert len(app.backend.status(NOW)["native_execution_results"]) == 1
        state = (Path(__file__).parent / "fixtures/demo/demo-state.txt").read_text().strip()
        drop[0] = True
        with pytest.raises(http.client.RemoteDisconnected):
            request("REPORT", state, "c" * 64)
        app.backend = restart(app.backend)
        assert request("REPORT", state, "c" * 64).payload == digest(state)
        assert len(app.backend.status(NOW + 30)["broker_states"]) == 1
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
        assert not thread.is_alive()
