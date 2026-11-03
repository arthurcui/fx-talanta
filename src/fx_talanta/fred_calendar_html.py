"""Bounded public-calendar qualification, separate from trading source health."""

import argparse
import json
import re
import ssl
import urllib.error
import urllib.request
from datetime import UTC, datetime
from hashlib import sha256
from html.parser import HTMLParser
from pathlib import Path
from zoneinfo import ZoneInfo

from fx_talanta.bls_calendar import import_calendar
from fx_talanta.fred_calendar import LIMIT, RELEASES, NoRedirect, Snapshot


class CalendarHTML(HTMLParser):
    def __init__(self):
        super().__init__()
        self.inputs, self.rows, self.text = {}, [], []
        self.scope = 0
        self.table = 0
        self.tables = 0
        self.row = None
        self.cell = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "input" and attrs.get("id") in {"rc-vs", "rc-ve"}:
            if attrs["id"] in self.inputs:
                raise ValueError("duplicate date marker")
            self.inputs[attrs["id"]] = attrs.get("value")
        if tag == "div":
            if self.scope:
                self.scope += 1
            elif attrs.get("id") == "release-dates-pager":
                self.scope = 1
        if self.table and tag == "table":
            raise ValueError("nested calendar table")
        if (
            self.scope
            and tag == "table"
            and "table-standard-theme" in attrs.get("class", "").split()
        ):
            self.table += 1
            self.tables += 1
        if self.table:
            if tag == "tr":
                if self.row is not None:
                    raise ValueError("nested row")
                self.row = {"cells": [], "links": []}
            if tag == "td" and self.row is not None:
                if self.cell is not None:
                    raise ValueError("nested cell")
                self.cell = []
            if tag == "a" and self.row is not None:
                self.row["links"].append(attrs.get("href", ""))

    def handle_endtag(self, tag):
        if tag == "td" and self.cell is not None:
            self.row["cells"].append(" ".join("".join(self.cell).split()))
            self.cell = None
        if tag == "tr" and self.row is not None:
            self.rows.append(self.row)
            self.row = None
        if tag == "table" and self.table:
            self.table -= 1
        if tag == "div" and self.scope:
            self.scope -= 1

    def handle_data(self, data):
        self.text.append(data)
        if self.cell is not None:
            self.cell.append(data)


def parse_times(raw, day, expected_ids):
    if len(raw) > LIMIT or not expected_ids or not set(expected_ids) <= RELEASES.keys():
        raise ValueError("invalid page scope")
    parser = CalendarHTML()
    parser.feed(raw.decode("utf-8-sig"))
    parser.close()
    if (
        parser.inputs != {"rc-vs": str(day), "rc-ve": str(day)}
        or parser.tables != 1
        or parser.table
        or parser.row is not None
        or parser.cell is not None
    ):
        raise ValueError("calendar structure or date changed")
    if "All times are US Central Time." not in " ".join(" ".join(parser.text).split()):
        raise ValueError("timezone label absent")
    expected_header = f"{day.strftime('%A %B')} {day.day:02d}, {day.year}"
    headers = [r["cells"] for r in parser.rows if len(r["cells"]) == 1]
    if headers != [[expected_header]]:
        raise ValueError("calendar day header mismatch")
    results = {}
    for row in parser.rows:
        ids = [
            int(m.group(1))
            for link in row["links"]
            if (m := re.fullmatch(r"/release\?rid=(\d+)", link))
        ]
        if not set(ids).intersection(expected_ids):
            continue
        if len(ids) != 1 or len(row["cells"]) != 2 or ids[0] in results:
            raise ValueError("ambiguous release row")
        rid = ids[0]
        clock, title = row["cells"]
        if title != RELEASES[rid] or not re.fullmatch(r"\d{1,2}:\d{2} [ap]m", clock):
            raise ValueError("release name/time missing or changed")
        civil = datetime.strptime(f"{day} {clock}", "%Y-%m-%d %I:%M %p")
        zone = ZoneInfo("America/Chicago")
        candidates = set()
        for fold in (0, 1):
            stamp = civil.replace(tzinfo=zone, fold=fold).astimezone(UTC)
            if stamp.astimezone(zone).replace(tzinfo=None) == civil:
                candidates.add(stamp)
        if len(candidates) != 1:
            raise ValueError("ambiguous/nonexistent calendar time")
        results[rid] = candidates.pop()
    if set(results) != set(expected_ids):
        raise ValueError("missing release rows")
    return results


def fetch_page(day):
    opener = urllib.request.build_opener(
        urllib.request.HTTPSHandler(context=ssl.create_default_context()), NoRedirect()
    )
    request = urllib.request.Request(
        f"https://fred.stlouisfed.org/releases/calendar?vs={day}&ve={day}",
        headers={"User-Agent": "FX-Talanta-Qualification/0.1"},
    )
    with opener.open(request, timeout=15) as response:
        if response.status != 200:
            raise ValueError("unexpected status")
        return response.read(LIMIT + 1)


def qualify(fred, bls, *, fetch=fetch_page, previous=None, max_age_seconds=120):
    if not 1 <= max_age_seconds <= 86400:
        raise ValueError("invalid freshness policy")
    started = datetime.now(UTC)
    reasons, pages, matches = set(), [], []
    if bls.imported_at > started:
        reasons.add("BLS_UNAVAILABLE")
    bls_dates = {
        (e.release_id, e.scheduled_at.astimezone(ZoneInfo("America/New_York")).date())
        for e in bls.events
        if fred.window_start
        <= e.scheduled_at.astimezone(ZoneInfo("America/New_York")).date()
        <= fred.window_end
    }
    if bls_dates != {(r.release_id, r.date) for r in fred.dates}:
        reasons.add("BLS_DATE_INVENTORY_MISMATCH")
    if fred.status != "OK" or {r.release_id for r in fred.dates} != set(RELEASES):
        reasons.add("INVALID_DATE_INVENTORY")
    if (
        fred.available_at > started
        or not 0 <= (started - fred.started_at).total_seconds() <= max_age_seconds
    ):
        reasons.add("FRED_DATES_STALE_OR_UNAVAILABLE")
    grouped = {}
    for row in fred.dates:
        grouped.setdefault(row.date, []).append(row.release_id)
    if not 1 <= len(grouped) <= 10:
        reasons.add("PAGE_BUDGET_EXCEEDED")
    if not reasons:
        for day, ids in sorted(grouped.items()):
            fetched = datetime.now(UTC)
            try:
                raw = fetch(day)
                times = parse_times(raw, day, ids)
                pages.append(
                    dict(
                        date=str(day),
                        fetched_at=fetched.isoformat(),
                        source_hash=sha256(raw).hexdigest(),
                        status="PARSED",
                    )
                )
                for rid, stamp in times.items():
                    candidates = [
                        e
                        for e in bls.events
                        if e.release_id == rid
                        and e.scheduled_at.astimezone(ZoneInfo("America/New_York")).date() == day
                    ]
                    agrees = (
                        len(candidates) == 1
                        and candidates[0].status == "CONFIRMED"
                        and candidates[0].scheduled_at == stamp
                    )
                    if not agrees:
                        reasons.add("BLS_TIME_CONFLICT_OR_MISSING")
                    matches.append(
                        dict(
                            release_id=rid,
                            date=str(day),
                            scheduled_at=stamp.isoformat(),
                            matches_bls=agrees,
                        )
                    )
            except (OSError, ValueError) as exc:
                error = (
                    f"HTTP_{exc.code}"
                    if isinstance(exc, urllib.error.HTTPError)
                    else ("TRANSPORT_OR_SCHEMA_FAILURE")
                )
                pages.append(dict(date=str(day), fetched_at=fetched.isoformat(), status=error))
                reasons.add("PAGE_FETCH_OR_PARSE_FAILED")
                break
    finished = datetime.now(UTC)
    if (finished - min(started, fred.started_at)).total_seconds() > max_age_seconds:
        reasons.add("STALE_DURING_COLLECTION")
    schedule = {(r["release_id"], r["date"], r["scheduled_at"]) for r in matches}
    if previous and schedule != {
        (r["release_id"], r["date"], r["scheduled_at"]) for r in previous["matches"]
    }:
        reasons.add("SCHEDULE_CHANGED_REVIEW_REQUIRED")
    return dict(
        started_at=started.isoformat(),
        available_at=finished.isoformat(),
        fred_hash=fred.digest(),
        bls_hash=bls.digest(),
        pages=pages,
        matches=matches,
        comparison_passed=not reasons,
        reasons=sorted(reasons),
        previous_hash=sha256(json.dumps(previous, sort_keys=True).encode()).hexdigest()
        if previous
        else None,
        bls_provenance=bls.provenance,
        block_entries=True,
        qualified_for_trading=False,
        execution_enabled=False,
        limitation="Bounded transport/time comparison only; no sustained refresh evidence",
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fred", type=Path, required=True)
    parser.add_argument("--bls", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--previous", type=Path)
    args = parser.parse_args(argv)
    try:

        def read(path):
            with path.open("rb") as stream:
                raw = stream.read(2 * LIMIT + 1)
            if len(raw) > 2 * LIMIT:
                raise ValueError("input bound")
            return raw

        fred = Snapshot.model_validate_json(read(args.fred))
        bls = import_calendar(read(args.bls))
        previous = json.loads(read(args.previous)) if args.previous else None
        with args.output.open("x", encoding="utf-8") as output:
            report = qualify(fred, bls, previous=previous)
            output.write(json.dumps(report, indent=2) + "\n")
        print(
            json.dumps(
                {
                    "comparison_passed": report["comparison_passed"],
                    "matches": len(report["matches"]),
                    "reasons": report["reasons"],
                    "execution_enabled": False,
                }
            )
        )
        return 0 if report["comparison_passed"] else 2
    except (OSError, ValueError, TypeError, KeyError):
        print("Calendar qualification failed; check inputs. Trading remains disabled.")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
