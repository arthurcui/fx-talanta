import urllib.error
from datetime import UTC, date, datetime, timedelta

import pytest

from fx_talanta import fred_calendar_html as html
from fx_talanta.bls_calendar import BlsEvent, BlsSnapshot
from fx_talanta.fred_calendar import RELEASES, ReleaseDate, Snapshot

NOW = datetime(2026, 11, 2, 22, tzinfo=UTC)
DAY = date(2026, 11, 6)


@pytest.fixture(autouse=True)
def fixed_clock(monkeypatch):
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW.astimezone(tz)

    monkeypatch.setattr(html, "datetime", Clock)


def page(day=DAY, clock="7:30 am"):
    rows = "".join(
        f'<tr><td>{clock}</td><td><a href="/release?rid={rid}">{name}</a></td></tr>'
        for rid, name in RELEASES.items()
    )
    return (
        f'<input id="rc-vs" value="{day}"><input id="rc-ve" value="{day}">'
        '<select><option value="50">Employment Situation</option></select>'
        '<div id="release-dates-pager"><table class="table-standard-theme">'
        f'<tr><td colspan="2">{day:%A %B} {day.day:02d}, {day.year}</td></tr>{rows}'
        "</table><table><tr><td>Pagination</td></tr></table></div>"
        "<p>All times are US Central Time.</p>"
    ).encode()


def inputs():
    fred = Snapshot(
        started_at=NOW,
        available_at=NOW,
        window_start=NOW.date(),
        window_end=date(2026, 12, 2),
        status="OK",
        dates=tuple(ReleaseDate(release_id=rid, date=DAY) for rid in RELEASES),
    )
    bls = BlsSnapshot(
        source_hash="a" * 64,
        imported_at=NOW,
        provenance="MANUAL_FILE",
        events=tuple(
            BlsEvent(
                uid=str(rid),
                sequence=1,
                release_id=rid,
                scheduled_at="2026-11-06T13:30:00Z",
                status="CONFIRMED",
            )
            for rid in RELEASES
        ),
    )
    return fred, bls


def test_only_results_table_and_correct_timezone():
    result = html.parse_times(page(), DAY, RELEASES)
    assert len(result) == 4 and result[50] == datetime(2026, 11, 6, 13, 30, tzinfo=UTC)
    assert html.parse_times(page(date(2026, 7, 6)), date(2026, 7, 6), RELEASES)[50].hour == 12


@pytest.mark.parametrize(
    "old,new",
    [
        (b"7:30 am", b"N/A"),
        (b"All times are US Central Time.", b"All times are UTC."),
        (b"table-standard-theme", b"unknown-table"),
        (b"Friday November 06, 2026", b"Saturday November 07, 2026"),
        (b"/release?rid=50", b"/release?rid=999"),
        (b"</table>", b""),
        (b"Consumer Price Index", b"Changed title"),
    ],
)
def test_missing_or_changed_structure_fails(old, new):
    with pytest.raises(ValueError):
        html.parse_times(page().replace(old, new), DAY, RELEASES)


def test_dropdown_only_and_duplicate_rows_are_not_evidence():
    with pytest.raises(ValueError):
        html.parse_times(b'<option value="50">Employment Situation</option>', DAY, [50])
    duplicate = (
        b'<tr><td>7:30 am</td><td><a href="/release?rid=50">Employment Situation</a></td></tr>'
    )
    with pytest.raises(ValueError):
        html.parse_times(page().replace(b"</table>", duplicate + b"</table>", 1), DAY, RELEASES)


def test_repeated_comparison_preserves_history_without_qualification():
    first = html.qualify(*inputs(), fetch=lambda day: page(day))
    second = html.qualify(*inputs(), fetch=lambda day: page(day), previous=first)
    assert first["comparison_passed"] and second["comparison_passed"]
    assert second["previous_hash"] and second["block_entries"]
    assert not second["qualified_for_trading"] and not second["execution_enabled"]


def test_rescheduled_time_blocks_and_preserves_previous():
    first = html.qualify(*inputs(), fetch=lambda day: page(day))
    second = html.qualify(*inputs(), fetch=lambda day: page(day, "8:00 am"), previous=first)
    assert not second["comparison_passed"]
    assert set(second["reasons"]) == {
        "BLS_TIME_CONFLICT_OR_MISSING",
        "SCHEDULE_CHANGED_REVIEW_REQUIRED",
    }
    assert first["comparison_passed"]


@pytest.mark.parametrize("status", [403, 429, 500])
def test_refresh_failure_cannot_reuse_success(status):
    first = html.qualify(*inputs(), fetch=lambda day: page(day))

    def failed(day):
        raise urllib.error.HTTPError("https://fred.stlouisfed.org", status, "error", {}, None)

    second = html.qualify(*inputs(), fetch=failed, previous=first)
    assert not second["comparison_passed"] and not second["matches"]
    assert second["pages"][0]["status"] == f"HTTP_{status}"


@pytest.mark.parametrize("offset", [-121, 1])
def test_stale_or_future_dates_do_not_trigger_fetch(offset):
    fred, bls = inputs()
    fred = fred.model_copy(
        update={
            "started_at": NOW + timedelta(seconds=offset),
            "available_at": NOW + timedelta(seconds=offset),
        }
    )

    def no_fetch(day):
        pytest.fail("must not fetch with stale/unavailable date evidence")

    result = html.qualify(fred, bls, fetch=no_fetch)
    assert "FRED_DATES_STALE_OR_UNAVAILABLE" in result["reasons"]


def test_dst_ambiguous_local_time_rejected():
    day = date(2026, 11, 1)
    with pytest.raises(ValueError, match="ambiguous"):
        html.parse_times(page(day, "1:30 am"), day, RELEASES)
