from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from test_dashboard import TOKEN
from test_mt5 import FakeSDK
from test_mt5 import demo_binding as demo_binding

from fx_talanta.clock import FakeClock
from fx_talanta.dashboard.app import Dashboard
from fx_talanta.dashboard.current_broker import CurrentBrokerView, CurrentConfig
from fx_talanta.dashboard.demo import AT, demo
from fx_talanta.dashboard.quote_clock import QuoteClock, QuoteSample, host_identity, project_quotes
from fx_talanta.dashboard.service import InspectionService
from tools.qualification.current_broker_capture import capture
from tools.qualification.inspection_quote_clock import anchor_offset


def proof(binding_hash="a" * 64, symbols=("EURUSD",)):
    return QuoteClock(
        binding_hash=binding_hash,
        host_hash=host_identity(),
        verified_at=AT,
        verified_monotonic=1000,
        valid_until=AT + timedelta(seconds=300),
        server_offset_seconds=7200,
        initial_error_ms=40,
        evidence_hash="b" * 64,
        symbols=symbols,
    )


def quote(age, state="AVAILABLE"):
    return QuoteSample(
        symbol="EURUSD",
        received_at=AT,
        state=state,
        native_time_ms=round((AT.timestamp() + 7200 - age) * 1000)
        if state == "AVAILABLE"
        else None,
    )


@pytest.mark.parametrize(
    "age,expected",
    [(0, "FRESH"), (1.95, "FRESH"), (1.96, "STALE"), (2, "STALE"), (8, "STALE"), (-0.1, "FUTURE")],
)
def test_two_second_ceiling_includes_uncertainty_without_subtracting_age(age, expected):
    result = project_quotes((quote(age),), proof(), AT, 1000, host_identity(), True)
    row = result["quotes"][0]
    assert row["state"] == expected
    assert row["age_seconds"] == pytest.approx(age, abs=0.001)
    assert row["age_upper_bound_seconds"] == pytest.approx(age + 0.041, abs=0.001)
    assert not result["entry_ready"] and result["entry_ceiling_seconds"] == 2


@pytest.mark.parametrize(
    "fault,expected",
    [
        ("expiry", "CLOCK_EXPIRED"),
        ("jump", "CLOCK_CHANGED"),
        ("reboot", "CLOCK_CHANGED"),
        ("host", "CLOCK_HOST_MISMATCH"),
        ("uncertainty", "CLOCK_UNCERTAIN"),
    ],
)
def test_clock_loss_never_retains_verified_age(fault, expected):
    p = proof()
    now = AT
    mono = 1000
    host = host_identity()
    if fault == "expiry":
        now += timedelta(seconds=300)
        mono += 300
    if fault == "jump":
        now += timedelta(seconds=1)
    if fault == "reboot":
        mono = 0
    if fault == "host":
        host = "c" * 64
    if fault == "uncertainty":
        p = p.model_copy(update={"initial_error_ms": 100})
    result = project_quotes((quote(0.1),), p, now, mono, host, True)
    assert result["freshness"] == expected
    assert result["quotes"][0]["age_seconds"] is None


def test_missing_invalid_and_source_stale_are_distinct():
    for state in ("MISSING", "INVALID"):
        value = project_quotes((quote(0, state),), proof(), AT, 1000, host_identity(), True)
        assert value["quotes"][0]["state"] == state and value["freshness"] == "NOT_FRESH"
    value = project_quotes((quote(0),), proof(), AT, 1000, host_identity(), False)
    assert value["freshness"] == "SOURCE_STALE"


def test_actual_capture_view_monitor_sequence(tmp_path, demo_binding):
    binding = demo_binding.model_copy(
        update={
            "sdk_time_offset_seconds": 7200,
            "time_policy_from": AT,
            "time_policy_until": AT + timedelta(seconds=300),
            "time_policy_evidence": "fixture independent anchor",
        }
    )
    p = proof(binding.fingerprint(), binding.symbols)
    sdk = FakeSDK()
    sdk.terminal.trade_allowed = False
    sdk.symbol_info_tick = lambda s: SimpleNamespace(
        time_msc=round((AT.timestamp() + 7200 - 0.2) * 1000), bid=1.0, ask=1.01
    )
    clock = FakeClock(AT)

    def mono():
        return 1000 + (clock.now() - AT).total_seconds()

    run = uuid4()
    path = tmp_path / "latest.json"
    r = capture(sdk, binding, run, 1, clock.now, p, mono)
    path.write_text(r.model_dump_json())
    cfg = CurrentConfig(
        label="Fixture",
        run_id=run,
        binding_hash=binding.fingerprint(),
        receipt_file=path,
        quote_clock=p,
    )
    app = Dashboard(
        demo(), tmp_path / "state", TOKEN, clock, broker_view=CurrentBrokerView(cfg, monotonic=mono)
    )
    try:
        service = InspectionService(app)
        service.sample()
        assert app.broker()["quote_freshness"] == "FRESH"
        clock.advance(timedelta(seconds=2))
        service.sample()
        assert app.broker()["quote_freshness"] == "NOT_FRESH"
        sdk.symbol_info_tick = lambda s: None
        r2 = capture(sdk, binding, run, 2, clock.now, p, mono)
        path.write_text(r2.model_dump_json())
        service.sample()
        assert app.broker()["quote_observation"]["quotes"][0]["state"] == "MISSING"
        sdk.symbol_info_tick = lambda s: SimpleNamespace(
            time_msc=round((clock.now().timestamp() + 7200 - 0.1) * 1000), bid=1.0, ask=1.01
        )
        r3 = capture(sdk, binding, run, 3, clock.now, p, mono)
        path.write_text(r3.model_dump_json())
        service.sample()
        assert app.broker()["quote_freshness"] == "FRESH"
        assert not app.broker()["entry_ready"]
        path.write_text(r3.model_copy(update={"quote_clock_hash": "c" * 64}).model_dump_json())
        with pytest.raises(ValueError, match="evidence mismatch"):
            app.broker()
        path.write_text(r3.model_dump_json())
        clock.advance(timedelta(seconds=299))
        service.sample()
        assert app.broker()["quote_clock"] == "CLOCK_EXPIRED"
        assert app.notifications.summary()["undelivered"] == 0
    finally:
        app.close()


def test_independent_anchor_requires_two_bls_series_and_exact_times():
    events = [
        dict(id="840030015", event_code="unemployment-rate", source_url="https://www.bls.gov"),
        dict(id="840030016", event_code="nonfarm-payrolls", source_url="https://www.bls.gov"),
    ]
    values = [
        dict(
            event_id=e["id"],
            time=(AT + timedelta(hours=2)).replace(tzinfo=None).isoformat(),
            time_unknown=False,
        )
        for e in events
    ]
    assert anchor_offset(events, values, AT)[0] == 7200
    values[0]["time_unknown"] = True
    with pytest.raises(ValueError):
        anchor_offset(events, values, AT)
    values[0]["time_unknown"] = False
    values[0]["time"] = (AT + timedelta(hours=3)).replace(tzinfo=None).isoformat()
    with pytest.raises(ValueError, match="disagree"):
        anchor_offset(events, values, AT)
