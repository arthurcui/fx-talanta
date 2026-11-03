import json
import urllib.error
from datetime import UTC, date, datetime, timedelta

import pytest

from fx_talanta import fred_calendar as fred

KEY = "a" * 32
START, END = date(2026, 11, 2), date(2026, 12, 2)


@pytest.fixture(autouse=True)
def fixed_clock(monkeypatch):
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 11, 2, 21, tzinfo=UTC).astimezone(tz)

    monkeypatch.setattr(fred, "datetime", Clock)


def page(key, params):
    assert key == KEY
    assert params["include_release_dates_with_no_data"] == "true"
    return json.dumps(
        {
            "count": 1,
            "offset": 0,
            "release_dates": [{"release_id": params["release_id"], "date": "2026-11-06"}],
        }
    ).encode()


def evidence(**changes):
    values = dict(
        release_id=50,
        date="2026-11-06",
        local_time="08:30",
        timezone="America/New_York",
        available_at="2026-11-02T00:00:00Z",
        valid_until="2026-12-03T00:00:00Z",
        source_url="https://www.bls.gov/schedule/2026/home.htm",
        corroborating_url="https://fred.stlouisfed.org/releases/calendar",
        source_hash="a" * 64,
        corroborating_hash="b" * 64,
    )
    return fred.TimeEvidence(**(values | changes))


def test_success_and_immutable_revision_chain():
    first = fred.collect(KEY, START, END, fetch=page)
    second = fred.collect(KEY, START, END, previous=first, fetch=page)
    assert first.status == "OK" and len(first.dates) == 4
    assert second.previous_hash == first.digest()
    assert not second.execution_enabled and not second.qualified_for_trading
    assert KEY not in second.model_dump_json()


@pytest.mark.parametrize(
    "kind", ["duplicate", "wrong_release", "outside", "empty", "bad_json", "changed_count"]
)
def test_malformed_or_incomplete_pages_discard_partial_results(kind):
    def bad(key, params):
        if kind == "bad_json":
            return b"[]"
        row = {"release_id": params["release_id"], "date": "2026-11-06"}
        rows, count = [row], 1
        if kind == "duplicate":
            rows, count = [row, row], 2
        if kind == "wrong_release":
            row["release_id"] = 999
        if kind == "outside":
            row["date"] = "2027-01-01"
        if kind == "empty":
            rows = []
        if kind == "changed_count":
            count = 2 if params["offset"] == 0 else 3
        return json.dumps(
            {"count": count, "offset": params["offset"], "release_dates": rows}
        ).encode()

    result = fred.collect(KEY, START, END, fetch=bad)
    assert result.status == "FAILED" and not result.dates


def test_pagination_collects_all_pages():
    calls = []

    def paged(key, params):
        calls.append(params["offset"])
        return json.dumps(
            {
                "count": 2,
                "offset": params["offset"],
                "release_dates": [
                    {
                        "release_id": params["release_id"],
                        "date": "2026-11-06" if params["offset"] == 0 else "2026-11-10",
                    }
                ],
            }
        ).encode()

    result = fred.collect(KEY, START, END, fetch=paged)
    assert result.status == "OK" and len(result.dates) == 8
    assert calls == [0, 1] * 4


@pytest.mark.parametrize("status", [403, 429, 500])
def test_http_failure_does_not_leak_key(monkeypatch, status):
    class Broken:
        def open(self, *args, **kwargs):
            raise urllib.error.HTTPError("https://example/?api_key=" + KEY, status, KEY, {}, None)

    monkeypatch.setattr(fred.urllib.request, "build_opener", lambda *args: Broken())
    result = fred.collect(KEY, START, END)
    assert result.error == f"HTTP_{status}"
    assert KEY not in result.model_dump_json()
    assert fred.restrictions(result, [], result.available_at)["block_entries"]


@pytest.mark.parametrize("day,hour", [("2026-07-06", 12), ("2026-11-06", 13)])
def test_dst_conversion(day, hour):
    assert evidence(date=day).scheduled_at().hour == hour


@pytest.mark.parametrize("day,time", [("2026-03-08", "02:30"), ("2026-11-01", "01:30")])
def test_dst_ambiguous_and_nonexistent_times_rejected(day, time):
    with pytest.raises(ValueError):
        evidence(date=day, local_time=time)


def test_unknown_conflicting_future_and_stale_evidence_block():
    snapshot = fred.collect(KEY, START, END, fetch=page)
    now = snapshot.available_at
    assert "UNKNOWN_OR_CONFLICTING_TIME" in fred.restrictions(snapshot, [], now)["reasons"]
    verified = [evidence(release_id=rid) for rid in fred.RELEASES]
    assert not fred.restrictions(snapshot, verified, now)["block_entries"]
    conflict = verified + [evidence(local_time="10:00")]
    assert fred.restrictions(snapshot, conflict, now)["block_entries"]
    future = [
        evidence(release_id=rid, available_at=now + timedelta(seconds=1)) for rid in fred.RELEASES
    ]
    assert fred.restrictions(snapshot, future, now)["block_entries"]
    assert fred.restrictions(snapshot, verified, now + timedelta(seconds=121))["block_entries"]


def test_reschedule_does_not_reuse_old_time_evidence():
    def moved(key, params):
        return page(key, params).replace(b"2026-11-06", b"2026-11-09")

    snapshot = fred.collect(KEY, START, END, fetch=moved)
    verified = [evidence(release_id=rid) for rid in fred.RELEASES]
    assert (
        "UNKNOWN_OR_CONFLICTING_TIME"
        in fred.restrictions(snapshot, verified, snapshot.available_at)["reasons"]
    )


def test_blackout_boundary_and_missing_inventory():
    cutoff = datetime(2026, 11, 6, 13, 0, tzinfo=UTC)
    snapshot = fred.collect(KEY, START, END, fetch=page).model_copy(
        update={"started_at": cutoff, "available_at": cutoff}
    )
    verified = [evidence(release_id=rid) for rid in fred.RELEASES]
    assert "EVENT_BLACKOUT" in fred.restrictions(snapshot, verified, cutoff)["reasons"]
    snapshot = snapshot.model_copy(update={"dates": ()})
    assert "MISSING_RELEASE_INVENTORY" in fred.restrictions(snapshot, [], cutoff)["reasons"]


def test_cli_never_overwrites_evidence(tmp_path):
    output = tmp_path / "snapshot.json"
    output.write_text("original")
    assert (
        fred.main(
            [
                "--env-file",
                str(tmp_path / "missing.env"),
                "--start",
                str(START),
                "--end",
                str(END),
                "--output",
                str(output),
            ]
        )
        == 2
    )
    assert output.read_text() == "original"
