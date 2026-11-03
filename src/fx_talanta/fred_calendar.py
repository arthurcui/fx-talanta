"""Read-only FRED schedule qualification; never grants trading authority."""

import argparse
import json
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, date, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

from dotenv import dotenv_values
from pydantic import Field, TypeAdapter, model_validator

from fx_talanta.domain.models import FrozenModel, Hash, Timestamp, utc

RELEASES = {
    50: "Employment Situation",
    10: "Consumer Price Index",
    46: "Producer Price Index",
    192: "Job Openings and Labor Turnover Survey",
}
LIMIT = 1024 * 1024


class FredError(Exception):
    """Only sanitized error codes cross the transport boundary."""


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class ReleaseDate(FrozenModel):
    release_id: Literal[50, 10, 46, 192]
    date: date


class TimeEvidence(FrozenModel):
    release_id: Literal[50, 10, 46, 192]
    date: date
    local_time: str = Field(pattern=r"^\d{2}:\d{2}$")
    timezone: Literal["America/New_York", "America/Chicago"]
    available_at: Timestamp
    valid_until: Timestamp
    source_url: str
    corroborating_url: str
    source_hash: Hash
    corroborating_hash: Hash

    @model_validator(mode="after")
    def validate_evidence(self):
        hosts = []
        for url in (self.source_url, self.corroborating_url):
            parsed = urllib.parse.urlsplit(url)
            if (
                parsed.scheme != "https"
                or parsed.hostname not in {"www.bls.gov", "fred.stlouisfed.org"}
                or parsed.username
                or parsed.password
                or parsed.port
            ):
                raise ValueError("use official schedule evidence URLs")
            hosts.append(parsed.hostname)
        if len(set(hosts)) != 2 or self.valid_until <= self.available_at:
            raise ValueError("independent sources and a valid evidence interval required")
        self.scheduled_at()
        return self

    def scheduled_at(self):
        naive = datetime.fromisoformat(f"{self.date}T{self.local_time}:00")
        zone = ZoneInfo(self.timezone)
        candidates = set()
        for fold in (0, 1):
            local = naive.replace(tzinfo=zone, fold=fold)
            candidate = local.astimezone(UTC)
            if candidate.astimezone(zone).replace(tzinfo=None) == naive:
                candidates.add(candidate)
        if len(candidates) != 1:
            raise ValueError("ambiguous or nonexistent local release time")
        return candidates.pop()


class Snapshot(FrozenModel):
    schema_version: Literal[1] = 1
    source: Literal["FRED"] = "FRED"
    started_at: Timestamp
    available_at: Timestamp
    window_start: date
    window_end: date
    status: Literal["OK", "FAILED"]
    error: str | None = None
    dates: tuple[ReleaseDate, ...] = ()
    response_hashes: tuple[Hash, ...] = ()
    previous_hash: Hash | None = None
    qualified_for_trading: Literal[False] = False
    execution_enabled: Literal[False] = False

    @model_validator(mode="after")
    def validate_snapshot(self):
        if (
            self.started_at > self.available_at
            or not 1 <= (self.window_end - self.window_start).days <= 62
        ):
            raise ValueError("invalid observation interval")
        identities = [(r.release_id, r.date) for r in self.dates]
        if len(set(identities)) != len(identities) or any(
            not self.window_start <= r.date <= self.window_end for r in self.dates
        ):
            raise ValueError("duplicate or out-of-window release")
        if self.status == "FAILED" and self.dates:
            raise ValueError("failed snapshot cannot expose partial dates")
        return self

    def digest(self):
        return sha256(self.model_dump_json().encode()).hexdigest()


def request_page(key, params):
    # Never log a request URL or propagate an exception containing the API key.
    query = urllib.parse.urlencode({**params, "api_key": key, "file_type": "json"})
    opener = urllib.request.build_opener(
        urllib.request.HTTPSHandler(context=ssl.create_default_context()), NoRedirect()
    )
    req = urllib.request.Request(
        "https://api.stlouisfed.org/fred/release/dates?" + query,
        headers={"User-Agent": "FX-Talanta-Qualification/0.1"},
    )
    try:
        with opener.open(req, timeout=15) as response:
            body = response.read(LIMIT + 1)
            if len(body) > LIMIT:
                raise FredError("BODY_LIMIT")
            return body
    except urllib.error.HTTPError as exc:
        raise FredError(f"HTTP_{exc.code}") from None
    except (OSError, ValueError):
        raise FredError("TRANSPORT_FAILURE") from None


def collect(key, start, end, *, previous=None, fetch=request_page):
    if not re.fullmatch(r"[a-z0-9]{32}", key):
        raise FredError("INVALID_KEY_FORMAT")
    if not 1 <= (end - start).days <= 62:
        raise ValueError("window must be 1 to 62 days")
    began = datetime.now(UTC)
    rows, hashes = [], []
    error = None
    try:
        for release_id in RELEASES:
            offset, total = 0, None
            seen = set()
            for _ in range(10):
                body = fetch(
                    key,
                    dict(
                        release_id=release_id,
                        realtime_start=str(start),
                        realtime_end=str(end),
                        limit=1000,
                        offset=offset,
                        sort_order="asc",
                        include_release_dates_with_no_data="true",
                    ),
                )
                if len(body) > LIMIT:
                    raise FredError("BODY_LIMIT")
                data = json.loads(body)
                count = data["count"]
                page = data["release_dates"]
                if (
                    type(count) is not int
                    or not 0 <= count <= 10000
                    or data["offset"] != offset
                    or not isinstance(page, list)
                    or len(page) > 1000
                    or (total is not None and total != count)
                ):
                    raise FredError("PAGINATION_INVALID")
                total = count
                hashes.append(sha256(body).hexdigest())
                for item in page:
                    row = ReleaseDate.model_validate(item)
                    if row.release_id != release_id or not start <= row.date <= end:
                        raise FredError("UNEXPECTED_RELEASE")
                    if row.date in seen:
                        raise FredError("DUPLICATE_RELEASE")
                    seen.add(row.date)
                    rows.append(row)
                offset += len(page)
                if offset == total:
                    break
                if not page or offset > total:
                    raise FredError("PAGINATION_INCOMPLETE")
            else:
                raise FredError("PAGE_LIMIT")
    except FredError as exc:
        error = str(exc)
    except (ValueError, KeyError, TypeError):
        error = "SCHEMA_INVALID"
    return Snapshot(
        started_at=began,
        available_at=datetime.now(UTC),
        window_start=start,
        window_end=end,
        status="FAILED" if error else "OK",
        error=error,
        dates=() if error else tuple(rows),
        response_hashes=tuple(hashes),
        previous_hash=previous.digest() if previous else None,
    )


def restrictions(snapshot, evidence, cutoff, *, max_age_seconds=120):
    """Additional veto only. Four BLS releases never establish full calendar health."""
    cutoff = utc(cutoff)
    if not 1 <= max_age_seconds <= 86400:
        raise ValueError("invalid freshness policy")
    reasons = []
    age = (cutoff - snapshot.started_at).total_seconds()
    if snapshot.status != "OK":
        reasons.append("FETCH_FAILED")
    if snapshot.available_at > cutoff or not 0 <= age <= max_age_seconds:
        reasons.append("STALE_OR_UNAVAILABLE")
    # Both US civil dates must be covered, including the blackout margins.
    for edge in (cutoff - timedelta(minutes=30), cutoff + timedelta(minutes=30)):
        for zone in ("America/Chicago", "America/New_York"):
            if (
                not snapshot.window_start
                <= edge.astimezone(ZoneInfo(zone)).date()
                <= (snapshot.window_end)
            ):
                reasons.append("OUTSIDE_WINDOW")
    if any(not any(r.release_id == rid for r in snapshot.dates) for rid in RELEASES):
        reasons.append("MISSING_RELEASE_INVENTORY")
    for row in snapshot.dates:
        candidates = [
            e
            for e in evidence
            if (e.release_id, e.date) == (row.release_id, row.date)
            and e.available_at <= cutoff < e.valid_until
        ]
        times = {e.scheduled_at() for e in candidates}
        if len(times) != 1:
            reasons.append("UNKNOWN_OR_CONFLICTING_TIME")
        elif abs((times.pop() - cutoff).total_seconds()) <= 1800:
            reasons.append("EVENT_BLACKOUT")
    return {
        "block_entries": bool(reasons),
        "reasons": sorted(set(reasons)),
        "calendar_coverage_complete": False,
        "execution_enabled": False,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--start", type=date.fromisoformat, required=True)
    parser.add_argument("--end", type=date.fromisoformat, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--previous", type=Path)
    parser.add_argument(
        "--time-evidence",
        type=Path,
        help="JSON array of independently checked, per-event time evidence",
    )
    args = parser.parse_args(argv)
    try:
        evidence = ()
        evidence_hash = None
        if args.time_evidence:
            with args.time_evidence.open("rb") as stream:
                raw = stream.read(LIMIT + 1)
            if len(raw) > LIMIT:
                raise ValueError("evidence size limit")
            evidence = TypeAdapter(tuple[TimeEvidence, ...]).validate_json(raw)
            evidence_hash = sha256(raw).hexdigest()
        # Reserve the immutable output before making requests; never overwrite evidence.
        with args.output.open("x", encoding="utf-8") as out:
            key = dotenv_values(args.env_file).get("FRED_API_KEY") or ""
            previous = (
                Snapshot.model_validate_json(args.previous.read_bytes())
                if (args.previous)
                else None
            )
            snapshot = collect(key, args.start, args.end, previous=previous)
            out.write(snapshot.model_dump_json(indent=2) + "\n")
        print(
            json.dumps(
                {
                    "status": snapshot.status,
                    "releases": len(snapshot.dates),
                    "snapshot_hash": snapshot.digest(),
                    "time_evidence_hash": evidence_hash,
                    "restrictions": restrictions(snapshot, evidence, snapshot.available_at),
                    "execution_enabled": False,
                }
            )
        )
        return 0 if snapshot.status == "OK" else 2
    except (OSError, ValueError, FredError):
        print("FRED collection failed; check local configuration. Secrets are not logged.")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
