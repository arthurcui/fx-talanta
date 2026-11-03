"""Additive M2A wire contracts. No dispatch, credentials or broker dependency."""

import hashlib
import json
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BeforeValidator, Field, PlainSerializer, model_validator

from fx_talanta.domain.models import AccountIdentity, FrozenModel, Hash, Identifier, Timestamp


def decimal_input(value):
    if not isinstance(value, (str, Decimal)):
        raise ValueError("financial values require decimal strings")
    return value


def decimal_text(value):
    text = format(value, "f")
    return (text.rstrip("0").rstrip(".") if "." in text else text) if value else "0"


Money = Annotated[
    Decimal,
    BeforeValidator(decimal_input),
    Field(allow_inf_nan=False),
    PlainSerializer(decimal_text, return_type=str),
]
Positive = Annotated[Money, Field(gt=0)]
NonNegative = Annotated[Money, Field(ge=0)]
Sequence = Annotated[int, Field(strict=True, ge=1)]
Action = Literal["ENTER", "CLOSE", "TIGHTEN_STOP", "CANCEL", "HOLD"]
Reason = Literal[
    "ACCEPTED",
    "ACCOUNT_MISMATCH",
    "RELEASE_MISMATCH",
    "POLICY_MISMATCH",
    "HASH_CONFLICT",
    "SEQUENCE_GAP",
    "EXPIRED",
    "FUTURE_MESSAGE",
    "CLOCK_UNCERTAIN",
    "RESERVATION_CONFLICT",
    "STATE_MISMATCH",
    "UNKNOWN_OUTCOME",
    "NOT_OWNED",
    "STALE_QUOTE",
    "HEALTH_BLOCK",
    "LOSS_BLOCK",
    "UNSUPPORTED",
    "BROKER_REJECTED",
]


class Message(FrozenModel):
    version: Literal["ea-protocol/1"] = "ea-protocol/1"
    message_id: UUID
    account: AccountIdentity
    sequence: Sequence
    created_at: Timestamp
    release_hash: Hash
    policy_hash: Hash


class Command(Message):
    expires_at: Timestamp

    @model_validator(mode="after")
    def lifetime(self):
        if self.expires_at <= self.created_at:
            raise ValueError("expiry must follow creation")
        return self


class DecisionIntent(Command):
    kind: Literal["decision_intent"] = "decision_intent"
    decision_id: UUID
    strategy: Identifier
    cutoff: Timestamp
    evidence: Annotated[tuple[Hash, ...], Field(min_length=1, max_length=64)]
    action: Literal["ENTER", "CLOSE", "TIGHTEN_STOP", "HOLD"]
    symbol: Literal["EURUSD", "USDJPY"]
    candidate_id: UUID | None = None
    side: Literal["BUY", "SELL"] | None = None
    position_id: Identifier | None = None
    expected_state_version: Sequence | None = None

    @model_validator(mode="after")
    def intent(self):
        if self.cutoff > self.created_at:
            raise ValueError("future evidence cutoff")
        if self.action == "ENTER":
            if self.candidate_id is None or self.side is None or self.position_id is not None:
                raise ValueError("entry needs candidate and side, not a position")
        elif self.action in {"CLOSE", "TIGHTEN_STOP"}:
            if self.position_id is None or self.expected_state_version is None:
                raise ValueError("management needs owned position/state reference")
        return self


class ExecutionRequest(Command):
    kind: Literal["execution_request"] = "execution_request"
    intent_hash: Hash
    reservation_id: UUID
    snapshot_hash: Hash
    action: Literal["ENTER", "CLOSE", "TIGHTEN_STOP", "CANCEL"]
    symbol: Literal["EURUSD", "USDJPY"]
    broker_symbol: Identifier
    currency: Literal["USD", "CAD"]
    max_volume: Positive
    max_risk: NonNegative
    side: Literal["BUY", "SELL"] | None = None
    stop: Positive | None = None
    target: Positive | None = None
    position_id: Identifier | None = None
    order_id: Identifier | None = None
    expected_state_version: Sequence | None = None

    @model_validator(mode="after")
    def request(self):
        if self.action == "ENTER":
            if self.side is None or self.stop is None or self.target is None or self.max_risk <= 0:
                raise ValueError("entry requires side, protection and risk allowance")
            if self.position_id is not None or self.order_id is not None:
                raise ValueError("entry cannot reference existing broker exposure")
        else:
            if self.max_risk != 0 or self.expected_state_version is None:
                raise ValueError("management cannot authorize additional risk")
            if self.action == "CANCEL" and self.order_id is None:
                raise ValueError("cancel requires reconciled order")
            if self.action != "CANCEL" and self.position_id is None:
                raise ValueError("management requires reconciled position")
            if self.action == "TIGHTEN_STOP" and self.stop is None:
                raise ValueError("tightening needs a stop")
        return self


class ExecutionAck(Message):
    kind: Literal["execution_ack"] = "execution_ack"
    request_id: UUID
    request_hash: Hash
    reservation_id: UUID
    stage: Literal["BACKEND_RECEIVED", "EA_RECEIVED", "BROKER_ACCEPTED", "REJECTED"]
    reason: Reason
    predecessor_hash: Hash | None = None
    # No filled-volume field: receipt/acceptance is never evidence of a fill.

    @model_validator(mode="after")
    def outcome(self):
        if (self.stage == "REJECTED") == (self.reason == "ACCEPTED"):
            raise ValueError("ack stage/reason mismatch")
        return self


class ExecutionState(Message):
    kind: Literal["execution_state"] = "execution_state"
    request_id: UUID
    request_hash: Hash
    reservation_id: UUID
    predecessor_hash: Hash
    state: Literal[
        "SUBMITTING",
        "OUTCOME_UNKNOWN",
        "PARTIALLY_FILLED",
        "FILLED",
        "PROTECTION_PENDING",
        "PROTECTED",
        "CLOSED",
        "REJECTED",
        "CANCELLED",
    ]
    requested_volume: Positive
    filled_volume: NonNegative
    open_volume: NonNegative
    protected_volume: NonNegative
    broker_evidence: tuple[Hash, ...] = ()
    broker_order_id: Identifier | None = None
    broker_position_id: Identifier | None = None
    broker_time_basis: Identifier

    @model_validator(mode="after")
    def quantities(self):
        if (
            not self.protected_volume
            <= self.open_volume
            <= self.filled_volume
            <= self.requested_volume
        ):
            raise ValueError("execution quantity bounds violated")
        if self.state in {"FILLED", "PARTIALLY_FILLED", "PROTECTED", "CLOSED"}:
            if not self.broker_evidence:
                raise ValueError("confirmed lifecycle requires broker evidence")
        if self.state == "FILLED" and self.filled_volume != self.requested_volume:
            raise ValueError("filled requires full requested volume")
        if self.state == "PARTIALLY_FILLED" and not 0 < self.filled_volume < self.requested_volume:
            raise ValueError("partial fill must be strictly partial")
        if self.state == "PROTECTED" and (
            self.open_volume <= 0
            or self.open_volume != self.protected_volume
            or self.broker_position_id is None
        ):
            raise ValueError("protection needs verified open position")
        if self.state == "CLOSED" and self.open_volume != 0:
            raise ValueError("closed cannot carry open exposure")
        return self


class ReconciliationResult(Message):
    kind: Literal["reconciliation_result"] = "reconciliation_result"
    request_id: UUID
    request_hash: Hash
    reservation_id: UUID
    predecessor_hash: Hash
    result: Literal["UNKNOWN", "CONFIRMED", "PROVEN_NOT_EXECUTED"]
    filled_volume: NonNegative
    released_volume: NonNegative
    evidence: tuple[Hash, ...] = ()

    @model_validator(mode="after")
    def proof(self):
        if self.result == "UNKNOWN" and self.released_volume != 0:
            raise ValueError("unknown outcome cannot release reservation")
        if self.result != "UNKNOWN" and not self.evidence:
            raise ValueError("positive broker evidence required; empty history is insufficient")
        if self.filled_volume > 0 and not self.evidence:
            raise ValueError("even a partial confirmed fill requires broker evidence")
        if self.result == "PROVEN_NOT_EXECUTED" and self.filled_volume != 0:
            raise ValueError("not-executed proof conflicts with fill")
        return self


Payload = Annotated[
    DecisionIntent | ExecutionRequest | ExecutionAck | ExecutionState | ReconciliationResult,
    Field(discriminator="kind"),
]


def canonical_bytes(payload: Message) -> bytes:
    return json.dumps(
        payload.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")


def payload_hash(payload: Message) -> str:
    return hashlib.sha256(canonical_bytes(payload)).hexdigest()


class Envelope(FrozenModel):
    payload: Payload
    digest: Hash

    @model_validator(mode="after")
    def verify(self):
        if payload_hash(self.payload) != self.digest:
            raise ValueError("payload hash mismatch")
        return self

    @classmethod
    def seal(cls, payload):
        return cls(payload=payload, digest=payload_hash(payload))


class ChannelTelemetry(FrozenModel):
    version: Literal["channel-telemetry/1"] = "channel-telemetry/1"
    account: AccountIdentity
    symbol: Literal["EURUSD", "USDJPY"]
    channel: Literal["EA", "PYTHON_PACKAGE", "MCP"]
    capability: Literal["QUOTES", "ACCOUNT_RECONCILIATION", "NEWS", "CALENDAR"]
    state: Literal[
        "NOT_CONFIGURED", "DISABLED", "CONNECTING", "HEALTHY", "DEGRADED", "DISCONNECTED", "ERROR"
    ]
    measured_at: Timestamp
    last_heartbeat: Timestamp | None = None
    last_success: Timestamp | None = None
    last_error: Timestamp | None = None
    last_quote_receipt: Timestamp | None = None
    original_tick_at: Timestamp | None = None
    delivery_median_ms: NonNegative | None = None
    delivery_p95_ms: NonNegative | None = None
    window_seconds: Positive | None = None
    samples: Annotated[int, Field(strict=True, ge=0)] = 0
    error_code: Identifier | None = None

    @model_validator(mode="after")
    def measurement(self):
        timing = (self.delivery_median_ms, self.delivery_p95_ms, self.window_seconds)
        if any(x is not None for x in timing):
            if any(x is None for x in timing) or self.samples == 0:
                raise ValueError("latency requires complete measurement window/sample count")
            if self.delivery_p95_ms < self.delivery_median_ms:
                raise ValueError("latency percentiles are unordered")
        elif self.samples:
            raise ValueError("sample count requires measured latency")
        if self.capability != "QUOTES" and (
            self.original_tick_at is not None or self.last_quote_receipt is not None
        ):
            raise ValueError("non-quote channel cannot report a quote")
        for at in (
            self.last_heartbeat,
            self.last_success,
            self.last_quote_receipt,
            self.last_error,
        ):
            if at is not None and at > self.measured_at:
                raise ValueError("receipt/heartbeat is from the future")
        return self

    def quote_age_seconds(self, now: datetime) -> Decimal | None:
        if self.original_tick_at is None:
            return None
        return Decimal(str((now - self.original_tick_at).total_seconds()))

    def quote_fresh(self, now: datetime) -> bool:
        age = self.quote_age_seconds(now)
        return self.capability == "QUOTES" and age is not None and 0 <= age <= 2
