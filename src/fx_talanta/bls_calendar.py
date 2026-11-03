"""Strict BLS ICS subset importer and one-shot refresh; qualification only."""

import argparse
import json
import re
import ssl
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import Field, model_validator

from fx_talanta.domain.models import FrozenModel, Hash, Timestamp, utc
from fx_talanta.fred_calendar import RELEASES, NoRedirect, Snapshot

URL = "https://www.bls.gov/schedule/news_release/bls.ics"
LIMIT = 2 * 1024 * 1024
NAMES = {name: rid for rid, name in RELEASES.items()}


class BlsEvent(FrozenModel):
    uid: str = Field(min_length=1, max_length=256)
    sequence: int = Field(ge=0)
    release_id: Literal[50, 10, 46, 192]
    scheduled_at: Timestamp
    status: Literal["CONFIRMED", "CANCELLED", "TENTATIVE"]


class BlsSnapshot(FrozenModel):
    source_url: Literal[URL] = URL
    source_hash: Hash
    imported_at: Timestamp
    fetched_at: Timestamp | None = None
    provenance: Literal["MANUAL_FILE", "HTTPS"]
    events: tuple[BlsEvent, ...]
    previous_hash: Hash | None = None
    execution_enabled: Literal[False] = False

    @model_validator(mode="after")
    def validate_snapshot(self):
        if (self.provenance == "HTTPS") != (self.fetched_at is not None):
            raise ValueError("only HTTPS collection has a verified fetch timestamp")
        if self.fetched_at and self.fetched_at > self.imported_at:
            raise ValueError("fetch cannot follow import")
        if len({e.uid for e in self.events}) != len(self.events):
            raise ValueError("duplicate UID")
        return self

    def digest(self):
        return sha256(self.model_dump_json().encode()).hexdigest()


def _timestamp(key, value):
    if not re.fullmatch(r"\d{8}T\d{6}Z?", value):
        raise ValueError("missing precise event time")
    if key == "DTSTART" and value.endswith("Z"):
        return datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
    if key not in {"DTSTART;TZID=US-Eastern", "DTSTART;TZID=America/New_York"}:
        raise ValueError("unsupported or floating event timezone")
    naive = datetime.strptime(value, "%Y%m%dT%H%M%S")
    zone = ZoneInfo("America/New_York")
    candidates = set()
    for fold in (0, 1):
        candidate = naive.replace(tzinfo=zone, fold=fold).astimezone(UTC)
        if candidate.astimezone(zone).replace(tzinfo=None) == naive:
            candidates.add(candidate)
    if len(candidates) != 1:
        raise ValueError("ambiguous or nonexistent event time")
    return candidates.pop()


def parse_ics(raw):
    """Accept the published nonrecurring BLS shape; reject unsupported target semantics."""
    if len(raw) > LIMIT or b"\x00" in raw:
        raise ValueError("invalid calendar size or encoding")
    lines = []
    for line in raw.decode("utf-8-sig").splitlines():
        if line.startswith((" ", "\t")):
            if not lines:
                raise ValueError("orphan folded line")
            lines[-1] += line[1:]
        elif line:
            lines.append(line)
    if not lines or lines[0] != "BEGIN:VCALENDAR" or lines[-1] != "END:VCALENDAR":
        raise ValueError("not a complete calendar")
    # The downloaded BLS alias must retain its US DST rules; never silently
    # substitute IANA rules for a changed/custom embedded timezone definition.
    timezone_blocks = re.findall(
        r"BEGIN:VTIMEZONE\n(.*?)\nEND:VTIMEZONE", "\n".join(lines), re.DOTALL
    )
    expected_zone = (
        "TZID:US-Eastern\nBEGIN:DAYLIGHT\nTZOFFSETFROM:-0500\nTZOFFSETTO:-0400\n"
        "DTSTART:20070311T020000\nRRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=2SU\n"
        "TZNAME:EDT\nEND:DAYLIGHT\nBEGIN:STANDARD\nTZOFFSETFROM:-0400\n"
        "TZOFFSETTO:-0500\nDTSTART:20071104T020000\n"
        "RRULE:FREQ=YEARLY;BYMONTH=11;BYDAY=1SU\nTZNAME:EST\nEND:STANDARD"
    )
    if timezone_blocks and timezone_blocks != [expected_zone]:
        raise ValueError("unrecognized embedded timezone rules")
    stack, fields, events = [], None, []
    calendar_fields = {}
    for line in lines:
        if ":" not in line:
            raise ValueError("malformed content line")
        key, value = line.split(":", 1)
        if key == "BEGIN":
            allowed_parent = {
                "VCALENDAR": [],
                "VEVENT": ["VCALENDAR"],
                "VTIMEZONE": ["VCALENDAR"],
                "DAYLIGHT": ["VCALENDAR", "VTIMEZONE"],
                "STANDARD": ["VCALENDAR", "VTIMEZONE"],
            }
            if value not in allowed_parent or stack != allowed_parent[value]:
                raise ValueError("unsupported component structure")
            if value == "VEVENT":
                if stack != ["VCALENDAR"]:
                    raise ValueError("nested event")
                fields = {}
            elif fields is not None:
                raise ValueError("unsupported event component")
            stack.append(value)
        elif key == "END":
            if not stack or stack.pop() != value:
                raise ValueError("unbalanced calendar")
            if value == "VEVENT":
                summary = fields.get("SUMMARY", (None, None))[1]
                if summary in NAMES:
                    if any(k in fields for k in ("RRULE", "RDATE", "EXDATE", "RECURRENCE-ID")):
                        raise ValueError("recurring release requires explicit expansion")
                    if not {"UID", "DTSTART", "SUMMARY"} <= fields.keys():
                        raise ValueError("incomplete release")
                    seq = fields.get("SEQUENCE", (None, "0"))[1]
                    if not seq.isdecimal():
                        raise ValueError("invalid sequence")
                    events.append(
                        BlsEvent(
                            uid=fields["UID"][1],
                            sequence=int(seq),
                            release_id=NAMES[summary],
                            scheduled_at=_timestamp(*fields["DTSTART"]),
                            status=fields.get("STATUS", (None, "CONFIRMED"))[1],
                        )
                    )
                fields = None
        elif fields is not None:
            base = key.split(";", 1)[0]
            if base in fields:
                raise ValueError("duplicate event property")
            fields[base] = (key, value)
        elif stack == ["VCALENDAR"]:
            if key in calendar_fields:
                raise ValueError("duplicate calendar property")
            calendar_fields[key] = value
    if stack or calendar_fields.get("VERSION") != "2.0" or not events:
        raise ValueError("incomplete or unsupported calendar")
    if calendar_fields.get("METHOD") not in {None, "PUBLISH"}:
        raise ValueError("unsupported calendar method")
    if len({e.uid for e in events}) != len(events):
        raise ValueError("duplicate release UID")
    return tuple(events)


def import_calendar(raw, *, previous=None, fetched_at=None):
    events = parse_ics(raw)
    if previous:
        old = {e.uid: e for e in previous.events}
        for event in events:
            before = old.get(event.uid)
            if before and (
                event.sequence < before.sequence
                or (event.sequence == before.sequence and event != before)
            ):
                raise ValueError("regressed or conflicting event revision")
    return BlsSnapshot(
        source_hash=sha256(raw).hexdigest(),
        imported_at=datetime.now(UTC),
        fetched_at=fetched_at,
        provenance="HTTPS" if fetched_at else "MANUAL_FILE",
        events=events,
        previous_hash=previous.digest() if previous else None,
    )


def refresh(*, previous=None):
    """No cookies, browser impersonation, redirect bypasses, retries or stale fallback."""
    started = datetime.now(UTC)
    opener = urllib.request.build_opener(
        urllib.request.HTTPSHandler(context=ssl.create_default_context()), NoRedirect()
    )
    request = urllib.request.Request(URL, headers={"User-Agent": "FX-Talanta-Qualification/0.1"})
    try:
        with opener.open(request, timeout=15) as response:
            raw = response.read(LIMIT + 1)
            if response.status != 200:
                return None, f"HTTP_{response.status}"
        return import_calendar(raw, previous=previous, fetched_at=started), None
    except urllib.error.HTTPError as exc:
        return None, f"HTTP_{exc.code}"
    except (OSError, ValueError):
        return None, "TRANSPORT_OR_SCHEMA_FAILURE"


def reconcile(bls, fred, cutoff, *, max_age_seconds=120):
    cutoff = utc(cutoff)
    if not 1 <= max_age_seconds <= 86400:
        raise ValueError("invalid freshness policy")
    reasons, matches = set(), []
    if bls.imported_at > cutoff:
        reasons.add("BLS_UNAVAILABLE")
    if bls.fetched_at is None:
        reasons.add("BLS_MANUAL_REFRESH_UNVERIFIED")
    elif not 0 <= (cutoff - bls.fetched_at).total_seconds() <= max_age_seconds:
        reasons.add("BLS_STALE_OR_FUTURE")
    if fred.status != "OK":
        reasons.add("FRED_FAILED")
    if (
        fred.available_at > cutoff
        or not 0 <= (cutoff - fred.started_at).total_seconds() <= max_age_seconds
    ):
        reasons.add("FRED_STALE_OR_UNAVAILABLE")
    for edge in (cutoff - timedelta(minutes=30), cutoff + timedelta(minutes=30)):
        if (
            not fred.window_start
            <= edge.astimezone(ZoneInfo("America/New_York")).date()
            <= (fred.window_end)
        ):
            reasons.add("OUTSIDE_WINDOW")
    indexed = {}
    for event in bls.events:
        day = event.scheduled_at.astimezone(ZoneInfo("America/New_York")).date()
        if fred.window_start <= day <= fred.window_end:
            indexed.setdefault((event.release_id, day), []).append(event)
    fred_keys = {(r.release_id, r.date) for r in fred.dates}
    if fred_keys != set(indexed):
        reasons.add("SCHEDULE_MISMATCH")
    if {rid for rid, _ in fred_keys} != set(RELEASES):
        reasons.add("MISSING_RELEASE_INVENTORY")
    for key in sorted(fred_keys):
        candidates = indexed.get(key, [])
        if len(candidates) != 1 or candidates[0].status != "CONFIRMED":
            reasons.add("MISSING_CONFLICTING_OR_CANCELLED_RELEASE")
            continue
        event = candidates[0]
        matches.append(event.model_dump(mode="json"))
        if abs((event.scheduled_at - cutoff).total_seconds()) <= 1800:
            reasons.add("EVENT_BLACKOUT")
    return dict(
        bls_hash=bls.digest(),
        fred_hash=fred.digest(),
        cutoff=cutoff.isoformat(),
        matched_events=matches,
        reasons=sorted(reasons),
        block_entries=bool(reasons),
        calendar_coverage_complete=False,
        qualified_for_trading=False,
        execution_enabled=False,
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--ics", type=Path)
    source.add_argument("--refresh", action="store_true")
    parser.add_argument("--fred", type=Path, required=True)
    parser.add_argument("--previous", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:

        def read(path):
            with path.open("rb") as stream:
                raw = stream.read(LIMIT + 1)
            if len(raw) > LIMIT:
                raise ValueError("input size limit")
            return raw

        fred = Snapshot.model_validate_json(read(args.fred))
        previous = (
            BlsSnapshot.model_validate(json.loads(read(args.previous))["snapshot"])
            if (args.previous)
            else None
        )
        with args.output.open("x", encoding="utf-8") as output:
            if args.refresh:
                snapshot, error = refresh(previous=previous)
            else:
                snapshot, error = import_calendar(read(args.ics), previous=previous), None
            result = dict(
                checked_at=datetime.now(UTC).isoformat(),
                source_url=URL,
                snapshot=snapshot.model_dump(mode="json") if snapshot else None,
                error=error,
                assessment=reconcile(snapshot, fred, datetime.now(UTC))
                if snapshot
                else dict(block_entries=True, execution_enabled=False),
            )
            output.write(json.dumps(result, indent=2) + "\n")
        print(
            json.dumps(
                dict(
                    status="IMPORTED" if snapshot else "FAILED",
                    error=error,
                    block_entries=result["assessment"]["block_entries"],
                )
            )
        )
        return 0 if snapshot else 2
    except (OSError, ValueError, KeyError, TypeError):
        print("BLS import failed: invalid input or output; trading remains disabled.")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
