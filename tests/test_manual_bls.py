import sys
from contextlib import closing
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from test_bls_calendar import calendar

from fx_talanta.manual_bls import main, status, upload
from fx_talanta.provider_pipeline import Journal

NOW = datetime(2026, 11, 3, tzinfo=UTC)


def seed(tmp_path):
    source = tmp_path / "bls.ics"
    source.write_bytes(calendar(start="20261206T083000"))
    return tmp_path / "store", source


def test_missing_upload_and_no_background_work(tmp_path):
    store = tmp_path / "missing"
    result = status(store, clock=lambda: NOW)
    assert result["reasons"] == ["NO_UPLOAD"]
    assert result["reminder_due"] and not store.exists()


def test_upload_archive_due_date_and_shared_filter(tmp_path):
    store, source = seed(tmp_path)
    result = upload(store, source, clock=lambda: NOW)
    assert not result["reminder_due"]
    assert result["review_due_at"] == (NOW + timedelta(days=7)).isoformat()
    assert not result["qualified_for_trading"] and not result["execution_enabled"]
    assert (
        store / "archive" / (result["source_hash"] + ".ics")
    ).read_bytes() == source.read_bytes()
    with closing(Journal(store / "journal.sqlite")) as journal:
        inputs = journal.inputs(NOW)
        assert inputs.provenance == "PROVIDER_SHADOW"
        assert len(inputs.calendar) == 1
        result = journal.evaluate("EURUSD", NOW)
        assert not result.calendar_ok and not result.news_ok
    assert "REVIEW_OVERDUE" in status(store, clock=lambda: NOW + timedelta(days=7))["reasons"]


def test_duplicate_does_not_snooze_unless_manually_confirmed(tmp_path):
    store, source = seed(tmp_path)
    upload(store, source, clock=lambda: NOW)
    later = NOW + timedelta(days=8)
    duplicate = upload(store, source, clock=lambda: later)
    assert duplicate["upload_result"] == "UNCHANGED"
    assert "REVIEW_OVERDUE" in duplicate["reasons"]
    confirmed = upload(store, source, reviewed_latest=True, clock=lambda: later)
    assert confirmed["last_reviewed_at"] == later.isoformat()
    assert not confirmed["reminder_due"]
    with closing(Journal(store / "journal.sqlite")) as journal:
        assert journal.conn.execute("SELECT count(*) FROM revisions").fetchone()[0] == 1
        assert journal.inputs(later).checks[0].complete is False
        assert journal.inputs(NOW).calendar[0].available_at == NOW


def test_invalid_upload_preserves_previous_and_requests_action(tmp_path):
    store, source = seed(tmp_path)
    first = upload(store, source, clock=lambda: NOW)
    source.write_bytes(b"<html>Access denied</html>")
    with pytest.raises(ValueError, match="preserved"):
        upload(store, source, clock=lambda: NOW + timedelta(seconds=1))
    result = status(store, clock=lambda: NOW + timedelta(seconds=2))
    assert result["source_hash"] == first["source_hash"]
    assert "LAST_UPLOAD_FAILED_OR_INTERRUPTED" in result["reasons"]


def test_revisions_and_archive_corruption(tmp_path):
    store, source = seed(tmp_path)
    first = upload(store, source, clock=lambda: NOW)
    source.write_bytes(calendar(start="20261207T083000", sequence=1))
    with pytest.raises(ValueError):
        upload(store, source, clock=lambda: NOW)
    source.write_bytes(calendar(start="20261207T083000", sequence=2))
    second = upload(store, source, clock=lambda: NOW)
    assert first["source_hash"] != second["source_hash"]
    assert len(list((store / "archive").glob("*.ics"))) == 2
    (store / "archive" / (second["source_hash"] + ".ics")).write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="integrity"):
        status(store, clock=lambda: NOW)


def test_running_out_clock_rollback_and_interrupted_attempt(tmp_path):
    store, source = seed(tmp_path)
    source.write_bytes(calendar(start="20261106T083000"))
    result = upload(store, source, clock=lambda: NOW)
    assert "SCHEDULE_RUNNING_OUT" in result["reasons"]
    assert "CLOCK_ROLLBACK" in status(store, clock=lambda: NOW - timedelta(seconds=1))["reasons"]
    with closing(Journal(store / "journal.sqlite")) as journal:
        journal.begin("bls", NOW)
    assert "LAST_UPLOAD_FAILED_OR_INTERRUPTED" in status(store, clock=lambda: NOW)["reasons"]


def test_cli_file_upload_and_cancellation(tmp_path, monkeypatch, capsys):
    store, source = seed(tmp_path)
    assert main(["--store", str(store), "upload", "--file", str(source)]) == 0
    assert "IMPORTED" in capsys.readouterr().out
    monkeypatch.setattr("fx_talanta.manual_bls.choose_file", lambda: "")
    assert main(["--store", str(store), "upload", "--choose"]) == 0
    assert "cancelled" in capsys.readouterr().out


@pytest.mark.parametrize("failure_stage", ["create", "dialog"])
def test_desktop_failure_has_cli_fallback_and_does_not_create_store(
    tmp_path, monkeypatch, capsys, failure_stage
):
    # CI may lack Tk/a display. This exercises error handling only; native picker
    # acceptance is recorded separately in docs/manual-bls-windows-verification.md.
    class DesktopError(Exception):
        pass

    window = Mock()
    create = Mock(return_value=window)
    dialog = Mock(side_effect=DesktopError("desktop unavailable"))
    if failure_stage == "create":
        create.side_effect = DesktopError("desktop unavailable")
    monkeypatch.setitem(
        sys.modules,
        "tkinter",
        SimpleNamespace(
            Tk=create,
            TclError=DesktopError,
            Label=Mock(),
            filedialog=SimpleNamespace(askopenfilename=dialog),
        ),
    )
    store = tmp_path / "store"
    assert main(["--store", str(store), "upload", "--choose"]) == 2
    assert "use --file" in capsys.readouterr().out
    assert not store.exists()
    assert window.destroy.call_count == (failure_stage == "dialog")
