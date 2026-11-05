"""BEA GDP/PCE schedule normalization, without coverage or delivery promotion.

The source has no immutable release-instance IDs. Occurrence identities therefore
include the normalized time. Removed/moved occurrences are not inferred cancelled:
the journal retains the older blackout until independent reconciliation exists.
"""

import json
import re
from datetime import date, datetime
from hashlib import sha256
from typing import Literal

from pydantic import Field, model_validator

from fx_talanta.domain.models import FrozenModel, Hash, Timestamp, utc

URL = "https://apps.bea.gov/API/signup/release_dates.json"
FAMILIES = {"Gross Domestic Product": "GDP", "Personal Income and Outlays": "PCE"}
LIMIT = 2 * 1024 * 1024


class Occurrence(FrozenModel):
    family: Literal["GDP", "PCE"]
    original_time: str = Field(max_length=80)
    precision: Literal["EXACT", "DATE_ONLY"]
    scheduled_at: Timestamp | None
    calendar_date: date

    @model_validator(mode="after")
    def consistent(self):
        if self.precision == "EXACT":
            original = utc(datetime.fromisoformat(self.original_time))
            if original != self.scheduled_at or original.date() != self.calendar_date:
                raise ValueError("inconsistent exact time")
        elif (
            self.scheduled_at is not None
            or date.fromisoformat(self.original_time) != self.calendar_date
        ):
            raise ValueError("date-only time cannot acquire an invented hour")
        return self

    def identity(self):
        when = self.scheduled_at.isoformat() if self.scheduled_at else str(self.calendar_date)
        return sha256(f"bea:{self.family}:{self.precision}:{when}".encode()).hexdigest()


class Snapshot(FrozenModel):
    parser: Literal["bea-calendar/1"] = "bea-calendar/1"
    received_at: Timestamp
    source_hash: Hash
    source_updated: str | None = Field(default=None, max_length=128)
    events: tuple[Occurrence, ...] = Field(max_length=10000)
    duplicate_count: int = Field(ge=0)
    qualified_for_trading: Literal[False] = False

    @model_validator(mode="after")
    def unique(self):
        if len({e.identity() for e in self.events}) != len(self.events):
            raise ValueError("duplicate normalized occurrence")
        if {e.family for e in self.events} != {"GDP", "PCE"}:
            raise ValueError("both required BEA families must be present")
        return self


def parse(raw, observed):
    if len(raw) > LIMIT:
        raise ValueError("body bound")

    def unique_keys(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    document = json.loads(raw, object_pairs_hook=unique_keys)
    if not isinstance(document, dict):
        raise ValueError("schedule object required")
    events, seen, duplicates = [], set(), 0
    for name, family in FAMILIES.items():
        rows = document[name]["release_dates"]
        if not isinstance(rows, list) or not 1 <= len(rows) <= 5000:
            raise ValueError("bounded nonempty release list required")
        for value in rows:
            if not isinstance(value, str) or len(value) > 80:
                raise ValueError("invalid time")
            exact = not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value)
            when = utc(datetime.fromisoformat(value)) if exact else None
            item = Occurrence(
                family=family,
                original_time=value,
                precision="EXACT" if exact else "DATE_ONLY",
                scheduled_at=when,
                calendar_date=when.date() if when else date.fromisoformat(value),
            )
            if item.identity() in seen:
                duplicates += 1
            else:
                seen.add(item.identity())
                events.append(item)
    return Snapshot(
        received_at=observed,
        source_hash=sha256(raw).hexdigest(),
        source_updated=document.get("file_last_updated"),
        events=tuple(sorted(events, key=lambda e: e.identity())),
        duplicate_count=duplicates,
    )


def candidates(payload, now):
    snapshot = Snapshot.model_validate(payload)
    if snapshot.received_at > now:
        raise ValueError("future receipt")
    return [
        (
            e.identity(),
            {
                "family": e.family,
                "currency": "USD",
                "precision": e.precision,
                "scheduled_at": e.scheduled_at.isoformat() if e.scheduled_at else None,
                "calendar_date": str(e.calendar_date),
                "impact": "HIGH",
                "status": "SCHEDULED",
            },
        )
        for e in snapshot.events
    ]
