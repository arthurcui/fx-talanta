"""Bounded quote-age evidence for local inspection, never entry authority."""

import platform
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Annotated, Literal

from pydantic import Field, model_validator

from fx_talanta.domain.models import FrozenModel, Hash, Identifier, Timestamp


def host_identity():
    return sha256(platform.node().encode()).hexdigest()


class QuoteClock(FrozenModel):
    version: Literal["inspection-quote-clock/1"] = "inspection-quote-clock/1"
    binding_hash: Hash
    host_hash: Hash
    verified_at: Timestamp
    verified_monotonic: Annotated[float, Field(ge=0, allow_inf_nan=False)]
    valid_until: Timestamp
    server_offset_seconds: Annotated[int, Field(ge=-50400, le=50400)]
    initial_error_ms: Annotated[float, Field(ge=0, le=100, allow_inf_nan=False)]
    evidence_hash: Hash
    symbols: Annotated[tuple[Identifier, ...], Field(min_length=1, max_length=100)]

    @model_validator(mode="after")
    def bounded(self):
        if not 0 < (self.valid_until - self.verified_at).total_seconds() <= 300:
            raise ValueError("inspection clock window must be at most five minutes")
        if len(set(self.symbols)) != len(self.symbols):
            raise ValueError("duplicate quote symbols")
        return self

    def fingerprint(self):
        return sha256(self.model_dump_json().encode()).hexdigest()

    def status(self, now, monotonic, host):
        elapsed = monotonic - self.verified_monotonic
        wall = (now - self.verified_at).total_seconds()
        if host != self.host_hash:
            return "CLOCK_HOST_MISMATCH", None
        if elapsed < 0 or abs(wall - elapsed) > 0.01 + max(elapsed, 0) * 0.0001:
            return "CLOCK_CHANGED", None
        if not self.verified_at <= now < self.valid_until:
            return "CLOCK_EXPIRED", None
        # 100 ppm drift allowance plus 1 ms timestamp quantization; no age subtraction.
        uncertainty = self.initial_error_ms + elapsed * 0.1 + 1
        if uncertainty > 100:
            return "CLOCK_UNCERTAIN", None
        return "VERIFIED_BOUNDED", uncertainty


class QuoteSample(FrozenModel):
    symbol: Identifier
    native_time_ms: Annotated[int, Field(strict=True, ge=1, le=9000000000000)] | None
    received_at: Timestamp
    state: Literal["AVAILABLE", "MISSING", "INVALID"]

    @model_validator(mode="after")
    def coherent(self):
        if (self.state == "AVAILABLE") != (self.native_time_ms is not None):
            raise ValueError("quote state/timestamp mismatch")
        return self


def project_quotes(samples, proof, now, monotonic, host, source_recent):
    clock, error = proof.status(now, monotonic, host)
    rows = []
    for sample in samples:
        age = upper = None
        state = sample.state
        if clock != "VERIFIED_BOUNDED":
            state = clock
        elif sample.state == "AVAILABLE":
            original = datetime.fromtimestamp(sample.native_time_ms / 1000, UTC) - timedelta(
                seconds=proof.server_offset_seconds
            )
            age = (now - original).total_seconds()
            upper = age + error / 1000
            # A timestamp future-dated at receipt cannot become valid merely by waiting.
            state = (
                "FUTURE"
                if original > sample.received_at or age < 0
                else "FRESH"
                if upper <= 2
                else "STALE"
            )
        if not source_recent:
            state = "SOURCE_STALE"
        rows.append(
            dict(
                symbol=sample.symbol,
                state=state,
                age_seconds=age,
                age_upper_bound_seconds=upper,
                uncertainty_ms=error,
                received_at=sample.received_at.isoformat(),
            )
        )
    overall = "FRESH" if rows and all(r["state"] == "FRESH" for r in rows) else "NOT_FRESH"
    if clock != "VERIFIED_BOUNDED":
        overall = clock
    if not source_recent:
        overall = "SOURCE_STALE"
    return dict(
        clock_status=clock,
        freshness=overall,
        quotes=rows,
        metric="AGE_SINCE_ORIGINAL_BROKER_TIMESTAMP_NOT_NETWORK_LATENCY",
        assessed_at=now.isoformat(),
        uncertainty_scope="HOST_CLOCK_AND_TIMESTAMP_QUANTIZATION_ONLY",
        broker_clock_error_independently_bounded=False,
        entry_ceiling_seconds=2,
        entry_ready=False,
    )
