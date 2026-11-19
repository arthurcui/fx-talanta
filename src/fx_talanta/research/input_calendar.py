"""Explicit, dataset-bound weekend exceptions for offline HistData research.

This is a reconciled archive convention, not a broker calendar or certification
of historical delivery. Unlisted gaps remain failures. No synthetic bars.
"""

from datetime import timedelta, timezone
from typing import Literal

from pydantic import Field, model_validator

from fx_talanta.domain.models import FrozenModel, Hash, Timestamp

EST = timezone(timedelta(hours=-5))


class WeekendClosure(FrozenModel):
    start: Timestamp
    end: Timestamp

    @model_validator(mode="after")
    def weekend_only(self):
        a, b = self.start.astimezone(EST), self.end.astimezone(EST)
        if (
            (a.weekday(), b.weekday(), a.hour, b.hour) != (4, 6, 17, 17)
            or (a.minute or a.second or a.microsecond or b.minute or b.second or b.microsecond)
            or self.end - self.start != timedelta(hours=48)
        ):
            raise ValueError("only exact Friday 17 to Sunday 17 fixed-EST closures supported")
        return self


class InputCalendar(FrozenModel):
    version: Literal["histdata-reviewed-weekends/1"] = "histdata-reviewed-weekends/1"
    provider: Literal["HistData"] = "HistData"
    symbol: Literal["EURUSD", "USDJPY"]
    source_timezone: Literal["UTC-05:00_NO_DST"] = "UTC-05:00_NO_DST"
    basis: Literal["RECONCILED_ARCHIVE_CONVENTION_NOT_PROVIDER_CERTIFIED"] = (
        "RECONCILED_ARCHIVE_CONVENTION_NOT_PROVIDER_CERTIFIED"
    )
    index_sha256: Hash
    evidence_sha256: Hash
    valid_from: Timestamp
    valid_to: Timestamp
    closures: tuple[WeekendClosure, ...] = Field(min_length=1, max_length=60)

    @model_validator(mode="after")
    def scope(self):
        if self.valid_from >= self.valid_to:
            raise ValueError("invalid input calendar scope")
        previous = self.valid_from
        for closure in self.closures:
            if not previous <= closure.start < closure.end <= self.valid_to:
                raise ValueError("closure outside scope, unordered or overlapping")
            previous = closure.end
        return self

    def permits(self, left, right, minutes):
        # Exact flanking bars are mandatory: losing even the first reopening bar
        # cannot be reclassified as a longer weekend. Calendar affects inputs only.
        return any(
            left == c.start
            and right == c.end + timedelta(minutes=minutes)
            and self.valid_from <= left < right <= self.valid_to
            for c in self.closures
        )
