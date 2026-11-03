from copy import deepcopy
from datetime import timedelta

from test_fred_calendar_html import NOW, inputs, page

from fx_talanta import calendar_qualification as campaign


def test_success_outage_recovery_preserves_baseline_and_failure_chain(monkeypatch):
    dates, reference = inputs()
    monkeypatch.setattr(campaign.fred, "collect", lambda *a, **kw: dates)
    monkeypatch.setattr(campaign.bls, "import_calendar", lambda raw: reference)
    monkeypatch.setattr(campaign.bls, "refresh", lambda: (None, "HTTP_403"))
    original = campaign.html.qualify
    fail = False

    def fetch(day):
        if fail:
            raise OSError("unavailable")
        return page(day)

    monkeypatch.setattr(campaign.html, "qualify", lambda *a, **kw: original(*a, fetch=fetch, **kw))

    # Match the fixture clock without changing timestamps in production inputs.
    class Clock(type(NOW)):
        @classmethod
        def now(cls, tz=None):
            return NOW

    monkeypatch.setattr(campaign.html, "datetime", Clock)
    first = campaign.attempt("key", dates.window_start, dates.window_end, b"reference")
    unchanged = deepcopy(first)
    fail = True
    failed = campaign.attempt(
        "key", dates.window_start, dates.window_end, b"reference", previous=first
    )
    assert not failed["comparison"]["comparison_passed"]
    assert failed["comparison_baseline"] == first["comparison"]
    assert not failed["comparison"]["matches"]
    fail = False
    recovered = campaign.attempt(
        "key", dates.window_start, dates.window_end, b"reference", previous=failed
    )
    assert recovered["comparison"]["comparison_passed"]
    assert first == unchanged
    assert recovered["previous_attempt_hash"] != failed["previous_attempt_hash"]
    assert recovered["bls_refresh"]["snapshot"] is None
    assert recovered["bls_refresh"]["error"] == "HTTP_403"
    assert all(
        r["block_entries"] and not r["qualified_for_trading"] for r in (first, failed, recovered)
    )
    # An outage must not hide a reschedule on recovery.
    monkeypatch.setattr(
        campaign.html,
        "qualify",
        lambda *a, **kw: original(*a, fetch=lambda d: page(d, "8:00 am"), **kw),
    )
    changed = campaign.attempt(
        "key", dates.window_start, dates.window_end, b"reference", previous=failed
    )
    assert "SCHEDULE_CHANGED_REVIEW_REQUIRED" in changed["comparison"]["reasons"]
    assert changed["comparison_baseline"] == first["comparison"]
    # Replayed stale API evidence cannot trigger HTML fetching or revive success.
    dates = dates.model_copy(update={"started_at": NOW - timedelta(seconds=121)})
    stale = campaign.attempt(
        "key", dates.window_start, dates.window_end, b"reference", previous=first
    )
    assert not stale["comparison"]["pages"]
    assert "FRED_DATES_STALE_OR_UNAVAILABLE" in stale["comparison"]["reasons"]


def test_existing_output_prevents_collection(tmp_path, monkeypatch):
    output = tmp_path / "attempt.json"
    output.write_text("preserved")
    reference = tmp_path / "reference.ics"
    reference.write_text("fixture")
    monkeypatch.setattr(
        campaign,
        "attempt",
        lambda *a, **kw: (_ for _ in ()).throw(AssertionError("network must not run")),
    )
    assert (
        campaign.main(
            [
                "--env-file",
                str(tmp_path / "missing.env"),
                "--bls-reference",
                str(reference),
                "--start",
                "2026-11-02",
                "--end",
                "2026-12-02",
                "--output",
                str(output),
            ]
        )
        == 2
    )
    assert output.read_text() == "preserved"
