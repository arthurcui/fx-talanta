"""Planning is outcome-blind; inadequate inputs never open the holdout."""

import json
import time
from datetime import UTC, datetime

import pytest
from test_candidate_research import RULES
from test_dashboard_indexed_research import indexed as indexed_fixture

from fx_talanta.dashboard.validation_agent import assessment, choose_plan
from fx_talanta.research.candidate import Rules
from fx_talanta.research.replay import digest

indexed = indexed_fixture


def plan(app, reg):
    return app.research.plan_validation(
        dict(candidate_sha256=reg["payload"]["candidate_sha256"], rules=RULES)
    )


def finish(app, key):
    for _ in range(200):
        state = app.research.validation_agent.status(key)
        if state["status"] != "RUNNING":
            return state
        time.sleep(0.02)
    raise AssertionError("agent fixture did not finish")


def test_adaptive_period_is_fixed_before_outcomes():
    candidate = dict(sha256="a" * 64, specification=dict(pairs=["EURUSD", "USDJPY"]))
    rules = Rules.model_validate(RULES)
    now = datetime(2026, 11, 17, tzinfo=UTC)
    normal = choose_plan(candidate, rules, [], now)
    slow = choose_plan(
        candidate,
        rules.model_copy(update=dict(start_hour_utc=8, end_hour_utc=9, signal_period=100)),
        [],
        now,
    )
    assert normal["required_sessions"] == 126
    assert slow["required_sessions"] == 5000
    assert normal["requested_end"] == now.isoformat()
    assert not normal["full_validation_ready"]
    assert all(x["blockers"] == ["NO_DATASET"] for x in normal["datasets"])
    assert normal == choose_plan(candidate, rules, [], now)


def test_inadequate_catalog_finishes_and_duplicate_never_restarts(indexed):
    app, reg, _ = indexed
    record = plan(app, reg)
    assert not record["payload"]["full_validation_ready"]
    assert "WARMUP_NOT_VERIFIED" in record["payload"]["datasets"][0]["blockers"]
    request = dict(plan_id=record["id"], reviewed_mapping=True)
    run = app.research.start_validation(request)
    result = finish(app, run["id"])
    assert result["status"] == "DATA_REQUIRED"
    assert not result["result"]["holdout_opened"]
    assert not result["result"]["execution_enabled"]
    assert not result["result"]["validation_complete"]
    assert app.research.start_validation(request) == result
    assert not app.research.active_runs


def test_interrupted_agent_never_restarts(indexed):
    app, reg, _ = indexed
    record = plan(app, reg)
    key = digest(dict(plan=record["id"]))
    with app.repo.conn:
        app.repo.conn.execute(
            "INSERT INTO validation_agent_runs VALUES (?,?,?,NULL)",
            (key, json.dumps(record["payload"]), "[]"),
        )
    response = app.research.start_validation(dict(plan_id=record["id"], reviewed_mapping=True))
    assert response["status"] == "INTERRUPTED_NO_RESEND"
    assert not app.research.validation_agent.active


def test_corrected_engine_plan_preserves_period_rules_and_prior_exposure(indexed, monkeypatch):
    app, reg, _ = indexed
    original = plan(app, reg)
    key = digest(dict(plan=original["id"]))
    with app.repo.conn:
        app.repo.conn.execute(
            "INSERT INTO validation_agent_runs VALUES (?,?,?,NULL)",
            (key, json.dumps(original["payload"]), "[]"),
        )
    with pytest.raises(ValueError, match="same engine"):
        app.research.plan_validation(dict(from_plan_id=original["id"]))
    monkeypatch.setattr("fx_talanta.dashboard.research.indexed_engine_hash", lambda: "b" * 64)
    corrected = app.research.plan_validation(dict(from_plan_id=original["id"]))
    value = dict(corrected["payload"])
    assert value.pop("supersedes_plan_id") == original["id"]
    value["engine_sha256"] = original["payload"]["engine_sha256"]
    assert value == original["payload"]
    assert corrected["id"] != original["id"]
    assert app.research.validation_agent.status(key)["status"] == "INTERRUPTED_NO_RESEND"


def test_manual_replay_cannot_compete_with_agent(indexed):
    app, reg, _ = indexed
    app.research.validation_agent.active.add("held")
    try:
        with pytest.raises(ValueError, match="agent validation"):
            app.research.execute(dict(registration_id=reg["id"], partition="training"))
    finally:
        app.research.validation_agent.active.clear()


def test_stage_gates_preserve_sample_size_settlement_and_risk():
    result = dict(
        metrics=dict(closed_trades=100, maximum_observed_drawdown_fraction=".02"),
        fully_settled=True,
        net_realized_pnl="10",
    )
    assert assessment(result, "training") == "PASS_TO_NEXT_STAGE"
    assert assessment(dict(result, fully_settled=False), "training") == "MORE_OBSERVATIONS_REQUIRED"
    assert assessment(dict(result, net_realized_pnl="-1"), "training") == "REJECT_OR_REVISE"
    assert (
        assessment(dict(result, experiment=dict(policy=dict(drawdown_fraction=".01"))), "training")
        == "REJECT_OR_REVISE"
    )


@pytest.mark.parametrize(
    "blocked,verdict,expected_phases",
    [
        (True, "FURTHER_VALIDATION_REQUIRED", ["training"]),
        (False, "REJECT_OR_REVISE", ["training"]),
        (False, "INSUFFICIENT_EVIDENCE", ["training"]),
        (False, "FURTHER_VALIDATION_REQUIRED", ["training", "validation", "holdout"]),
    ],
)
def test_stage_order_with_controlled_outcomes(
    indexed, monkeypatch, blocked, verdict, expected_phases
):
    # Synthetic outcomes test orchestration only, never historical qualification.
    app, reg, _ = indexed
    value = plan(app, reg)["payload"]
    value["datasets"] = [
        dict(
            value["datasets"][0],
            exploratory_ready=True,
            blockers=["INSUFFICIENT_HISTORY"] if blocked else [],
        )
    ]
    value["full_validation_ready"] = not blocked
    record = app.research.retain("VALIDATION_PLAN", value)
    phases = []
    monkeypatch.setattr(app.research, "select_dataset", lambda data: reg)

    def replay(data, agent_key=None):
        phases.append(data["partition"])
        return dict(
            kind="BACKTEST",
            id="fixture",
            payload=dict(
                verdict=verdict,
                result=dict(
                    metrics=dict(closed_trades=100, maximum_observed_drawdown_fraction=".01"),
                    fully_settled=True,
                    net_realized_pnl="1",
                ),
            ),
        )

    monkeypatch.setattr(app.research, "_execute", replay)
    started = app.research.start_validation(dict(plan_id=record["id"], reviewed_mapping=True))
    result = finish(app, started["id"])
    assert phases == expected_phases
    assert result["result"]["holdout_opened"] == ("holdout" in expected_phases)
    assert not result["result"]["qualified_for_paper"]
