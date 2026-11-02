import json
import urllib.error
from datetime import UTC, date, datetime, timedelta

import pytest

from fx_talanta import bls_calendar as bls
from fx_talanta.fred_calendar import RELEASES, ReleaseDate, Snapshot

NOW = datetime(2026, 11, 2, 22, tzinfo=UTC)


@pytest.fixture(autouse=True)
def clock(monkeypatch):
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW.astimezone(tz)

    monkeypatch.setattr(bls, "datetime", Clock)


def calendar(*, start="20261106T083000", extra="", sequence=1, summary="Employment Situation"):
    return (
        "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nMETHOD:PUBLISH\r\nBEGIN:VEVENT\r\n"
        f"UID:test\r\nSEQUENCE:{sequence}\r\nDTSTART;TZID=US-Eastern:{start}\r\n"
        f"SUMMARY:{summary}\r\n{extra}END:VEVENT\r\nEND:VCALENDAR\r\n"
    ).encode()


def all_releases():
    events = []
    for rid, name in RELEASES.items():
        event = calendar(summary=name).decode().split("BEGIN:VEVENT")[1].split("END:VEVENT")[0]
        events.append("BEGIN:VEVENT" + event.replace("UID:test", f"UID:{rid}") + "END:VEVENT\n")
    return ("BEGIN:VCALENDAR\nVERSION:2.0\n" + "".join(events) + "END:VCALENDAR").encode()


def fred():
    return Snapshot(
        started_at=NOW,
        available_at=NOW,
        window_start=date(2026, 11, 2),
        window_end=date(2026, 12, 2),
        status="OK",
        dates=tuple(ReleaseDate(release_id=rid, date=date(2026, 11, 6)) for rid in RELEASES),
    )


def test_folded_summary_and_timezone_conversion():
    event = bls.parse_ics(calendar(summary="Employment \r\n Situation"))[0]
    # Fold removes the single folding character, so retain a content space.
    assert event.scheduled_at == datetime(2026, 11, 6, 13, 30, tzinfo=UTC)


@pytest.mark.parametrize("start,hour", [("20260706T083000", 12), ("20261106T083000", 13)])
def test_dst_dates(start, hour):
    assert bls.parse_ics(calendar(start=start))[0].scheduled_at.hour == hour


@pytest.mark.parametrize("start", ["20260308T023000", "20261101T013000", "20261106"])
def test_invalid_local_times(start):
    with pytest.raises(ValueError):
        bls.parse_ics(calendar(start=start))


@pytest.mark.parametrize(
    "extra",
    ["RRULE:FREQ=MONTHLY\r\n", "RDATE:20261201T100000Z\r\n", "STATUS:INVALID\r\n", "UID:other\r\n"],
)
def test_unsupported_semantics(extra):
    with pytest.raises(ValueError):
        bls.parse_ics(calendar(extra=extra))


def test_floating_html_truncated_oversized_and_duplicate_uid():
    raw = calendar()
    invalid = [
        b"<html>Access denied</html>",
        raw[:-30],
        b"x" * (bls.LIMIT + 1),
        raw.replace(b"DTSTART;TZID=US-Eastern", b"DTSTART"),
        raw.replace(b"END:VCALENDAR", raw.split(b"BEGIN:VEVENT")[1].join([b"BEGIN:VEVENT", b""])),
    ]
    for item in invalid:
        with pytest.raises(ValueError):
            bls.parse_ics(item)


def test_revision_chain_preserves_changes_and_rejects_silent_conflicts():
    first = bls.import_calendar(calendar())
    with pytest.raises(ValueError):
        bls.import_calendar(calendar(start="20261109T083000"), previous=first)
    second = bls.import_calendar(calendar(start="20261109T083000", sequence=2), previous=first)
    assert second.previous_hash == first.digest()
    with pytest.raises(ValueError):
        bls.import_calendar(calendar(), previous=second)


def test_manual_import_never_refreshes_health():
    snapshot = bls.import_calendar(all_releases())
    result = bls.reconcile(snapshot, fred(), NOW)
    assert len(result["matched_events"]) == 4
    assert result["reasons"] == ["BLS_MANUAL_REFRESH_UNVERIFIED"]
    assert result["block_entries"] and not result["execution_enabled"]


def test_fresh_verified_snapshot_still_never_claims_full_coverage():
    snapshot = bls.import_calendar(all_releases(), fetched_at=NOW)
    result = bls.reconcile(snapshot, fred(), NOW)
    assert not result["block_entries"]
    assert not result["calendar_coverage_complete"] and not result["qualified_for_trading"]
    stale = bls.reconcile(snapshot, fred(), NOW + timedelta(seconds=121))
    assert "BLS_STALE_OR_FUTURE" in stale["reasons"]
    assert "FRED_STALE_OR_UNAVAILABLE" in stale["reasons"]


def test_cancelled_missing_or_moved_dates_block():
    for raw in (
        all_releases().replace(b"END:VEVENT", b"STATUS:CANCELLED\nEND:VEVENT", 1),
        all_releases().replace(b"20261106T083000", b"20261109T083000", 1),
        calendar(),
    ):
        assert bls.reconcile(bls.import_calendar(raw, fetched_at=NOW), fred(), NOW)["block_entries"]


@pytest.mark.parametrize("status", [403, 429, 500])
def test_refresh_failures_do_not_reuse_previous(monkeypatch, status):
    class Denied:
        def open(self, *args, **kwargs):
            raise urllib.error.HTTPError(bls.URL, status, "denied", {}, None)

    monkeypatch.setattr(bls.urllib.request, "build_opener", lambda *args: Denied())
    previous = bls.import_calendar(all_releases())
    snapshot, error = bls.refresh(previous=previous)
    assert snapshot is None and error == f"HTTP_{status}"
    assert previous.provenance == "MANUAL_FILE"


def test_cli_output_is_immutable_and_can_be_previous(tmp_path):
    source, fredfile, out, second = [
        tmp_path / name for name in ("bls.ics", "fred.json", "a.json", "b.json")
    ]
    source.write_bytes(all_releases())
    fredfile.write_text(fred().model_dump_json())
    args = ["--ics", str(source), "--fred", str(fredfile)]
    assert bls.main(args + ["--output", str(out)]) == 0
    before = out.read_bytes()
    assert bls.main(args + ["--output", str(out)]) == 2
    assert out.read_bytes() == before
    assert bls.main(args + ["--output", str(second), "--previous", str(out)]) == 0
    assert json.loads(second.read_text())["snapshot"]["previous_hash"]


def test_refresh_success_and_html_failure(monkeypatch):
    class Response:
        status = 200
        body = all_releases()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def read(self, limit):
            return self.body[:limit]

    class Client:
        def open(self, request, timeout):
            assert request.full_url == bls.URL
            assert timeout == 15
            return Response()

    monkeypatch.setattr(bls.urllib.request, "build_opener", lambda *args: Client())
    result, error = bls.refresh()
    assert error is None and result.provenance == "HTTPS" and result.fetched_at == NOW
    Response.body = b"<html>denied</html>"
    assert bls.refresh() == (None, "TRANSPORT_OR_SCHEMA_FAILURE")


def test_utc_blackout_boundary_and_future_snapshot():
    raw = all_releases().replace(
        b"DTSTART;TZID=US-Eastern:20261106T083000", b"DTSTART:20261102T223000Z"
    )
    snapshot = bls.import_calendar(raw, fetched_at=NOW)
    dates = tuple(ReleaseDate(release_id=rid, date=NOW.date()) for rid in RELEASES)
    result = bls.reconcile(snapshot, fred().model_copy(update={"dates": dates}), NOW)
    assert "EVENT_BLACKOUT" in result["reasons"]
    assert (
        "BLS_UNAVAILABLE" in bls.reconcile(snapshot, fred(), NOW - timedelta(seconds=1))["reasons"]
    )


def test_unknown_embedded_timezone_rules_fail():
    raw = calendar().replace(
        b"BEGIN:VEVENT", b"BEGIN:VTIMEZONE\nTZID:US-Eastern\nEND:VTIMEZONE\nBEGIN:VEVENT"
    )
    with pytest.raises(ValueError, match="timezone"):
        bls.parse_ics(raw)
