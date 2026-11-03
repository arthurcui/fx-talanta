import json
from contextlib import closing
from datetime import timedelta
from pathlib import Path

import pytest
from test_mt5_calendar import EPOCH, NOW, export, policy

from fx_talanta.calendar_collector import Deployment, collect
from fx_talanta.provider_pipeline import Journal, status_lock


def setup(tmp_path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    config = Deployment(
        inbox=inbox,
        installed_at=NOW - timedelta(seconds=1),
        expires_at=NOW + timedelta(days=1),
        server_from=EPOCH + 7200 - 3600,
        server_until=EPOCH + 7200 + 86400,
        clock_policy=policy(),
    )
    (tmp_path / "deployment.json").write_text(config.model_dump_json())
    return inbox


def put(inbox, raw, suffix="1"):
    (inbox / f"fx-calendar-fixture_calendar-{suffix}.json").write_bytes(raw)


def test_restart_deduplication_and_producer_freshness(tmp_path):
    inbox = setup(tmp_path)
    put(inbox, export())
    assert collect(tmp_path, NOW + timedelta(seconds=2))["state"] == "FRESH"
    restarted = collect(tmp_path, NOW + timedelta(seconds=60))
    assert restarted["imported_snapshots"] == 0
    assert restarted["export_age_seconds"] == 59
    stale = collect(tmp_path, NOW + timedelta(seconds=122))
    assert stale["state"] == "STALE"
    with closing(Journal(tmp_path / "journal.sqlite")) as journal:
        assert journal.conn.execute("SELECT count(*) FROM outcomes").fetchone()[0] == 1
        checks = journal.inputs(NOW + timedelta(seconds=122)).checks
        assert checks[0].connection == "FAILED"
        assert checks[0].checked_at == NOW + timedelta(seconds=1)
        assert not journal.evaluate("EURUSD", NOW + timedelta(seconds=122)).calendar_ok
    assert len(list((tmp_path / "archive").glob("*.json"))) == 1


def test_partial_file_and_interrupted_attempt_recovery(tmp_path):
    inbox = setup(tmp_path)
    (inbox / "partial.tmp").write_bytes(b'{"unfinished":')
    assert collect(tmp_path, NOW)["state"] == "WAITING"
    with closing(Journal(tmp_path / "journal.sqlite")) as journal:
        journal.begin("mt5_calendar", NOW)
    assert collect(tmp_path, NOW + timedelta(seconds=1))["state"] == "FAILED"
    put(inbox, export())
    assert collect(tmp_path, NOW + timedelta(seconds=2))["state"] == "FRESH"
    with closing(Journal(tmp_path / "journal.sqlite")) as journal:
        assert journal.conn.execute("SELECT count(*) FROM attempts").fetchone()[0] == 2
        assert journal.conn.execute("SELECT count(*) FROM outcomes").fetchone()[0] == 1


def test_failure_and_subsequent_fresh_recovery_preserve_evidence(tmp_path):
    inbox = setup(tmp_path)
    put(inbox, export())
    collect(tmp_path, NOW + timedelta(seconds=2))
    put(inbox, export(error_code=5401), "2")
    assert collect(tmp_path, NOW + timedelta(seconds=3))["state"] == "FAILED"
    put(inbox, export(started_utc=EPOCH + 60, finished_utc=EPOCH + 61), "3")
    assert collect(tmp_path, NOW + timedelta(seconds=62))["state"] == "FRESH"
    with closing(Journal(tmp_path / "journal.sqlite")) as journal:
        assert journal.conn.execute("SELECT count(*) FROM outcomes").fetchone()[0] == 3
        assert journal.conn.execute("SELECT count(*) FROM revisions").fetchone()[0] == 1
        assert (
            journal.conn.execute("SELECT count(*) FROM outcomes WHERE status='FAILED'").fetchone()[
                0
            ]
            == 1
        )


def test_expiry_stop_window_and_identity_guards(tmp_path):
    inbox = setup(tmp_path)
    put(inbox, export(server_from=EPOCH))
    assert collect(tmp_path, NOW + timedelta(seconds=2))["state"] == "FAILED"
    assert collect(tmp_path, NOW + timedelta(days=1))["state"] == "EXPIRED"
    (inbox / "STOP").touch()
    assert collect(tmp_path, NOW + timedelta(seconds=4))["state"] == "STOPPED"
    config = json.loads((tmp_path / "deployment.json").read_text())
    config["expires_at"] = (NOW + timedelta(hours=1)).isoformat()
    (tmp_path / "deployment.json").write_text(json.dumps(config))
    with pytest.raises(ValueError, match="deployment changed"):
        collect(tmp_path, NOW + timedelta(seconds=5))


def test_concurrent_collector_is_rejected(tmp_path):
    setup(tmp_path)
    with status_lock(tmp_path / "journal.collector"), pytest.raises(OSError):
        collect(tmp_path, NOW)


def test_service_has_no_trading_and_expires_without_terminal_shutdown():
    root = Path(__file__).resolve().parents[1]
    source = (root / "bridges/mt5/CalendarService.mq5").read_text()
    for forbidden in ("OrderSend(", "CTrade", "#import", "WebRequest(", "TerminalClose("):
        assert forbidden not in source
    assert "TimeGMT()<StopAtUTC" in source
    assert "initial_login" in source and "FILE_WRITE|FILE_BIN" in source
    assert "Sleep(250)" in source
