import http.client
import json
import threading
from datetime import timedelta
from uuid import uuid4

import pytest
from test_dashboard import TOKEN

from fx_talanta.clock import FakeClock
from fx_talanta.dashboard.app import Dashboard
from fx_talanta.dashboard.demo import AT, demo
from fx_talanta.dashboard.recovery import backup, restore, verify
from fx_talanta.dashboard.server import make_server
from fx_talanta.domain.offline import Policy
from fx_talanta.gateway.offline import Gateway
from fx_talanta.provider_pipeline import status_lock
from fx_talanta.research.offline import make_intent, market_at, warmup

OPERATOR = "isolated-operator-fixture-" + "z" * 40


def build(path):
    clock = FakeClock(AT)
    snapshot = demo()
    gateway = Gateway.for_replay(snapshot.account, uuid4(), clock, Policy())
    warmup(gateway, clock)
    app = Dashboard(
        snapshot,
        path,
        TOKEN,
        clock,
        operator_gateway=gateway,
        operator_market=lambda: market_at(clock.now()),
        operator_token=OPERATOR,
    )
    return app, gateway


def preview(app, action="PAUSE_ENTRIES", position=None):
    return app.operator.preview(
        OPERATOR, dict(action=action, position_id=str(position) if position else None)
    )


def confirm(app, p):
    return app.operator.confirm(
        OPERATOR, dict(request_id=p["request_id"], confirmation="SIMULATOR ONLY")
    )


def test_actual_simulator_close_is_confirmed_once_and_audited(tmp_path):
    app, g = build(tmp_path)
    try:
        g.submit(make_intent(g), market_at(g.clock.now()))
        position = next(p.position_id for p in g.broker.book.positions if p.volume)
        p = preview(app, "CLOSE_OWNED_POSITION", position)
        before = len(g.broker.book.calls)
        result = confirm(app, p)
        assert result["status"] == "COMPLETED" and not result["execution_enabled"]
        assert not any(p.volume for p in g.broker.book.positions)
        calls = len(g.broker.book.calls)
        assert calls > before
        assert confirm(app, p) == result and len(g.broker.book.calls) == calls
        assert (
            app.repo.conn.execute("SELECT started,result FROM operator_requests").fetchone()[0] == 1
        )
    finally:
        app.close()
        g.close()


def test_pause_resume_and_halt_preserve_existing_risk_gates(tmp_path):
    app, g = build(tmp_path)
    try:
        assert confirm(app, preview(app))["status"] == "COMPLETED"
        assert g.book.administrative_pause
        app.operator.market_source = lambda: market_at(g.clock.now()).model_copy(
            update={"news_ok": False}
        )
        result = confirm(app, preview(app, "RESUME_ENTRIES"))
        assert result["status"] == "REJECTED" and g.book.administrative_pause
        app.operator.market_source = lambda: market_at(g.clock.now())
        assert confirm(app, preview(app, "RESUME_ENTRIES"))["status"] == "COMPLETED"
        assert not g.book.administrative_pause
        assert confirm(app, preview(app, "FLATTEN_OWNED_AND_HALT"))["status"] == "COMPLETED"
        assert confirm(app, preview(app, "RESUME_ENTRIES"))["status"] == "REJECTED"
    finally:
        app.close()
        g.close()


def test_expiry_stale_quotes_and_changed_state_reject(tmp_path):
    app, g = build(tmp_path)
    try:
        p = preview(app)
        g.clock.advance(timedelta(seconds=21))
        assert confirm(app, p)["reason"] == "EXPIRED"
        old = market_at(g.clock.now() - timedelta(seconds=3))
        app.operator.market_source = lambda: old
        with pytest.raises(ValueError, match="stale"):
            preview(app)
        app.operator.market_source = lambda: market_at(g.clock.now())
        p = preview(app)
        confirm(app, preview(app, "FLATTEN_OWNED_AND_HALT"))
        assert confirm(app, p)["reason"] == "STATE_VERSION_CONFLICT"
    finally:
        app.close()
        g.close()


def test_interruption_marker_survives_restart_and_never_dispatches(tmp_path):
    app, g = build(tmp_path)
    p = preview(app)
    with app.repo.conn:
        app.repo.conn.execute("UPDATE operator_requests SET started=1")
    calls = len(g.broker.book.calls)
    app.close()
    app = Dashboard(
        demo(),
        tmp_path,
        TOKEN,
        g.clock,
        operator_gateway=g,
        operator_market=lambda: market_at(g.clock.now()),
        operator_token=OPERATOR,
    )
    try:
        assert confirm(app, p)["reason"] == "INTERRUPTED_NO_RESEND"
        assert len(g.broker.book.calls) == calls
    finally:
        app.close()
        g.close()


def test_operator_http_requires_distinct_auth_origin_and_confirmation(tmp_path):
    app, g = build(tmp_path)
    server = make_server(app)
    worker = threading.Thread(target=server.serve_forever)
    worker.start()

    def req(path, data=None, token=OPERATOR, origin=None):
        c = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
        headers = {"Authorization": "Bearer " + token, "Content-Type": "application/json"}
        if origin:
            headers["Origin"] = origin
        c.request(
            "POST" if data is not None else "GET",
            path,
            json.dumps(data) if data is not None else None,
            headers,
        )
        r = c.getresponse()
        body = json.loads(r.read())
        c.close()
        return r.status, body

    try:
        assert req("/api/operator/state", token=TOKEN)[0] == 403
        assert req("/api/operator/state", origin="https://example.invalid")[0] == 403
        assert req("/api/operator/state")[0] == 200
        code, p = req("/api/operator/preview", dict(action="PAUSE_ENTRIES", position_id=None))
        assert code == 200
        assert (
            req("/api/operator/confirm", dict(request_id=p["request_id"], confirmation="yes"))[0]
            == 400
        )
        assert (
            req(
                "/api/operator/confirm",
                dict(request_id=p["request_id"], confirmation="SIMULATOR ONLY"),
            )[1]["status"]
            == "COMPLETED"
        )
        assert req("/api/order", {})[0] == 403
        assert req("/api/operator/revoke", {})[0] == 200
        assert req("/api/operator/state")[0] == 403
    finally:
        server.shutdown()
        server.server_close()
        worker.join()
        app.close()
        g.close()


def test_backup_restore_checks_hashes_and_removes_authority(tmp_path):
    source = tmp_path / "source"
    app, g = build(source)
    confirm(app, preview(app))
    app.close()
    g.close()
    archive = tmp_path / "backup"
    dest = tmp_path / "restored"
    assert backup(source, archive)["verified"]
    assert restore(archive, dest)["authority_restored"] is False
    assert verify(archive)["files"]
    restored = Dashboard(demo(), dest, TOKEN, FakeClock(AT + timedelta(minutes=1)))
    restored.close()
    from test_dashboard_integration import BUDGET, response

    with pytest.raises(PermissionError):
        Dashboard(
            demo(),
            dest,
            TOKEN,
            FakeClock(AT + timedelta(minutes=1)),
            model_budget=BUDGET,
            model_transport=response,
        )
    with pytest.raises(FileExistsError):
        restore(archive, dest)
    (archive / "inspection.sqlite").write_bytes(b"corrupt")
    with pytest.raises(ValueError):
        verify(archive)


def test_active_backup_is_refused_and_path_traversal_rejected(tmp_path):
    source = tmp_path / "source"
    app, g = build(source)
    try:
        with status_lock(source / "dashboard.lock"):
            with pytest.raises(OSError):
                backup(source, tmp_path / "bad")
        archive = tmp_path / "archive"
        backup(source, archive)
        manifest = json.loads((archive / "manifest.json").read_text())
        manifest["files"]["../outside"] = "a" * 64
        (archive / "manifest.json").write_text(json.dumps(manifest))
        with pytest.raises(ValueError):
            restore(archive, tmp_path / "out")
        assert not (tmp_path / "out").exists()
    finally:
        app.close()
        g.close()


def test_explicit_reconcile_uses_gateway_and_cannot_reset_halt(tmp_path):
    app, g = build(tmp_path)
    try:
        g.book = g.book.model_copy(update={"state": "STARTUP_RECONCILE", "integrity_halt": True})
        g._save("FIXTURE_RESTART")
        p = preview(app, "RECONCILE_SIMULATOR")
        result = confirm(app, p)
        assert result["reason"] == "SIMULATOR_RECONCILED"
        assert g.book.integrity_halt
        assert confirm(app, p) == result
        assert confirm(app, preview(app, "RESUME_ENTRIES"))["status"] == "REJECTED"
    finally:
        app.close()
        g.close()


def test_operator_rejects_account_mismatch_and_restore_incomplete(tmp_path):
    app, g = build(tmp_path / "original")
    app.close()
    other = demo().model_copy(
        update={"account": g.account.model_copy(update={"login": "other"}), "records": ()}
    )
    try:
        with pytest.raises(PermissionError):
            Dashboard(
                other,
                tmp_path / "other",
                TOKEN,
                g.clock,
                operator_gateway=g,
                operator_market=lambda: market_at(g.clock.now()),
                operator_token=OPERATOR,
            )
        restored = tmp_path / "incomplete"
        restored.mkdir()
        (restored / "restored-inspection-only.json").write_text('{"status":"INCOMPLETE"}')
        with pytest.raises(PermissionError):
            Dashboard(demo(), restored, TOKEN, g.clock)
    finally:
        g.close()
