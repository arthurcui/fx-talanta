from datetime import timedelta
from uuid import uuid4

import pytest
from test_dashboard import TOKEN
from test_mt5 import FakeSDK
from test_mt5 import demo_binding as demo_binding

from fx_talanta.clock import FakeClock
from fx_talanta.dashboard.app import Dashboard
from fx_talanta.dashboard.current_broker import CurrentBrokerView, CurrentConfig
from fx_talanta.dashboard.demo import AT, demo
from fx_talanta.dashboard.service import InspectionService
from fx_talanta.observer.mt5 import ObservationFailure
from tools.qualification.current_broker_capture import capture


def sample(binding, sequence=1, run=None):
    sdk = FakeSDK()
    sdk.terminal.trade_allowed = False
    receipt = capture(sdk, binding, run or uuid4(), sequence, lambda: AT)
    assert sdk.calls[-1] == ("shutdown",)
    return receipt


def test_actual_capture_contract_does_not_decode_unverified_ticks(demo_binding):
    r = sample(demo_binding)
    assert r.quotes_received == 2 and r.positions == r.orders == 0
    assert r.quote_freshness == "UNVERIFIED" and not r.execution_enabled
    assert "bid" not in r.model_dump_json() and "12345" not in r.model_dump_json()


@pytest.mark.parametrize("fault", ["algo", "live", "switch", "disconnected", "missing"])
def test_capture_rejects_unsafe_or_incomplete_identity(demo_binding, fault):
    sdk = FakeSDK()
    sdk.terminal.trade_allowed = fault == "algo"
    if fault == "live":
        sdk.account.trade_mode = 2
    if fault == "switch":
        sdk.switch_during_quotes = True
    if fault == "disconnected":
        sdk.terminal.connected = False
    if fault == "missing":
        sdk.none_positions = True
    with pytest.raises((ValueError, ObservationFailure)):
        capture(sdk, demo_binding, uuid4(), 1, lambda: AT)
    assert sdk.calls[-1] == ("shutdown",)


def test_feed_current_stale_missing_recovery_and_persistent_rollback(tmp_path, demo_binding):
    r = sample(demo_binding)
    path = tmp_path / "latest.json"
    path.write_text(r.model_dump_json())
    config = CurrentConfig(
        label="Fixture demo", binding_hash=r.binding_hash, run_id=r.run_id, receipt_file=path
    )
    clock = FakeClock(AT)
    state = tmp_path / "state"

    def app():
        return Dashboard(demo(), state, TOKEN, clock, broker_view=CurrentBrokerView(config))

    ui = app()
    try:
        worker = InspectionService(ui)
        worker.sample()
        result = ui.broker()
        assert result["state"] == "RECENT_RECORDED"
        assert result["channels"]["EA"] == "NOT_OBSERVED"
        assert result["snapshot"]["quote_latency_seconds"] is None
        assert not result["entry_ready"]
        clock.advance(timedelta(seconds=16))
        worker.sample()
        assert ui.broker()["state"] == "STALE_RECORDED"
        path.unlink()
        worker.sample()
        with pytest.raises(FileNotFoundError):
            ui.broker()
        r2 = r.model_copy(
            update={"sequence": 2, "started_at": clock.now(), "observed_at": clock.now()}
        )
        path.write_text(r2.model_dump_json())
        worker.sample()
        assert ui.broker()["state"] == "RECENT_RECORDED"
        assert ui.notifications.summary()["undelivered"] == 0
    finally:
        ui.close()
    ui = app()
    try:
        path.write_text(r.model_dump_json())
        with pytest.raises(ValueError, match="rollback"):
            ui.broker()
        path.write_text(r2.model_copy(update={"positions": 1}).model_dump_json())
        with pytest.raises(ValueError, match="conflict"):
            ui.broker()
        path.write_text(r2.model_copy(update={"run_id": uuid4()}).model_dump_json())
        with pytest.raises(ValueError, match="binding"):
            ui.broker()
    finally:
        ui.close()
