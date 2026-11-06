"""Inspection-only broker receipts; never a quote clock or execution input."""

import time
from hashlib import sha256
from pathlib import Path
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field

from fx_talanta.dashboard.quote_clock import QuoteClock, QuoteSample, host_identity, project_quotes
from fx_talanta.domain.models import Amount, FrozenModel, Hash, Timestamp


class CurrentConfig(FrozenModel):
    source: Literal["CURRENT_DEMO_INSPECTION"] = "CURRENT_DEMO_INSPECTION"
    label: Annotated[str, Field(min_length=1, max_length=80)]
    run_id: UUID
    binding_hash: Hash
    receipt_file: Path
    quote_clock: QuoteClock | None = None


class Receipt(FrozenModel):
    version: Literal["demo-inspection/1"] = "demo-inspection/1"
    run_id: UUID
    binding_hash: Hash
    sequence: Annotated[int, Field(ge=1)]
    started_at: Timestamp
    observed_at: Timestamp
    currency: Annotated[str, Field(pattern="^[A-Z]{3}$")]
    balance: Amount
    equity: Amount
    positions: Annotated[int, Field(ge=0, le=2000)]
    orders: Annotated[int, Field(ge=0, le=2000)]
    quotes_received: Annotated[int, Field(ge=0, le=100)]
    expected_quotes: Annotated[int, Field(ge=1, le=100)]
    execution_enabled: Literal[False] = False
    quote_freshness: Literal["UNVERIFIED"] = "UNVERIFIED"
    quote_clock_hash: Hash | None = None
    quotes: Annotated[tuple[QuoteSample, ...], Field(max_length=100)] = ()


class CurrentBrokerView:
    def __init__(self, config, *, monotonic=time.monotonic, host=host_identity):
        self.config = CurrentConfig.model_validate(config.model_dump(mode="json"))
        if not self.config.receipt_file.is_absolute():
            raise ValueError("absolute receipt path required")
        self.repo = None
        self.monotonic, self.host = monotonic, host
        if (
            self.config.quote_clock
            and self.config.quote_clock.binding_hash != self.config.binding_hash
        ):
            raise ValueError("clock binding mismatch")

    def bind_journal(self, repo):
        self.repo = repo
        with repo.lock, repo.conn:
            repo.conn.execute(
                "CREATE TABLE IF NOT EXISTS current_broker_cursor "
                "(singleton INTEGER PRIMARY KEY CHECK(singleton=1), sequence INTEGER, "
                "digest TEXT, observed_at TEXT, checked_at TEXT)"
            )

    def read(self, now):
        sampled_monotonic = self.monotonic()
        if self.repo is None:
            raise ValueError("inspection journal required")
        p = self.config.receipt_file
        if p.is_symlink():
            raise ValueError("receipt symlink rejected")
        with p.open("rb") as stream:
            raw = stream.read(65537)
        if len(raw) > 65536:
            raise ValueError("receipt size bound")
        r = Receipt.model_validate_json(raw)
        if r.run_id != self.config.run_id or r.binding_hash != self.config.binding_hash:
            raise ValueError("receipt binding mismatch")
        if not r.started_at <= r.observed_at <= now or r.quotes_received > r.expected_quotes:
            raise ValueError("receipt time/count invalid")
        digest = sha256(raw).hexdigest()
        proof = self.config.quote_clock
        if proof:
            if not proof.verified_at <= r.started_at <= r.observed_at < proof.valid_until:
                raise ValueError("capture outside verified clock window")
            if r.quote_clock_hash != proof.fingerprint():
                raise ValueError("clock evidence mismatch")
            if len(r.quotes) != r.expected_quotes or len({q.symbol for q in r.quotes}) != len(
                r.quotes
            ):
                raise ValueError("quote coverage mismatch")
            if set(q.symbol for q in r.quotes) != set(proof.symbols):
                raise ValueError("quote symbol binding mismatch")
            if any(not r.started_at <= q.received_at <= r.observed_at for q in r.quotes):
                raise ValueError("quote receipt outside capture")
        elif r.quote_clock_hash or r.quotes:
            raise ValueError("unbound quote evidence")
        from datetime import datetime

        with self.repo.lock, self.repo.conn:
            old = self.repo.conn.execute("SELECT * FROM current_broker_cursor").fetchone()
            if old and (
                r.sequence < old[1]
                or (r.sequence == old[1] and digest != old[2])
                or r.observed_at < datetime.fromisoformat(old[3])
                or now < datetime.fromisoformat(old[4])
            ):
                raise ValueError("receipt rollback or conflict")
            self.repo.conn.execute(
                "INSERT INTO current_broker_cursor VALUES (1,?,?,?,?) "
                "ON CONFLICT(singleton) DO UPDATE SET sequence=excluded.sequence, "
                "digest=excluded.digest,observed_at=excluded.observed_at,checked_at=excluded.checked_at",
                (r.sequence, digest, r.observed_at.isoformat(), now.isoformat()),
            )
        # Oldest read bounds age: a slow capture cannot refresh earlier account fields.
        age = (now - r.started_at).total_seconds()
        recent = age <= 15
        quote_view = (
            project_quotes(r.quotes, proof, now, sampled_monotonic, self.host(), recent)
            if proof
            else None
        )
        return dict(
            label=self.config.label,
            scope="DEMO_INSPECTION_NOT_RECONCILIATION",
            state="RECENT_RECORDED" if recent else "STALE_RECORDED",
            recorded_at=r.observed_at.isoformat(),
            source_sha256=digest,
            execution_enabled=False,
            entry_ready=False,
            current_positions="UNKNOWN",
            transport_at_capture="CONNECTED",
            recorded_clock_policy=quote_view["clock_status"] if quote_view else "NOT_VERIFIED",
            quote_clock=quote_view["clock_status"]
            if quote_view
            else "NOT_INDEPENDENTLY_VERIFIED_BY_DASHBOARD",
            quote_freshness=quote_view["freshness"] if quote_view else "UNVERIFIED",
            quote_observation=quote_view,
            channels={
                "Python": "RECENT_RECEIPT" if recent else "STALE_RECEIPT",
                "EA": "NOT_OBSERVED",
                "MCP": "NOT_OBSERVED",
            },
            snapshot=dict(
                display_status="RECENT_RECORDED" if recent else "STALE_RECORDED",
                observed_at=r.observed_at.isoformat(),
                age_seconds=age,
                currency=r.currency,
                balance_at_capture=str(r.balance),
                equity_at_capture=str(r.equity),
                positions_at_capture=r.positions,
                orders_at_capture=r.orders,
                quotes_received=r.quotes_received,
                expected_quotes=r.expected_quotes,
                quote_latency_seconds=None,
                history_complete_at_capture=False,
            ),
        )
