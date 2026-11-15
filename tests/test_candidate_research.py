import json
from decimal import Decimal
from uuid import uuid4

import pytest

from fx_talanta.advisor.provider import MODEL
from fx_talanta.clock import FakeClock
from fx_talanta.dashboard.app import Dashboard
from fx_talanta.dashboard.demo import AT, demo
from fx_talanta.research.candidate import Rules
from fx_talanta.research.replay import run
from tools.fixtures.b01_replay import scenario

RULES = dict(
    family="TREND_BREAKOUT",
    trend_period=50,
    signal_period=20,
    atr_period=14,
    stop_atr="1.5",
    reward_risk="2",
    hold_bars=16,
    start_hour_utc=0,
    end_hour_utc=23,
    calendar_policy="REQUIRE_MARKET_HEALTH",
)


def specification():
    return dict(
        name="Research fixture",
        pairs=["EURUSD", "USDJPY"],
        **{
            k: "Explicit synthetic test description only"
            for k in [
                "hypothesis",
                "input_policy",
                "entry_rules",
                "exit_rules",
                "portfolio_policy",
                "evaluation_plan",
                "provenance",
            ]
        },
        risk_per_trade_pct="0.25",
        total_open_risk_pct="0.50",
        daily_loss_limit_pct="1",
        authorship="AI_IMPORTED",
    )


def response():
    return json.dumps(
        dict(
            status="completed",
            model=MODEL,
            output=[
                dict(
                    type="message",
                    content=[
                        dict(
                            type="output_text",
                            text=json.dumps(dict(specification=specification(), rules=RULES)),
                        )
                    ],
                )
            ],
            usage=dict(input_tokens=100, output_tokens=500),
        )
    ).encode()


@pytest.fixture
def app(tmp_path):
    value = Dashboard(
        demo(), tmp_path, "x" * 40, FakeClock(AT), research_transport=lambda _: response()
    )
    yield value
    value.close()


def registration(app):
    saved = app.strategies.save(
        dict(request_id=str(uuid4()), strategy_id=str(uuid4()), specification=specification())
    )
    app.strategies.freeze(dict(sha256=saved["sha256"]))
    data, exp = scenario()
    return dict(
        candidate_sha256=saved["sha256"],
        rules=RULES,
        reviewed_mapping=True,
        dataset=data.model_dump(mode="json"),
        experiment=exp.model_dump(mode="json"),
        minimum_closed_trades=1,
        maximum_drawdown_fraction="0.05",
    )


def test_proposal_is_at_most_once_and_provenance_retained(app):
    calls = []
    app.research.transport = lambda raw: calls.append(raw) or response()
    req = dict(request_id=str(uuid4()), brief="Propose a simple research hypothesis")
    first = app.research.generate(req)
    assert first == app.research.generate(req)
    assert len(calls) == 1 and first["kind"] == "AI_PROPOSAL"
    assert first["payload"]["returned_model"] == MODEL
    with pytest.raises(ValueError, match="conflict"):
        app.research.generate(dict(req, brief="Different research hypothesis"))


def test_uncertain_calls_never_resend(app):
    calls = []

    def timeout(raw):
        calls.append(raw)
        raise TimeoutError("private detail")

    app.research.transport = timeout
    req = dict(request_id=str(uuid4()), brief="Propose a simple research hypothesis")
    first = app.research.generate(req)
    assert first == app.research.generate(req)
    assert len(calls) == 1 and "private detail" not in json.dumps(first)


def test_binding_costs_outcomes_retry_and_restart(app):
    registered = app.research.register(registration(app))
    request = dict(registration_id=registered["id"], partition="training")
    result = app.research.execute(request)
    assert result == app.research.execute(request)
    report = result["payload"]
    assert report["result"]["strategy"].startswith("candidate/")
    assert report["result"]["metrics"]["closed_trades"] == 1
    assert Decimal(report["result"]["commission"]) > 0
    assert report["verdict"] == "REJECT_OR_REVISE"
    assert not report["qualified_for_paper"] and not report["execution_enabled"]
    state = app.state
    app.close()
    resumed = Dashboard(demo(), state, "x" * 40, FakeClock(AT))
    try:
        assert resumed.research.execute(request) == result
    finally:
        resumed.close()


def test_review_and_percentage_gates(app):
    data = registration(app)
    with pytest.raises(ValueError, match="review"):
        app.research.register(dict(data, reviewed_mapping=False))
    data["experiment"]["policy"]["trade_fraction"] = "0.01"
    with pytest.raises(ValueError, match="percentage"):
        app.research.register(data)


def test_candidate_parameters_change_actual_signal_and_keep_future_out(app):
    data, exp = scenario()
    rules = Rules.model_validate(RULES)
    result, _ = run(data, exp, "training", signal=rules.evaluate, strategy_version="candidate/test")
    assert result["deals"]
    restricted = rules.model_copy(update={"end_hour_utc": 10})
    other, _ = run(
        data, exp, "training", signal=restricted.evaluate, strategy_version="candidate/test2"
    )
    assert not other["deals"]
    at = data.events[2].available_at
    future = data.bars[-1].model_copy(update={"available_at": at.replace(year=2027), "revision": 2})
    assert rules.evaluate(data.bars, exp.symbol, at, history_complete=True) == rules.evaluate(
        (*data.bars, future), exp.symbol, at, history_complete=True
    )


def test_failed_window_exposure_is_retained(app):
    registered = app.research.register(registration(app))
    req = dict(registration_id=registered["id"], partition="holdout")
    with pytest.raises(ValueError, match="no market"):
        app.research.execute(req)
    assert app.research.execute(req)["status"] == "EXPOSED_WITHOUT_RESULT_NO_RERUN"


def test_engine_change_blocks_registered_run(app, monkeypatch):
    registered = app.research.register(registration(app))
    monkeypatch.setattr("fx_talanta.dashboard.research.engine_hash", lambda: "f" * 64)
    with pytest.raises(ValueError, match="engine changed"):
        app.research.execute(dict(registration_id=registered["id"], partition="training"))


def test_schema_requires_decimal_strings():
    from fx_talanta.dashboard.research import payload

    data = json.loads(payload("Test an unvalidated research hypothesis"))
    schema = data["text"]["format"]["schema"]
    assert schema["$defs"]["Specification"]["properties"]["risk_per_trade_pct"]["type"] == "string"
