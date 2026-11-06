"""Explicit telemetry semantics for immutable, offline dashboard snapshots."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field, model_validator

from fx_talanta.domain.models import AccountIdentity, FrozenModel, Record, Timestamp


class Channel(FrozenModel):
    name: Literal["EA", "Python", "MCP"]
    connection: Literal["CONNECTED", "DISCONNECTED", "UNKNOWN"] = "UNKNOWN"
    observed_at: Timestamp | None = None
    quote_at: Timestamp | None = None
    received_at: Timestamp | None = None
    clock_uncertainty_ms: Annotated[float, Field(ge=0, allow_inf_nan=False)] | None = None
    symbol: Literal["EURUSD", "USDJPY"] | None = None

    def metrics(self, now: datetime):
        age = (now - self.quote_at).total_seconds() * 1000 if self.quote_at else None
        receipt_age = (now - self.observed_at).total_seconds() if self.observed_at else None
        delay = (
            (self.received_at - self.quote_at).total_seconds() * 1000
            if self.received_at and self.quote_at
            else None
        )
        invalid = any(v is not None and v < 0 for v in (age, receipt_age, delay)) or (
            self.received_at is not None and self.received_at > now
        )
        clock_ok = self.clock_uncertainty_ms is not None and self.clock_uncertainty_ms <= 100
        freshness = (
            "CLOCK_UNVERIFIED"
            if invalid or not clock_ok
            else "UNKNOWN"
            if age is None
            else "FRESH"
            if age + self.clock_uncertainty_ms <= 2000
            else "STALE"
        )
        return dict(
            **self.model_dump(mode="json"),
            quote_age_ms=age,
            transport_delay_ms=delay,
            freshness=freshness,
            telemetry_status=(
                "UNKNOWN"
                if receipt_age is None
                else "INVALID_TIME"
                if invalid
                else "RECENT"
                if receipt_age <= 15
                else "STALE"
            ),
            entry_ready=False,
        )


class Snapshot(FrozenModel):
    schema_version: Literal["dashboard-snapshot/1"] = "dashboard-snapshot/1"
    label: Annotated[str, Field(min_length=1, max_length=80)]
    source: Literal["SYNTHETIC", "RECORDED_SIMULATOR"]
    captured_at: Timestamp
    account: AccountIdentity
    records: Annotated[tuple[Record, ...], Field(max_length=1000)] = ()
    channels: Annotated[tuple[Channel, ...], Field(max_length=3)] = ()

    @model_validator(mode="after")
    def scope(self):
        if self.account.environment != "PAPER" or self.account.venue != "SIMULATOR":
            raise ValueError("dashboard imports only offline PAPER simulator snapshots")
        if any(r.account != self.account or r.recorded_at > self.captured_at for r in self.records):
            raise ValueError("mixed account or future record")
        if len({r.record_id for r in self.records}) != len(self.records):
            raise ValueError("duplicate record")
        if len({c.name for c in self.channels}) != len(self.channels):
            raise ValueError("duplicate channel")
        if any(c.observed_at and c.observed_at > self.captured_at for c in self.channels):
            raise ValueError("future telemetry")
        return self
