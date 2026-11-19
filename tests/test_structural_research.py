from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from fx_talanta.research.baseline import Bar
from fx_talanta.research.structural import StructuralRules, StructuralSignal

D = Decimal
START = datetime(2026, 6, 3, 8, tzinfo=UTC)
LATENCY = timedelta(milliseconds=250)


def candle(at, timeframe, o, h, low, c):
    return Bar(
        symbol="EURUSD",
        timeframe=timeframe,
        close_at=at,
        available_at=at + LATENCY,
        revision=1,
        open=o,
        high=h,
        low=low,
        close=c,
    )


def history():
    bars = []
    for i in range(63):
        close = D("1.1000") + D("0.0001") * i
        bars.append(
            candle(
                START + timedelta(hours=i - 59),
                "H1",
                close - D("0.00003"),
                close + D("0.0001"),
                D("1.1050") if i == 57 else close - D("0.0001"),
                close,
            )
        )
    for i in range(32):
        bars.append(
            candle(
                START + timedelta(minutes=15 * (i - 31)),
                "M15",
                "1.1070",
                "1.1090",
                "1.1055",
                "1.1070",
            )
        )
    path = [
        ("1.1070", "1.1080", "1.1065", "1.1070"),  # full bar not yet after watch
        ("1.1060", "1.1062", "1.1051", "1.1058"),  # touch
        ("1.1060", "1.1067", "1.1059", "1.1063"),  # bounce
        ("1.1060", "1.1061", "1.1052", "1.1056"),  # retest
        ("1.1057", "1.1064", "1.1055", "1.1062"),  # confirmation
    ]
    bars.extend(
        candle(START + timedelta(minutes=15 * (i + 1)), "M15", *p) for i, p in enumerate(path)
    )
    return tuple(bars)


def drive(bars=None, arm="RETEST_CONFIRMATION", occupied=False):
    bars = bars or history()
    signal = StructuralSignal(StructuralRules(arm=arm))
    results = [
        signal(
            bars,
            "EURUSD",
            START + LATENCY + timedelta(minutes=15 * i),
            history_complete=True,
            position_open=occupied,
        )
        for i in range(6)
    ]
    return signal, results


def test_causal_sequence_and_matched_opportunities():
    confirmation, rows = drive()
    control, controls = drive(arm="FIRST_TOUCH")
    assert [r["action"] for r in rows] == ["HOLD"] * 5 + ["CANDIDATE"]
    assert [i for i, r in enumerate(controls) if r["action"] == "CANDIDATE"] == [2]
    assert confirmation.setups[0]["setup_id"] == control.setups[0]["setup_id"]
    assert confirmation.setups[0]["stop"] == control.setups[0]["stop"]
    assert [t["state"] for t in confirmation.setups[0]["transitions"]] == [
        "LEVEL_KNOWN",
        "TOUCHED",
        "BOUNCED",
        "RETESTED",
        "CONFIRMED",
    ]
    assert rows[-1]["lifecycle_guard"] == "FINITE_TARGET_90_PERCENT"
    assert rows[-1]["structural_stop"] == confirmation.setups[0]["stop"]


def test_future_bars_do_not_change_past_and_duplicates_do_not_enter():
    all_bars = history()
    whole, rows = drive(all_bars)
    sliced = StructuralSignal(StructuralRules())
    for i, expected in enumerate(rows):
        at = START + LATENCY + timedelta(minutes=15 * i)
        assert (
            sliced(
                tuple(b for b in all_bars if b.available_at <= at),
                "EURUSD",
                at,
                history_complete=True,
            )
            == expected
        )
    duplicate = whole(
        all_bars, "EURUSD", START + LATENCY + timedelta(minutes=75), history_complete=True
    )
    assert duplicate["reason"] == "ALREADY_PROCESSED_BAR"
    assert len(whole.setups) == 1


def test_position_veto_does_not_erase_opportunity():
    signal, rows = drive(occupied=True)
    assert signal.setups[0]["state"] == "CONFIRMED"
    assert rows[-1]["reason"] == "POSITION_ALREADY_OPEN"
    assert signal.setups[0]["entry"]["disposition"] == "POSITION_ALREADY_OPEN"


def test_stop_cross_has_priority_over_touch_or_confirmation():
    bars = list(history())
    i = next(
        i
        for i, b in enumerate(bars)
        if b.timeframe == "M15" and b.close_at == START + timedelta(minutes=30)
    )
    bars[i] = bars[i].model_copy(update={"low": D("1.1000")})
    signal, rows = drive(tuple(bars))
    assert rows[2]["reason"] == "STRUCTURAL_STOP_CROSSED"
    assert not any(r["action"] == "CANDIDATE" for r in rows)
    assert signal.setups[0]["state"] == "INVALIDATED"


def test_revision_latches_and_missing_bars_block():
    bars = history()
    signal = StructuralSignal(StructuralRules())
    signal(bars, "EURUSD", START + LATENCY, history_complete=True)
    revised = bars[10].model_copy(
        update={
            "revision": 2,
            "available_at": START + timedelta(minutes=1),
            "high": bars[10].high + D("0.0001"),
        }
    )
    at = START + timedelta(minutes=15) + LATENCY
    assert signal((*bars, revised), "EURUSD", at, history_complete=True)["reason"] == (
        "REVISED_OR_INCOMPLETE_INPUTS"
    )
    assert signal(bars, "EURUSD", at, history_complete=True)["reason"] == (
        "REVISED_OR_INCOMPLETE_INPUTS"
    )
    missing = tuple(b for b in bars if b.close_at != START - timedelta(hours=1))
    other = StructuralSignal(StructuralRules())
    assert other(missing, "EURUSD", START + LATENCY, history_complete=True)["reason"] == (
        "GAPPED_OR_STALE_INPUTS"
    )


def test_wrong_pair_and_backwards_arrival_rejected():
    signal, _ = drive()
    with pytest.raises(ValueError, match="EURUSD"):
        signal(history(), "USDJPY", START, history_complete=True)
    with pytest.raises(ValueError, match="monotonic"):
        signal(history(), "EURUSD", START, history_complete=True)


def test_end_of_window_is_explicit_and_no_rule_expansion():
    signal = StructuralSignal(StructuralRules())
    signal(history(), "EURUSD", START + LATENCY, history_complete=True)
    report = signal.finish(START + timedelta(minutes=1))
    assert report["opportunities"][0]["transitions"][-1]["reason"] == "END_OF_STUDY_WINDOW"
    assert not report["execution_enabled"]
    with pytest.raises(ValueError):
        StructuralRules(hold_bars=24)


def scenario():
    from fx_talanta.domain.offline import Instrument, Market, Policy, Quote
    from fx_talanta.research.replay import Costs, Dataset, Event, Experiment

    bars = history()
    prices = [
        (START - timedelta(seconds=2), D("1.1070")),
        (START - timedelta(seconds=1), D("1.1070")),
    ]
    prices += [
        (b.close_at + timedelta(milliseconds=300), b.close)
        for b in bars
        if b.timeframe == "M15" and b.close_at >= START
    ]
    prices += [
        (START + timedelta(minutes=76), D("1.1090")),
        (START + timedelta(minutes=77), D("1.1124")),
        (START + timedelta(hours=6), D("1.1124")),
    ]
    spec = Instrument(
        symbol="EURUSD",
        base="EUR",
        quote="USD",
        minimum_stop="0.00005",
        maximum_spread="0.0003",
        maximum_adverse_move="0.0005",
    )
    events = tuple(
        Event(
            available_at=at + LATENCY,
            market=Market(
                at=at,
                quotes=(Quote(symbol="EURUSD", at=at, bid=price, ask=price + D("0.0001")),),
                instruments=(spec,),
                conversion={"USD": D(1), "EUR": price},
            ),
        )
        for at, price in sorted(prices)
    )
    data = Dataset(
        provenance="SYNTHETIC",
        source="Causal structural setup fixture, not market data",
        session_calendar="Synthetic continuous engineering path",
        bar_price_basis="BID",
        history_complete=True,
        bars=bars,
        events=events,
    )
    experiment = Experiment(
        name="structural-synthetic-lifecycle",
        symbol="EURUSD",
        start=START - timedelta(seconds=3),
        training_end=START + timedelta(hours=7),
        validation_end=START + timedelta(hours=8),
        end=START + timedelta(hours=9),
        costs=Costs(
            commission_per_lot_per_side="4",
            slippage_per_lot_per_side="2",
            financing_per_lot_day="3",
            basis="Synthetic USD cost fixture",
        ),
        policy=Policy(
            capital="100000",
            trade_fraction="0.001",
            aggregate_fraction="0.001",
            maximum_positions=1,
        ),
    )
    return data, experiment


def test_target_lifecycle_replay_and_old_halt_semantics_are_both_preserved():
    from fx_talanta.research.replay import run

    data, experiment = scenario()
    signal = StructuralSignal(StructuralRules())
    result, _ = run(data, experiment, "training", signal=signal, strategy_version="candidate/guard")
    assert result["fully_settled"] and not result["integrity_halt"]
    assert result["metrics"]["closed_trades"] == 1
    evidence = result["structural_setups"]["opportunities"][0]["entry"]
    assert evidence["reservation"]["lifecycle_bound"]
    assert len(evidence["deals"]) == 2
    assert evidence["exit_context"][0]["observed_conditions"] == ["FIXED_TARGET_TOUCHED"]
    assert D(evidence["quote_age_seconds"]) <= 2
    assert D(evidence["net_realized"]) > 0  # Engine fixture only; not a market claim.
    unguarded = StructuralSignal(StructuralRules())

    def original_admission(*args, **kwargs):
        value = unguarded(*args, **kwargs)
        value.pop("lifecycle_guard", None)
        return value

    old, _ = run(
        data,
        experiment,
        "training",
        signal=original_admission,
        strategy_version="candidate/old-admission-control",
    )
    assert old["integrity_halt"] and old["fully_settled"]
    assert old["experiment"]["policy"] == result["experiment"]["policy"]


def test_gap_beyond_finite_envelope_still_halts_without_reset():
    from fx_talanta.research.replay import run

    data, experiment = scenario()
    events = list(data.events)
    index = next(i for i, e in enumerate(events) if e.market.at == START + timedelta(minutes=76))
    event = events[index]
    quote = event.market.quotes[0].model_copy(update={"bid": D("1.1500"), "ask": D("1.1501")})
    market = event.market.model_copy(
        update={"quotes": (quote,), "conversion": {"USD": D(1), "EUR": D("1.15")}}
    )
    events[index] = event.model_copy(update={"market": market})
    result, _ = run(
        data.model_copy(update={"events": tuple(events)}),
        experiment,
        "training",
        signal=StructuralSignal(StructuralRules()),
        strategy_version="candidate/gap",
    )
    assert result["integrity_halt"] and result["fully_settled"]
    assert result["metrics"]["closed_trades"] == 1


def test_structural_dashboard_register_control_export_and_resume(tmp_path):
    from uuid import uuid4

    from test_candidate_research import specification

    from fx_talanta.clock import FakeClock
    from fx_talanta.dashboard.app import Dashboard
    from fx_talanta.dashboard.demo import AT, demo

    data, experiment = scenario()
    app = Dashboard(demo(), tmp_path, "x" * 40, FakeClock(AT))
    saved = app.strategies.save(
        dict(request_id=str(uuid4()), strategy_id=str(uuid4()), specification=specification())
    )
    app.strategies.freeze(dict(sha256=saved["sha256"]))
    reg = app.research.register(
        dict(
            candidate_sha256=saved["sha256"],
            rules=StructuralRules().model_dump(mode="json"),
            reviewed_mapping=True,
            dataset=data.model_dump(mode="json"),
            experiment=experiment.model_dump(mode="json"),
            minimum_closed_trades=1,
            maximum_drawdown_fraction="0.05",
        )
    )
    request = dict(registration_id=reg["id"], partition="training")
    result = app.research.execute(request)
    control = app.research.structural_control(dict(result_id=result["id"]))
    assert (
        result["payload"]["structural_comparison_key"]
        == control["payload"]["structural_comparison_key"]
    )
    assert app.research.structural_control(dict(result_id=result["id"])) == control
    assert (
        len(
            app.research.item(result["id"])["payload"]["result"]["structural_setups"][
                "opportunities"
            ]
        )
        == 1
    )
    with pytest.raises(ValueError, match="training-only"):
        app.research.execute(dict(request, partition="holdout"))
    app.close()
    reopened = Dashboard(demo(), tmp_path, "x" * 40, FakeClock(AT))
    try:
        assert reopened.research.execute(request) == result
        assert not result["payload"]["qualified_for_paper"]
    finally:
        reopened.close()


def test_structural_diagnosis_schema_keeps_provider_supported_union():
    import json

    from fx_talanta.dashboard.improvement import Diagnosis
    from fx_talanta.dashboard.research import payload

    schema = json.loads(payload("Explain retained evidence", contract=Diagnosis))["text"]["format"][
        "schema"
    ]
    rules = schema["properties"]["rules"]
    assert "anyOf" in rules and "oneOf" not in rules and "discriminator" not in rules
    assert len(rules["anyOf"]) == 2
