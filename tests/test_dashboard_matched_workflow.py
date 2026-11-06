"""Synthetic chronological receipt acceptance; never opens broker/model connections."""

import hashlib
import json
import shutil
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from uuid import uuid4

import pytest
from test_dashboard import TOKEN
from test_m5_engineering import study_data

from fx_talanta.clock import FakeClock
from fx_talanta.dashboard.app import Dashboard
from fx_talanta.dashboard.demo import AT, demo
from fx_talanta.dashboard.workflow import WorkflowView
from fx_talanta.evaluation.ledger import Ledger, Registration, digest


def fixture_registration():
    data = study_data()
    data.update(
        schema_version="matched-receipt-plan/1", samples=[], run_id=str(uuid4()), max_snapshots=2
    )
    artifacts = {}

    def artifact(label):
        value = "SYNTHETIC fixture: " + label
        sha = hashlib.sha256(value.encode()).hexdigest()
        artifacts[sha] = value
        return sha

    for field in (
        "candidate_hash",
        "dataset_hash",
        "criteria_hash",
        "feature_hash",
        "lessons_hash",
        "news_interpretation_hash",
    ):
        data[field] = artifact(field)
    for arm in data["arms"]:
        for field in ("policy_hash", "safety_hash", "model_hash", "prompt_hash"):
            if arm[field]:
                arm[field] = artifact(field)
    return Registration.model_validate(dict(plan=data, artifacts=artifacts))


def setup(path):
    registration = fixture_registration()
    clock = FakeClock(AT)
    ledger = Ledger.create(path, registration, uuid4(), clock)
    plan_hash = digest(registration.plan.model_dump(mode="json"))
    return ledger, clock, plan_hash


def observe(ledger, plan_hash, content="SYNTHETIC EURUSD input"):
    data = dict(
        snapshot_hash=hashlib.sha256(content.encode()).hexdigest(),
        snapshot_at=ledger.clock.now(),
        content=content,
    )
    ledger.append("OBSERVE", data, uuid4(), expected_plan_hash=plan_hash)
    return data


def decisions(ledger, plan_hash, observation):
    result = []
    for arm in ("NO_AI", "AI_NO_NEWS", "AI_NEWS"):
        data = dict(
            snapshot_hash=observation["snapshot_hash"],
            snapshot_at=observation["snapshot_at"],
            arm=arm,
            decision_id=uuid4(),
            decision_at=ledger.clock.now(),
            decision_hash=hashlib.sha256(b"SYNTHETIC decision, execution disabled").hexdigest(),
            decision_content="SYNTHETIC decision, execution disabled",
            latency_ms=0,
            missed_entry=False,
        )
        ledger.append("DECIDE", data, uuid4(), expected_plan_hash=plan_hash)
        result.append(data)
    return result


def outcome(decision, clock):
    return dict(
        snapshot_hash=decision["snapshot_hash"],
        arm=decision["arm"],
        decision_id=decision["decision_id"],
        outcome_at=clock.now(),
        gross_pnl="2",
        cost="0.5",
        evidence="SYNTHETIC simulated outcome",
    )


def test_receipts_restart_corrections_export_and_close(tmp_path):
    ledger, clock, plan_hash = setup(tmp_path / "receipts.sqlite")
    observation = observe(ledger, plan_hash)
    values = decisions(ledger, plan_hash, observation)
    clock.advance(timedelta(seconds=1))
    event_id = uuid4()
    first = outcome(values[0], clock)
    receipt = ledger.append("OUTCOME", first, event_id, expected_plan_hash=plan_hash)
    resumed = Ledger(ledger.path, clock)
    assert resumed.append("OUTCOME", first, event_id, expected_plan_hash=plan_hash)["replayed"]
    with pytest.raises(ValueError, match="conflicting"):
        resumed.append("OUTCOME", dict(first, cost="1"), event_id, expected_plan_hash=plan_hash)
    corrected = dict(first, cost=None, supersedes=event_id)
    resumed.append("OUTCOME", corrected, uuid4(), expected_plan_hash=plan_hash)
    for value in values[1:]:
        resumed.append("OUTCOME", outcome(value, clock), uuid4(), expected_plan_hash=plan_hash)
    report = resumed.report(plan_hash, (receipt["sequence"], receipt["receipt_hash"]))
    assert report["outcomes"] == 3 and report["revisions"] == 1
    assert report["comparison"]["comparisons"][0]["excluded_pairs"] == 1
    assert report["comparison"]["comparisons"][1]["complete_pairs"] == 1
    assert not report["execution_enabled"] and not report["prospective_evidence_verified"]
    assert not report["qualified_for_unattended_paper"]
    resumed.append(
        "CLOSE", {"reason": "Synthetic acceptance complete"}, uuid4(), expected_plan_hash=plan_hash
    )
    with pytest.raises(ValueError, match="closed"):
        observe(resumed, plan_hash, "second snapshot")
    assert resumed.report(plan_hash)["status"] == "CLOSED"
    with sqlite3.connect(ledger.path) as conn:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("DELETE FROM events")


@pytest.mark.parametrize(
    "failure",
    [
        "late-decision",
        "missing-arm",
        "backdated-outcome",
        "future",
        "wrong-plan",
        "artifact",
        "duplicate-arm",
        "unobserved",
        "late-observation",
        "capacity",
    ],
)
def test_receipt_admission_failures_preserve_evidence(tmp_path, failure):
    ledger, clock, plan_hash = setup(tmp_path / "receipts.sqlite")
    observation = observe(ledger, plan_hash)
    before = ledger.path.read_bytes()
    if failure == "artifact":
        bad = fixture_registration().model_dump(mode="json")
        key = next(iter(bad["artifacts"]))
        bad["artifacts"][key] = "changed"
        with pytest.raises(ValueError):
            Ledger.create(tmp_path / "bad.sqlite", bad, uuid4(), clock)
        assert ledger.path.read_bytes() == before
        return
    decision = dict(
        snapshot_hash=observation["snapshot_hash"],
        snapshot_at=AT,
        arm="NO_AI",
        decision_id=uuid4(),
        decision_at=AT,
        decision_hash=hashlib.sha256(b"SYNTHETIC decision, execution disabled").hexdigest(),
        decision_content="SYNTHETIC decision, execution disabled",
        latency_ms=0,
        missed_entry=False,
    )
    if failure == "wrong-plan":
        with pytest.raises(ValueError, match="binding"):
            ledger.append("DECIDE", decision, uuid4(), expected_plan_hash="0" * 64)
    elif failure == "missing-arm":
        ledger.append("DECIDE", decision, uuid4(), expected_plan_hash=plan_hash)
        clock.advance(timedelta(seconds=1))
        with pytest.raises(ValueError, match="three decisions"):
            ledger.append(
                "OUTCOME", outcome(decision, clock), uuid4(), expected_plan_hash=plan_hash
            )
    elif failure == "unobserved":
        with pytest.raises(ValueError, match="missing observation"):
            ledger.append(
                "DECIDE",
                dict(decision, snapshot_hash="f" * 64),
                uuid4(),
                expected_plan_hash=plan_hash,
            )
    elif failure == "late-observation":
        clock.advance(timedelta(hours=2))
        with pytest.raises(ValueError, match="window"):
            observe(ledger, plan_hash, "late")
        assert ledger.report(plan_hash)["status"] == "WINDOW_EXPIRED"
    elif failure == "capacity":
        observe(ledger, plan_hash, "second")
        with pytest.raises(ValueError, match="limit"):
            observe(ledger, plan_hash, "third")
    else:
        values = decisions(ledger, plan_hash, observation)
        if failure == "duplicate-arm":
            with pytest.raises(ValueError, match="duplicate"):
                ledger.append("DECIDE", decision, uuid4(), expected_plan_hash=plan_hash)
        elif failure == "late-decision":
            clock.advance(timedelta(seconds=1))
            ledger.append(
                "OUTCOME", outcome(values[0], clock), uuid4(), expected_plan_hash=plan_hash
            )
            with pytest.raises(ValueError):
                ledger.append("DECIDE", decision, uuid4(), expected_plan_hash=plan_hash)
        else:
            data = outcome(values[0], clock)
            if failure == "future":
                data["outcome_at"] = AT + timedelta(days=1)
            with pytest.raises(ValueError, match="outcome predates"):
                ledger.append("OUTCOME", data, uuid4(), expected_plan_hash=plan_hash)
    report = ledger.report(plan_hash)
    assert report["outcomes"] == (1 if failure == "late-decision" else 0)


def test_concurrent_retry_is_once_and_clock_rollback_rejected(tmp_path):
    ledger, clock, plan_hash = setup(tmp_path / "receipts.sqlite")
    data = dict(snapshot_hash=hashlib.sha256(b"x").hexdigest(), snapshot_at=AT, content="x")
    event_id = uuid4()

    def append(_):
        return Ledger(ledger.path, clock).append(
            "OBSERVE", data, event_id, expected_plan_hash=plan_hash
        )

    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(append, range(2)))
    assert sorted(r["replayed"] for r in results) == [False, True]
    assert ledger.report(plan_hash)["receipt_sequence"] == 2
    clock._now -= timedelta(seconds=1)
    with pytest.raises(ValueError, match="clock"):
        ledger.report(plan_hash)
    with pytest.raises(ValueError):
        ledger.append("CLOSE", {"reason": "rollback"}, uuid4(), expected_plan_hash=plan_hash)


def test_dashboard_pins_receipt_prefix_and_refuses_rebinding(tmp_path):
    ledger, clock, plan_hash = setup(tmp_path / "receipts.sqlite")
    saved = tmp_path / "older.sqlite"
    shutil.copyfile(ledger.path, saved)
    config = dict(journal=str(ledger.path), plan_hash=plan_hash)
    app = Dashboard(demo(), tmp_path / "ui", TOKEN, clock, workflow_view=WorkflowView(config))
    try:
        assert app.overview()["matched_workflow"]["status"] == "REGISTERED"
        observe(ledger, plan_hash)
        assert app.overview()["matched_workflow"]["observations"] == 1
    finally:
        app.close()
    shutil.copyfile(saved, ledger.path)
    app = Dashboard(demo(), tmp_path / "ui", TOKEN, clock, workflow_view=WorkflowView(config))
    try:
        assert app.overview()["matched_workflow"]["status"] == "UNAVAILABLE"
    finally:
        app.close()
    with pytest.raises(ValueError, match="rebind"):
        Dashboard(
            demo(),
            tmp_path / "ui",
            TOKEN,
            clock,
            workflow_view=WorkflowView(dict(config, plan_hash="f" * 64)),
        )


def test_cli_export_is_importable_and_does_not_overwrite(tmp_path, monkeypatch):
    import sys

    from fx_talanta.evaluation.ledger import main
    from fx_talanta.evaluation.matched import Study

    ledger, clock, plan_hash = setup(tmp_path / "receipts.sqlite")
    decisions(ledger, plan_hash, observe(ledger, plan_hash))
    output = tmp_path / "study.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "ledger",
            "export",
            "--journal",
            str(ledger.path),
            "--plan-hash",
            plan_hash,
            "--output",
            str(output),
        ],
    )
    main()
    study = Study.model_validate_json(output.read_bytes())
    assert len(study.samples) == 3 and study.provenance == "SYNTHETIC"
    with pytest.raises(FileExistsError):
        main()
    report = ledger.report(plan_hash)
    assert report["missing_decisions"] == 0 and report["pending_outcomes"] == 3
    assert json.loads(output.read_bytes())["execution_enabled"] is False


def test_tamper_duplicate_creation_and_observation_without_decisions(tmp_path):
    ledger, clock, plan_hash = setup(tmp_path / "receipts.sqlite")
    with pytest.raises(FileExistsError):
        Ledger.create(ledger.path, fixture_registration(), uuid4(), clock)
    observe(ledger, plan_hash)
    report = ledger.report(plan_hash)
    assert report["observations_without_decisions"] == 1
    assert report["missing_decisions"] == 3 and report["comparison"] is None
    with sqlite3.connect(ledger.path) as conn:
        conn.execute(
            "DROP TRIGGER no_change"
        )  # Simulate local-file corruption, not normal API use.
        conn.execute("UPDATE events SET sha=? WHERE seq=2", ("f" * 64,))
    with pytest.raises(ValueError, match="chain"):
        ledger.report(plan_hash)
    with pytest.raises(ValueError, match="chain"):
        ledger.append(
            "CLOSE",
            {"reason": "must not append to corrupt journal"},
            uuid4(),
            expected_plan_hash=plan_hash,
        )


def test_outcome_cannot_use_backdated_decisions_received_after_the_event(tmp_path):
    ledger, clock, plan_hash = setup(tmp_path / "receipts.sqlite")
    observation = observe(ledger, plan_hash)
    clock.advance(timedelta(seconds=10))
    values = decisions(ledger, plan_hash, observation)
    data = outcome(values[0], clock)
    data["outcome_at"] = AT + timedelta(seconds=5)
    with pytest.raises(ValueError, match="receipt"):
        ledger.append("OUTCOME", data, uuid4(), expected_plan_hash=plan_hash)
    assert ledger.report(plan_hash)["pending_outcomes"] == 3
