import json
import zipfile
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from fx_talanta.research.historical import import_zip
from fx_talanta.research.replay import execute_timeline, run
from fx_talanta.research.session_study import (
    Plan,
    execute_phase,
    register_study,
    timeline,
    verify_phase,
)
from fx_talanta.research.spool import EquitySpool, Spool, rows
from fx_talanta.research.tick_index import TickIndex, build_index
from tools.fixtures.b01_replay import scenario


def source(tmp_path):
    archive = tmp_path / "source.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr(
            "DAT_ASCII_EURUSD_T_202501.csv",
            "\n".join(
                [
                    "20250116 060000000,1.1,1.1001,0",
                    "20250116 070000000,1.101,1.1011,0",
                    "20250116 070000000,1.102,1.1021,0",
                    "20250116 070000000,1.102,1.1021,0",
                    "20250116 080000000,1.103,1.1031,0",
                    "20250116 090000000,1.103,1.1031,0",
                ]
            ),
        )
    build_index(archive, "EURUSD", tmp_path / "index")
    return archive, tmp_path / "index" / "ticks.sqlite"


def test_index_matches_original_import_including_ties(tmp_path):
    archive, path = source(tmp_path)
    start = datetime(2025, 1, 16, 12, tzinfo=UTC)
    end = start + timedelta(hours=1)
    original, _ = import_zip(archive, "EURUSD", start, end)
    index = TickIndex(path)
    try:
        assert tuple(index.events(start, end, 250, False)) == original.events
        assert {b.model_dump_json() for b in index.bars(250) if b.close_at <= end} == {
            b.model_dump_json() for b in original.bars
        }
    finally:
        index.close()


def test_streamed_engine_matches_original_financial_and_audit_results(tmp_path):
    data, experiment = scenario()
    expected, journal = run(data, experiment, "training")
    start, end = experiment.window("training")
    audit = Spool(tmp_path / "journal.gz")
    equity = EquitySpool(tmp_path / "equity.gz", experiment.policy.capital)
    actual, _ = execute_timeline(
        data,
        experiment,
        "training",
        timeline(data.bars, data.events, start, end),
        UUID(expected["run_id"]),
        journal_sink=audit,
        samples_sink=equity,
    )
    audit.close()
    equity.close()
    actual["equity_samples"] = list(rows(equity.path))
    assert actual == expected
    assert list(rows(audit.path)) == journal


def test_exclusive_phase_verified_receipt_and_tampering(tmp_path):
    _, path = source(tmp_path)
    _, template = scenario()
    start = datetime(2025, 1, 16, 12, tzinfo=UTC)
    experiment = template.model_copy(
        update={
            "start": start,
            "training_end": start + timedelta(hours=1),
            "validation_end": start + timedelta(hours=2),
            "end": start + timedelta(hours=3),
        }
    )
    plan = Plan(experiments=(experiment,), description="Synthetic lifecycle test")
    study = tmp_path / "study"
    manifest = register_study(study, plan, {"EURUSD": path})
    result = execute_phase(study, "EURUSD", "training")
    assert result["fully_settled"] and not result["execution_enabled"]
    output = study / "EURUSD-training"
    assert verify_phase(output, manifest) == result
    with pytest.raises(FileExistsError):
        execute_phase(study, "EURUSD", "training")
    (output / "verified.json").unlink()
    with pytest.raises(FileNotFoundError):
        execute_phase(study, "EURUSD", "validation")
    assert not (study / "EURUSD-validation").exists()
    (output / "verified.json").write_text(json.dumps({"reconstructed": True, "result_hash": "bad"}))
    with pytest.raises(ValueError, match="verification"):
        verify_phase(output, manifest)
    with (output / "equity.jsonl.gz").open("ab") as stream:
        stream.write(b"corrupt")
    with pytest.raises(ValueError, match="artifact"):
        verify_phase(output, manifest, full=True)


def test_spool_enforces_bounds_and_exclusive_creation(tmp_path, monkeypatch):
    from fx_talanta.research import spool

    monkeypatch.setattr(spool, "MAX_LINE", 10)
    stream = Spool(tmp_path / "a.gz")
    with pytest.raises(ValueError, match="bound"):
        stream.append({"long": "x" * 20})
    stream.close()
    with pytest.raises(FileExistsError):
        Spool(stream.path)


def test_unsettled_or_failed_prior_partition_cannot_advance(tmp_path, monkeypatch):
    from fx_talanta.research import session_study

    _, path = source(tmp_path)
    _, experiment = scenario()
    study = tmp_path / "study"
    register_study(
        study, Plan(experiments=(experiment,), description="Boundary test"), {"EURUSD": path}
    )
    monkeypatch.setattr(session_study, "verify_phase", lambda *a, **kw: {"fully_settled": False})
    with pytest.raises(ValueError, match="exposure unresolved"):
        execute_phase(study, "EURUSD", "validation")
    assert not (study / "EURUSD-validation").exists()


def test_registered_source_change_is_rejected_before_output(tmp_path, monkeypatch):
    from fx_talanta.research import session_study

    _, path = source(tmp_path)
    _, experiment = scenario()
    study = tmp_path / "study"
    register_study(
        study, Plan(experiments=(experiment,), description="Pinning test"), {"EURUSD": path}
    )
    monkeypatch.setattr(session_study, "engine_hash", lambda: "changed")
    with pytest.raises(ValueError, match="engine or plan changed"):
        execute_phase(study, "EURUSD", "training")
    assert not (study / "EURUSD-training").exists()


def test_invalid_archive_preserves_failure_and_cannot_be_read(tmp_path):
    archive = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("DAT_ASCII_EURUSD_T_202501.csv", "20250116 070000000,2,1,0")
    with pytest.raises(ValueError, match="quote"):
        build_index(archive, "EURUSD", tmp_path / "failed-index")
    assert (tmp_path / "failed-index" / "failed.json").exists()
    with pytest.raises((ValueError, TypeError)):
        TickIndex(tmp_path / "failed-index" / "ticks.sqlite")


def test_report_reconstructs_fills_and_rejects_invented_balance():
    from tools.qualification.session_report import reconcile_fills

    data, experiment = scenario()
    result, _ = run(data, experiment, "training")
    assert reconcile_fills(result)["exposure_from_fills"]
    result["balance"] = "999999"
    with pytest.raises(ValueError, match="balance mismatch"):
        reconcile_fills(result)
