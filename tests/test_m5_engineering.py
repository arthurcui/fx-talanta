from datetime import timedelta
from uuid import uuid4

import pytest

from fx_talanta.dashboard.demo import AT, demo
from fx_talanta.dashboard.operations import summary
from fx_talanta.evaluation.matched import Study, evaluate


def study_data():
    arms = [
        dict(
            name=name,
            ledger="ledger-" + str(i),
            policy_hash="a" * 64,
            safety_hash="b" * 64,
            model_hash=None if i == 0 else "c" * 64,
            prompt_hash=None if i == 0 else "d" * 64,
            news_content=i == 2,
        )
        for i, name in enumerate(("NO_AI", "AI_NO_NEWS", "AI_NEWS"))
    ]
    samples = [
        dict(
            snapshot_hash="e" * 64,
            snapshot_at=AT,
            arm=arm["name"],
            decision_id=uuid4(),
            decision_at=AT + timedelta(seconds=1),
            outcome_at=AT + timedelta(seconds=10),
            gross_pnl=str(i + 1),
            cost="0.5",
            latency_ms=100,
            missed_entry=False,
        )
        for i, arm in enumerate(arms)
    ]
    return dict(
        provenance="SYNTHETIC",
        candidate_hash="a" * 64,
        dataset_hash="b" * 64,
        criteria_hash="c" * 64,
        feature_hash="d" * 64,
        lessons_hash="e" * 64,
        news_interpretation_hash="f" * 64,
        frozen_at=AT,
        cutoff=AT + timedelta(hours=1),
        arms=arms,
        samples=samples,
    )


def test_matched_costs_and_pairing_do_not_qualify():
    data = study_data()
    result = evaluate(Study.model_validate(data))
    assert all(c["complete_pairs"] == 1 for c in result["comparisons"])
    assert all(c["mean_net_difference_usd"] == "1.0" for c in result["comparisons"])
    assert not result["qualified_for_unattended_paper"]
    assert not result["execution_enabled"] and not result["prospective_evidence_verified"]
    assert result["minimum_paper_weeks"] == 8 and result["minimum_closed_trades"] == 100


@pytest.mark.parametrize(
    "failure",
    [
        "shared-ledger",
        "safety",
        "model",
        "prompt",
        "news",
        "baseline",
        "duplicate",
        "post-outcome",
        "late-freeze",
        "future-decision",
    ],
)
def test_mismatch_and_lookahead_rejected(failure):
    data = study_data()
    if failure == "shared-ledger":
        data["arms"][1]["ledger"] = data["arms"][0]["ledger"]
    if failure == "safety":
        data["arms"][1]["safety_hash"] = "0" * 64
    if failure == "model":
        data["arms"][1]["model_hash"] = "0" * 64
    if failure == "prompt":
        data["arms"][1]["prompt_hash"] = None
    if failure == "news":
        data["arms"][1]["news_content"] = True
    if failure == "baseline":
        data["arms"][0]["model_hash"] = "0" * 64
    if failure == "duplicate":
        data["samples"].append(data["samples"][0])
    if failure == "post-outcome":
        data["samples"][1]["decision_at"] = AT + timedelta(seconds=11)
        data["samples"][1]["outcome_at"] = AT + timedelta(seconds=20)
    if failure == "late-freeze":
        data["frozen_at"] = AT + timedelta(seconds=1)
    if failure == "future-decision":
        data["cutoff"] = AT
    with pytest.raises(ValueError):
        Study.model_validate(data)


@pytest.mark.parametrize("missing", ["cost", "outcome", "arm", "future"])
def test_incomplete_pairs_are_explicit_not_zero(missing):
    data = study_data()
    if missing == "cost":
        data["samples"][2]["cost"] = None
    if missing == "outcome":
        data["samples"][2]["outcome_at"] = None
        data["samples"][2]["gross_pnl"] = None
    if missing == "arm":
        data["samples"].pop()
    if missing == "future":
        data["samples"][2]["outcome_at"] = AT + timedelta(days=1)
    result = evaluate(Study.model_validate(data))
    comparison = result["comparisons"][1]
    assert comparison["complete_pairs"] == 0 and comparison["excluded_pairs"] == 1
    assert comparison["mean_net_difference_usd"] is None


def test_summary_keeps_account_economics_unknown_and_gates_open():
    result = summary(demo())
    assert result["operational_outcomes"] == {"HOLD": 1}
    assert result["known_economic_labels"] == {"NOT_APPLICABLE": 1}
    assert all(v is None for v in result["account_metrics"].values())
    assert result["model_usage"]["distinct_requests"] == 1
    assert len(result["gates"]) == 7 and not result["qualified_for_unattended_paper"]


def test_summary_versions_and_conflicting_model_traces_not_double_counted():
    snap = demo()
    decision = snap.records[0]
    conflicting = decision.model_copy(
        update={
            "record_id": uuid4(),
            "supersedes": decision.record_id,
            "body": decision.body.model_copy(
                update={"trace": decision.body.trace.model_copy(update={"input_tokens": 99})}
            ),
        }
    )
    result = summary(snap.model_copy(update={"records": snap.records + (conflicting,)}))
    assert result["corrections"] == 1 and result["decisions"] == {"HOLD": 2}
    assert result["model_usage"]["distinct_requests"] == 1
    assert result["model_usage"]["conflicting_requests"] == 1
    assert result["model_usage"]["input_tokens"] == 0


def test_cli_retains_output_and_unknown_costs(tmp_path, monkeypatch):
    import json
    import sys

    from fx_talanta.evaluation.matched import main

    source = tmp_path / "study.json"
    output = tmp_path / "report.json"
    data = study_data()
    data["samples"][1]["cost"] = "2.5"
    study = Study.model_validate(data)
    source.write_text(study.model_dump_json(), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["matched", "--input", str(source), "--output", str(output)])
    main()
    original = output.read_bytes()
    result = json.loads(original)
    assert result["comparisons"][0]["mean_net_difference_usd"] == "-1.0"
    with pytest.raises(FileExistsError):
        main()
    assert output.read_bytes() == original
