"""Offline validation of historical MT5 calendar captures; no terminal collection."""

import argparse
import json
from collections import Counter
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, model_validator

from fx_talanta.domain.models import FrozenModel, Hash, Identifier, Timestamp, utc

LIMIT = 2 * 1024 * 1024
Currency = Literal["USD", "EUR", "JPY"]
Integer = Annotated[int, Field(strict=True)]
Epoch = Annotated[Integer, Field(ge=0, le=32503680000)]
Id = Annotated[str, Field(pattern=r"^[1-9][0-9]{0,19}$")]
RawValue = Annotated[str, Field(pattern=r"^-?(0|[1-9][0-9]{0,18})$")]


class ClockSegment(FrozenModel):
    utc_from: Timestamp
    utc_until: Timestamp
    server_offset_seconds: Annotated[Integer, Field(ge=-50400, le=50400)]

    @model_validator(mode="after")
    def ordered(self):
        if not self.utc_from < self.utc_until:
            raise ValueError("invalid clock interval")
        return self


class ClockPolicy(FrozenModel):
    version: Identifier
    bridge_id: Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")]
    terminal_build: Annotated[Integer, Field(gt=0)]
    evidence_type: Literal["INDEPENDENT_CALENDAR_CHECK", "SYNTHETIC"]
    evidence_hash: Hash
    verified_at: Timestamp
    segments: Annotated[tuple[ClockSegment, ...], Field(min_length=1, max_length=8)]

    @model_validator(mode="after")
    def continuous(self):
        for a, b in zip(self.segments, self.segments[1:], strict=False):
            if a.utc_until != b.utc_from:
                raise ValueError("clock intervals must be ordered and contiguous")
        if self.segments[-1].utc_until - self.segments[0].utc_from > timedelta(days=31):
            raise ValueError("clock qualification is bounded to 31 days")
        return self

    def decode(self, stamp):
        wall = datetime.fromtimestamp(stamp, UTC)
        candidates = {
            wall - timedelta(seconds=s.server_offset_seconds)
            for s in self.segments
            if s.utc_from <= wall - timedelta(seconds=s.server_offset_seconds) < s.utc_until
        }
        if len(candidates) != 1:
            raise ValueError("ambiguous, nonexistent or unqualified server time")
        return candidates.pop()


class CalendarValue(FrozenModel):
    value_id: Id
    event_id: Id
    currency: Currency
    server_time: Epoch
    period_server_time: Epoch
    source_revision: Annotated[Integer, Field(ge=0)]
    time_mode: Annotated[str, Field(pattern=r"^CALENDAR_TIMEMODE_[A-Z]+$")]
    importance: Annotated[str, Field(pattern=r"^CALENDAR_IMPORTANCE_[A-Z]+$")]
    unit: Identifier
    multiplier: Identifier
    digits: Annotated[Integer, Field(ge=0, le=16)]
    actual_raw: RawValue
    forecast_raw: RawValue
    previous_raw: RawValue
    revised_previous_raw: RawValue

    @model_validator(mode="after")
    def ranges(self):
        if max(int(self.value_id), int(self.event_id)) > 2**64 - 1:
            raise ValueError("ID exceeds unsigned 64-bit range")
        for name in ("actual_raw", "forecast_raw", "previous_raw", "revised_previous_raw"):
            if not -(2**63) <= int(getattr(self, name)) < 2**63:
                raise ValueError("value exceeds signed 64-bit range")
        return self


class Export(FrozenModel):
    schema_version: Literal[1]
    bridge_id: str
    terminal_build: Integer
    mode: Literal["FULL_SNAPSHOT"]
    status: Literal["COMPLETE", "FAILED"]
    error_code: Integer
    server_from: Epoch
    server_until: Epoch
    started_utc: Epoch
    finished_utc: Epoch
    elapsed_ms: Annotated[Integer, Field(ge=0)]
    counts: dict[Currency, Annotated[Integer, Field(ge=0, lt=500)]]
    values: Annotated[tuple[CalendarValue, ...], Field(max_length=1497)]
    execution_enabled: Literal[False]

    @model_validator(mode="after")
    def complete(self):
        if self.status != "COMPLETE" or self.error_code != 0:
            raise ValueError("failed or partial export")
        if not 0 < self.server_until - self.server_from <= 31 * 86400:
            raise ValueError("invalid explicit query window")
        if not 0 <= self.finished_utc - self.started_utc <= 31 or self.elapsed_ms > 30000:
            raise ValueError("export exceeded collection budget or clock regressed")
        if abs((self.finished_utc - self.started_utc) - self.elapsed_ms / 1000) > 2:
            raise ValueError("export clocks diverged")
        counts = Counter(v.currency for v in self.values)
        if set(self.counts) != {"USD", "EUR", "JPY"} or any(
            self.counts[c] != counts[c] for c in self.counts
        ):
            raise ValueError("currency inventory or counts incomplete")
        if len({v.value_id for v in self.values}) != len(self.values):
            raise ValueError("duplicate value IDs")
        if any(not self.server_from <= v.server_time <= self.server_until for v in self.values):
            raise ValueError("out-of-window value")
        return self


def parse(raw):
    if len(raw) > LIMIT:
        raise ValueError("export size bound")

    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    return Export.model_validate(json.loads(raw.decode("utf-8-sig"), object_pairs_hook=unique))


def decimal_value(raw):
    value = int(raw)
    return None if value == -(2**63) else str(Decimal(value) / Decimal(1000000))


def normalize(raw, policy, imported_at, *, fixture=False):
    policy = ClockPolicy.model_validate(policy.model_dump(mode="json"))
    imported_at = utc(imported_at)
    snapshot = parse(raw)
    if policy.evidence_type == "SYNTHETIC" and not fixture:
        raise ValueError("synthetic mapping cannot import real calendar evidence")
    if snapshot.bridge_id != policy.bridge_id or snapshot.terminal_build != policy.terminal_build:
        raise ValueError("bridge/build differs from clock qualification")
    started = datetime.fromtimestamp(snapshot.started_utc, UTC)
    finished = datetime.fromtimestamp(snapshot.finished_utc, UTC)
    if not policy.verified_at <= started <= finished <= imported_at:
        raise ValueError("invalid qualification/export/import ordering")
    start, end = policy.decode(snapshot.server_from), policy.decode(snapshot.server_until)
    if start >= end:
        raise ValueError("invalid normalized query window")
    events, uncertain = [], []
    for value in snapshot.values:
        if value.time_mode != "CALENDAR_TIMEMODE_DATETIME":
            uncertain.append(value.value_id)
            continue
        at = policy.decode(value.server_time)
        if not start <= at <= end:
            raise ValueError("normalized event outside declared window")
        impact = {
            "CALENDAR_IMPORTANCE_HIGH": "HIGH",
            "CALENDAR_IMPORTANCE_MODERATE": "MEDIUM",
            "CALENDAR_IMPORTANCE_LOW": "LOW",
        }.get(value.importance, "UNKNOWN")
        events.append(
            {
                "value_id": value.value_id,
                "event_id": value.event_id,
                "currency": value.currency,
                "scheduled_at": at.isoformat(),
                "status": "SCHEDULED",
                "impact": impact,
                "source_revision": value.source_revision,
                "actual": decimal_value(value.actual_raw),
                "forecast": decimal_value(value.forecast_raw),
                "previous": decimal_value(value.previous_raw),
                "revised_previous": decimal_value(value.revised_previous_raw),
                "unit": value.unit,
                "multiplier": value.multiplier,
                "digits": value.digits,
            }
        )
    return {
        "schema_version": 1,
        "bridge_id": snapshot.bridge_id,
        "clock_policy_hash": sha256(policy.model_dump_json().encode()).hexdigest(),
        "source_hash": sha256(raw).hexdigest(),
        "exported_at": finished.isoformat(),
        "available_at": imported_at.isoformat(),
        "coverage_from": start.isoformat(),
        "coverage_until": end.isoformat(),
        "export_age_seconds": (imported_at - finished).total_seconds(),
        "transport_fresh": (imported_at - finished).total_seconds() <= 120,
        "events": events,
        "uncertain_time_ids": uncertain,
        "raw_snapshot": snapshot.model_dump(mode="json"),
        "provenance": "SCRIPTED_FIXTURE" if fixture else "MT5_CALENDAR_EXPORT",
        "qualified_for_trading": False,
        "execution_enabled": False,
    }


def import_file(journal, raw, policy, now):
    attempt = journal.begin("mt5_calendar", now)
    try:
        normalized = normalize(raw, policy, now)
        journal.finish(attempt, {"status": "OK", "payload": normalized}, now)
    except (ValueError, TypeError, KeyError):
        journal.finish(
            attempt,
            {
                "status": "FAILED",
                "error": "CALENDAR_EXPORT_OR_MAPPING_INVALID",
                "source_hash": sha256(raw).hexdigest(),
            },
            now,
        )
        raise ValueError("calendar import rejected; failure preserved") from None
    return normalized


def main(argv=None):
    from fx_talanta.provider_pipeline import Journal, status_lock

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--export", type=Path, required=True)
    parser.add_argument("--clock-policy", type=Path, required=True)
    parser.add_argument("--journal", type=Path, required=True)
    args = parser.parse_args(argv)
    try:

        def read(path):
            with path.open("rb") as stream:
                raw = stream.read(LIMIT + 1)
            if len(raw) > LIMIT:
                raise ValueError("file size bound")
            return raw

        raw = read(args.export)
        policy = ClockPolicy.model_validate_json(read(args.clock_policy))
        with status_lock(args.journal.with_suffix(".collector")):
            journal = Journal(args.journal, create=True)
            try:
                result = import_file(journal, raw, policy, datetime.now(UTC))
                print(
                    json.dumps(
                        {
                            "imported_events": len(result["events"]),
                            "uncertain_times": len(result["uncertain_time_ids"]),
                            "transport_fresh": result["transport_fresh"],
                            "qualified_for_trading": False,
                            "execution_enabled": False,
                        }
                    )
                )
            finally:
                journal.close()
        return 0
    except Exception:
        print("Calendar bridge import failed; entries remain blocked.")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
