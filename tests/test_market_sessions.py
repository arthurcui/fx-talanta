from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
import test_research_improvement as fixtures
from test_candidate_research import RULES
from test_research_improvement import baseline, diagnose

from fx_talanta.research.candidate import Rules
from fx_talanta.research.market_sessions import context, entry_window, reference_bars
from fx_talanta.research.session_results import summarize
from tools.fixtures.b01_replay import AT, bars


@pytest.fixture
def app(tmp_path):
    yield from fixtures.app.__wrapped__(tmp_path)


def at(value):
    return datetime.fromisoformat(value).replace(tzinfo=UTC)


def test_session_dst_and_overlap_are_independent():
    assert context(at("2026-01-06T08:30"))["regime"] == "TOKYO+LONDON"
    assert context(at("2026-07-07T07:30"))["regime"] == "TOKYO+LONDON"
    # US has changed clocks; UK has not. Then both have changed.
    assert context(at("2026-03-17T12:30"))["regime"] == "LONDON+NEW_YORK"
    assert context(at("2026-03-03T12:30"))["regime"] == "LONDON"
    assert context(at("2026-04-07T12:30"))["regime"] == "LONDON+NEW_YORK"
    assert context(at("2026-07-11T13:00"))["regime"] == "OFF_SESSION"
    assert context(at("2026-07-07T21:00"))["regime"] == "OFF_SESSION"
    with pytest.raises(ValueError, match="timezone-aware"):
        context(datetime(2026, 1, 1))


def test_overlap_bounds_and_exact_end():
    start, end = entry_window("LONDON_NEW_YORK_OVERLAP", at("2026-07-07T13:00"))
    assert start.hour == 12 and end.hour == 16
    assert entry_window("LONDON_NEW_YORK_OVERLAP", end) is None


def test_entry_gate_changes_signal_without_changing_risk_or_prices():
    rolling = Rules(**RULES)
    assert rolling.evaluate(bars(), "EURUSD", AT, history_complete=True)["action"] == "CANDIDATE"
    tokyo = Rules(**RULES, entry_session="TOKYO")
    assert (
        tokyo.evaluate(bars(), "EURUSD", AT, history_complete=True)["reason"]
        == "OUTSIDE_NAMED_SESSION"
    )
    london = Rules(**RULES, entry_session="LONDON")
    decision = london.evaluate(bars(), "EURUSD", AT, history_complete=True)
    assert decision["action"] == "CANDIDATE"
    assert decision["market_session"]["regime"] == "LONDON"
    assert (
        decision["stop_distance"]
        == rolling.evaluate(bars(), "EURUSD", AT, history_complete=True)["stop_distance"]
    )


def test_session_range_is_complete_and_never_includes_signal_or_future():
    template = next(b for b in bars() if b.timeframe == "M15")
    start = at("2026-11-05T00:00")
    history = [
        template.model_copy(
            update={
                "close_at": start + timedelta(minutes=15 * i),
                "available_at": start + timedelta(minutes=15 * i),
            }
        )
        for i in range(1, 41)
    ]
    signal = history[-1]
    chosen = reference_bars(
        "PREVIOUS_COMPLETED_TOKYO", "LONDON", history, signal, 20, signal.close_at
    )
    assert len(chosen) == 36 and chosen[-1].close_at.hour == 9
    assert chosen == reference_bars(
        "PREVIOUS_COMPLETED_TOKYO", "LONDON", history, signal, 24, signal.close_at
    )
    assert (
        reference_bars(
            "PREVIOUS_COMPLETED_TOKYO", "LONDON", history[1:], signal, 20, signal.close_at
        )
        == []
    )
    earlier = history[31]  # 08:00, today's Tokyo range still incomplete.
    assert (
        reference_bars("PREVIOUS_COMPLETED_TOKYO", "LONDON", history, earlier, 20, earlier.close_at)
        == []
    )
    current = reference_bars("CURRENT_SESSION", "LONDON", history, signal, 20, signal.close_at)
    assert len(current) == 7 and all(b.close_at > at("2026-11-05T08:00") for b in current)
    assert signal not in current


def test_invalid_reference_combinations_fail_closed():
    with pytest.raises(ValueError, match="named entry session"):
        Rules(**RULES, reference_window="CURRENT_SESSION")
    with pytest.raises(ValueError, match="breakout"):
        Rules(**dict(RULES, family="TREND_PULLBACK"), reference_window="PREVIOUS_COMPLETED_TOKYO")


def test_session_report_attribution_and_ai_input_are_exact(app):
    _, result = baseline(app)
    saved = app.research.analyze_sessions(dict(result_id=result["id"]))
    assert app.research.analyze_sessions(dict(result_id=result["id"])) == saved
    report = saved["payload"]["sessions"]
    assert sum(b["closed_trades"] for b in report["buckets"]) == 1
    assert Decimal(report["attributed_net_pnl"]) == Decimal(
        result["payload"]["result"]["net_realized_pnl"]
    )
    assert Decimal(report["unattributed_realized_pnl"]) == 0
    assert all(b["sample_status"] == "INSUFFICIENT_SESSION_SAMPLE" for b in report["buckets"])
    diagnosis = diagnose(app, result)
    assert diagnosis["payload"]["evidence"]["session_results"] == report
    assert diagnosis["payload"]["evidence"]["session_analysis_id"] == saved["id"]
    assert app.research.item(result["id"]) == result
    held = app.research.retain("BACKTEST", dict(result["payload"], partition="holdout"))
    with pytest.raises(ValueError, match="training"):
        app.research.analyze_sessions(dict(result_id=held["id"]))


def test_open_fees_are_not_reported_as_closed_session_profit(app):
    _, result = baseline(app)
    r = dict(result["payload"]["result"])
    r["deals"] = [d for d in r["deals"] if d["action"] == "ENTER"]
    report = summarize(r)
    assert sum(b["closed_trades"] for b in report["buckets"]) == 0
    assert report["unattributed_realized_pnl"] == r["net_realized_pnl"]


def test_overlap_attribution_counts_each_position_once(app):
    _, result = baseline(app)
    r = dict(result["payload"]["result"])
    shifted = [
        dict(
            d,
            position_id="independent-second-position",
            at=(datetime.fromisoformat(d["at"]) + timedelta(hours=1)).isoformat(),
        )
        for d in r["deals"]
    ]
    r["deals"] = r["deals"] + shifted
    r["net_realized_pnl"] = str(Decimal(r["net_realized_pnl"]) * 2)
    report = summarize(r)
    traded = {b["regime"]: b for b in report["buckets"] if b["closed_trades"]}
    assert set(traded) == {"LONDON", "LONDON+NEW_YORK"}
    assert all(b["closed_trades"] == 1 for b in traded.values())
    assert Decimal(report["unattributed_realized_pnl"]) == 0


def test_halted_signal_counts_are_separate_from_research_opportunities(app):
    _, result = baseline(app)
    r = dict(result["payload"]["result"])
    r["risk_halt"] = dict(at=AT.isoformat())
    report = summarize(r)
    assert sum(b["candidates_before_halt"] for b in report["buckets"]) == 0
    assert sum(b["candidates_after_halt"] for b in report["buckets"]) > 0


def test_planner_rejects_disjoint_session_and_utc_cap():
    from fx_talanta.dashboard.validation_agent import choose_plan

    rules = Rules(**dict(RULES, start_hour_utc=0, end_hour_utc=1), entry_session="LONDON")
    with pytest.raises(ValueError, match="does not overlap"):
        choose_plan({}, rules, [], AT)


def test_inactive_lookback_cannot_be_an_ai_revision(app):
    from test_candidate_research import registration

    request = registration(app)
    request["rules"] = dict(
        request["rules"], entry_session="LONDON", reference_window="CURRENT_SESSION"
    )
    reg = app.research.register(request)
    original = app.research.execute(dict(registration_id=reg["id"], partition="training"))
    diagnosis = diagnose(app, original)
    with pytest.raises(ValueError, match="inactive"):
        app.research.revise_diagnosis(dict(diagnosis_id=diagnosis["id"], reviewed=True))
