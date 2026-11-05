import json
from contextlib import closing
from datetime import UTC, datetime, timedelta

import pytest

from fx_talanta.bea_calendar import FAMILIES, parse
from fx_talanta.provider_pipeline import Journal

NOW = datetime(2026, 11, 5, tzinfo=UTC)


def raw(value="2026-11-25T08:30:00-05:00"):
    return json.dumps(
        {
            **{k: {"release_dates": [value, value]} for k in FAMILIES},
            "file_last_updated": "2026-11-04",
        }
    ).encode()


def store(journal, at, body):
    snapshot = parse(body, at)
    attempt = journal.begin("bea", at)
    journal.finish(attempt, {"status": "OK", "payload": snapshot.model_dump(mode="json")}, at)


def test_normalization_dedup_and_date_only():
    snapshot = parse(raw(), NOW)
    assert snapshot.duplicate_count == 2
    assert len(snapshot.events) == 2
    assert all(e.scheduled_at.hour == 13 for e in snapshot.events)
    assert all(e.original_time.endswith("-05:00") for e in snapshot.events)
    dates = parse(raw("2026-11-25"), NOW)
    assert all(e.scheduled_at is None and e.precision == "DATE_ONLY" for e in dates.events)


@pytest.mark.parametrize("value", ["2026-11-25T08:30:00", "bad", "2026-02-30", None])
def test_reject_unknown_or_naive_time(value):
    with pytest.raises(ValueError):
        parse(raw(value), NOW)


def test_missing_family_and_duplicate_json_key_fail():
    with pytest.raises(KeyError):
        parse(b"{}", NOW)
    with pytest.raises(ValueError):
        parse(b'{"x":1,"x":2}', NOW)


def test_restart_replay_reschedule_and_failure_preserve_blackouts(tmp_path):
    path = tmp_path / "journal.sqlite"
    with closing(Journal(path, create=True)) as journal:
        store(journal, NOW, raw())
    with closing(Journal(path)) as journal:
        store(journal, NOW + timedelta(seconds=1), raw("2026-11-25T13:30:00+00:00"))
        assert len(journal.inputs(NOW + timedelta(seconds=1)).calendar) == 2
        store(journal, NOW + timedelta(seconds=2), raw("2026-11-26T13:30:00+00:00"))
        # No source ID identifies a moved release: retain both possible blackouts.
        assert len(journal.inputs(NOW + timedelta(seconds=2)).calendar) == 4
        store(journal, NOW + timedelta(seconds=3), raw("2026-11-26"))
        assert len(journal.inputs(NOW + timedelta(seconds=3)).calendar) == 4
        failed_at = NOW + timedelta(seconds=4)
        attempt = journal.begin("bea", failed_at)
        journal.finish(attempt, {"status": "FAILED"}, failed_at)
        assert len(journal.inputs(failed_at).calendar) == 4
        assert len(journal.inputs(NOW).calendar) == 2
        result = journal.evaluate("EURUSD", failed_at)
        assert not result.execution_enabled and not result.calendar_ok
        store(journal, NOW + timedelta(seconds=5), raw())
        assert len(journal.inputs(NOW + timedelta(seconds=5)).calendar) == 4
        assert all(not c.complete for c in journal.inputs(NOW + timedelta(seconds=5)).checks)


def test_date_only_never_enters_exact_calendar(tmp_path):
    with closing(Journal(tmp_path / "dates.sqlite", create=True)) as journal:
        store(journal, NOW, raw("2026-11-25"))
        assert not journal.inputs(NOW).calendar
        assert not journal.evaluate("USDJPY", NOW).calendar_ok
