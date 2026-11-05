import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from fx_talanta.research.replay import digest
from fx_talanta.research.session_study import engine_hash, verify_phase, write
from fx_talanta.research.spool import file_hash
from tests.test_session_study import source
from tools.fixtures.b01_replay import scenario
from tools.qualification.walkforward import Session, run, run_job, verdict, wrapper_hash
from tools.qualification.walkforward_report import report


def setup(tmp_path):
    _, index = source(tmp_path)
    _, example = scenario()
    start = datetime(2025, 1, 16, tzinfo=UTC)
    session = Session(
        name="fixture",
        symbol="EURUSD",
        start=start,
        end=start + timedelta(days=1),
        costs=example.costs,
        policy=example.policy,
    )
    job = {
        "session": session.model_dump(mode="json"),
        "expected_ticks": 6,
        "fold": "fixture",
        "role": "walkforward",
        "arm": "base",
        "prior_h1_bars": 0,
    }
    manifest = {
        "paths": {"EURUSD": str(index)},
        "protocol": {"index_hashes": {"EURUSD": file_hash(index)}, "latency_ms": 250},
        "jobs": [job],
        "engine_sha256": engine_hash(),
        "wrapper_sha256": wrapper_hash(),
        "runtime": {"scope": "fixture"},
    }
    directory = tmp_path / "study"
    directory.mkdir()
    write(directory / "manifest.json", manifest)
    write(directory / "registration.json", {"manifest_hash": digest(manifest)})
    return directory, manifest, job


def test_session_sinks_reconstruction_and_no_retry(tmp_path):
    directory, manifest, job = setup(tmp_path)
    result = run_job(directory, manifest, job)
    assert result["fully_settled"]
    assert result["coverage"]["ticks"] == 6
    assert result["fill_ledger_verification"]["balance_from_fills"]
    verify_phase(directory / "fixture", manifest, full=True)
    with pytest.raises(FileExistsError):
        run_job(directory, manifest, job)


def test_failed_source_count_is_preserved_and_stops(tmp_path):
    directory, manifest, job = setup(tmp_path)
    job["expected_ticks"] = 7
    with pytest.raises(ValueError, match="reconciliation"):
        run_job(directory, manifest, job)
    assert (directory / "fixture" / "failed.json").exists()
    assert not (directory / "fixture" / "verified.json").exists()


def test_changed_registry_refused_before_start(tmp_path):
    directory, manifest, job = setup(tmp_path)
    manifest["jobs"][0]["arm"] = "changed"
    (directory / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="registry"):
        run(directory)
    assert not (directory / "started.json").exists()


def test_independent_report_rebuilds_and_rejects_changed_claim(tmp_path):
    directory, manifest, job = setup(tmp_path)
    run(directory)
    result = report(directory)
    assert result["completed_sessions"] == 1
    assert result["independently_verified"]
    assert result["sessions"][0]["source_rows_independently_counted"] == 6
    assert result["verdict"] == "INSUFFICIENT_EVIDENCE_INCOMPLETE"
    path = directory / "conclusion.json"
    damaged = json.loads(path.read_text())
    damaged["no_trade_comparator"]["return_percent"] = "-1"
    path.write_text(json.dumps(damaged))
    with pytest.raises(ValueError, match="comparator"):
        report(directory)


def test_frozen_protocol_has_new_outcome_holdout_and_unchanged_limits():
    path = (
        Path(__file__).resolve().parents[1] / "docs/evidence/m3-walkforward-protocol-20261105.json"
    )
    protocol = json.loads(path.read_text())
    days = [f["evaluation_start"][:10] for f in protocol["folds"]]
    assert days == sorted(set(days))
    assert not set(days) & set(protocol["prior_outcomes_examined"])
    assert len([f for f in protocol["folds"] if f["role"] == "walkforward"]) == 3
    assert protocol["folds"][-1]["role"] == "final_holdout"
    assert protocol["policy"]["quote_age_seconds"] == 2
    assert not protocol["execution_enabled"]


def test_verdict_is_not_a_statistical_or_operating_pass():
    assert verdict([]) == "INSUFFICIENT_EVIDENCE_INCOMPLETE"
    assert verdict([{"fully_settled": False}]) == "INSUFFICIENT_EVIDENCE_UNRESOLVED_EXPOSURE"
    sessions = [
        {
            "fully_settled": True,
            "role": role,
            "symbol": symbol,
            "arm": arm,
            "net_realized_return_percent": "0.1",
        }
        for role in ("walkforward", "walkforward", "walkforward", "final_holdout")
        for symbol in ("EURUSD", "USDJPY")
        for arm in ("base", "stress")
    ]
    assert verdict(sessions) == "KEEP_FOR_FURTHER_RESEARCH_ONLY"
    sessions[-1]["net_realized_return_percent"] = "-0.01"
    assert verdict(sessions) == "REJECT_FOR_PROMOTION"
