"""Immutable M0A wire/storage contracts. No broker or model SDK dependency."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID, uuid4

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    model_serializer,
    model_validator,
)


def utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamps must include a timezone")
    return value.astimezone(UTC)


def exact_decimal(value: object) -> object:
    if isinstance(value, (float, bool)):
        raise ValueError("use Decimal or a decimal string, not a float/bool")
    return value


Timestamp = Annotated[datetime, AfterValidator(utc)]
Amount = Annotated[Decimal, BeforeValidator(exact_decimal), Field(allow_inf_nan=False)]
NonNegative = Annotated[Amount, Field(ge=0)]
Text = Annotated[str, Field(min_length=1, max_length=4096)]
Identifier = Annotated[str, Field(min_length=1, max_length=160)]
Hash = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", validate_default=True)


class Environment(StrEnum):
    PAPER = "PAPER"
    LIVE = "LIVE"


class AccountIdentity(FrozenModel):
    environment: Environment
    broker: Identifier
    server: Identifier
    login: Identifier
    venue: Literal["SIMULATOR", "BROKER_DEMO", "BROKER_LIVE"]

    @model_validator(mode="after")
    def valid_venue(self) -> AccountIdentity:
        if (self.environment == Environment.LIVE) != (self.venue == "BROKER_LIVE"):
            raise ValueError("LIVE requires BROKER_LIVE; PAPER requires SIMULATOR or BROKER_DEMO")
        return self


class Versions(FrozenModel):
    component: Identifier = "m0a/0.1.0"
    strategy: Identifier = "fixture/1"
    policy: Identifier = "fixture-records/1"
    model: Identifier = "scripted/1"
    prompt: Identifier = "fixture/1"


class Cost(FrozenModel):
    currency: Annotated[str, Field(pattern=r"^[A-Z]{3}$")] = "USD"
    commission: NonNegative = Decimal("0")
    financing: Amount = Decimal("0")
    model: NonNegative = Decimal("0")
    data: NonNegative = Decimal("0")


class EvidenceLink(FrozenModel):
    record_id: UUID
    relation: Literal["NEWS", "HEALTH", "DECISION", "EXECUTION", "MESSAGE", "ARTIFACT", "CASE"]


class ModelTrace(FrozenModel):
    provider: Identifier = "scripted"
    requested_model: Identifier = "scripted/1"
    returned_model: Identifier = "scripted/1"
    request_id: UUID = Field(default_factory=uuid4)
    latency_ms: Annotated[int, Field(ge=0)] = 0
    input_tokens: Annotated[int, Field(ge=0)] = 0
    output_tokens: Annotated[int, Field(ge=0)] = 0


class Decision(FrozenModel):
    """Untrusted DecisionSource response before account, time and reference validation."""

    account: AccountIdentity
    action: Literal["ENTER", "CLOSE", "TIGHTEN_STOP", "HOLD"]
    candidate_id: Identifier | None = None
    symbol: Literal["EURUSD", "USDJPY"] | None = None
    side: Literal["BUY", "SELL"] | None = None
    position_id: Identifier | None = None
    expected_state_version: Annotated[int, Field(ge=0)] | None = None
    expires_at: Timestamp
    rationale: Text

    @model_validator(mode="after")
    def action_fields(self) -> Decision:
        if self.action == "ENTER" and not (self.candidate_id and self.symbol and self.side):
            raise ValueError("ENTER requires candidate, symbol and side")
        if self.action in {"CLOSE", "TIGHTEN_STOP"} and (
            not self.position_id or self.expected_state_version is None
        ):
            raise ValueError("position action requires position and expected state version")
        return self


class DecisionAttempt(FrozenModel):
    kind: Literal["decision"] = "decision"
    result: Literal["VALID", "HOLD", "MALFORMED", "EXPIRED", "REJECTED"]
    action: Literal["ENTER", "CLOSE", "TIGHTEN_STOP", "HOLD"]
    cutoff: Timestamp
    input_snapshot: Identifier
    candidates: tuple[Identifier, ...] = ()
    response: Annotated[str, Field(max_length=16384)]
    decision: Decision | None = None
    reason: Text
    trace: ModelTrace = Field(default_factory=ModelTrace)

    @model_validator(mode="after")
    def decision_result(self) -> DecisionAttempt:
        if self.result in {"VALID", "HOLD"} and self.decision is None:
            raise ValueError("valid attempts require the validated response")
        if self.result != "VALID" and self.action != "HOLD":
            raise ValueError("unsuccessful decisions must resolve to HOLD")
        if self.result == "HOLD" and self.decision and self.decision.action != "HOLD":
            raise ValueError("HOLD result requires a HOLD decision")
        if self.result == "VALID" and self.decision and self.action != self.decision.action:
            raise ValueError("attempt action must match validated decision")
        return self


class RiskEvaluation(FrozenModel):
    kind: Literal["risk"] = "risk"
    approved: bool
    reasons: tuple[Text, ...]
    checked_limits: tuple[Identifier, ...]
    proposed_volume: NonNegative
    planned_loss: NonNegative
    reservation_id: UUID | None = None
    evaluation_mode: Literal["SCRIPTED", "DETERMINISTIC"] = "SCRIPTED"


class ExecutionEvent(FrozenModel):
    kind: Literal["execution"] = "execution"
    request_id: UUID
    state: Literal[
        "CREATED",
        "VALIDATED",
        "RESERVED",
        "SUBMITTING",
        "ACKNOWLEDGED",
        "PARTIALLY_FILLED",
        "FILLED",
        "PROTECTION_PENDING",
        "PROTECTED",
        "COMPLETED",
        "REJECTED",
        "CANCELLED",
        "OUTCOME_UNKNOWN",
    ]
    order_id: Identifier | None = None
    deal_id: Identifier | None = None
    position_id: Identifier | None = None
    filled_volume: NonNegative = Decimal("0")
    fill_price: NonNegative | None = None
    evidence: Text


class ExperienceCase(FrozenModel):
    kind: Literal["experience"] = "experience"
    operational_result: Literal[
        "SUCCESS", "HOLD", "REJECTED", "INVALID", "EXPIRED", "UNKNOWN", "RECOVERED", "FAILED"
    ]
    policy_compliance: Literal["COMPLIANT", "VIOLATION", "UNKNOWN"]
    economic_outcome: Literal["UNKNOWN", "NOT_APPLICABLE", "PROFIT", "LOSS", "FLAT"]
    net_pnl: Amount | None = None
    outcome_known_at: Timestamp | None = None
    summary: Text

    @model_validator(mode="after")
    def outcome_fields(self) -> ExperienceCase:
        if self.economic_outcome in {"PROFIT", "LOSS", "FLAT"}:
            if self.net_pnl is None or self.outcome_known_at is None:
                raise ValueError("economic result requires P&L and outcome-known time")
            if (
                self.economic_outcome == "PROFIT"
                and self.net_pnl <= 0
                or self.economic_outcome == "LOSS"
                and self.net_pnl >= 0
                or self.economic_outcome == "FLAT"
                and self.net_pnl != 0
            ):
                raise ValueError("economic label does not match net P&L")
        elif self.net_pnl is not None:
            raise ValueError("unknown/not-applicable economics cannot claim realized P&L")
        return self


class Lesson(FrozenModel):
    kind: Literal["lesson"] = "lesson"
    hypothesis: Text
    status: Literal["PROPOSED", "REJECTED", "QUALIFIED"]
    supporting_cases: tuple[UUID, ...]
    contradicting_cases: tuple[UUID, ...] = ()
    sample_size: Annotated[int, Field(ge=0)]
    uncertainty: Text
    activated_at: Timestamp | None = None

    @model_validator(mode="after")
    def qualified_activation(self) -> Lesson:
        if self.activated_at and self.status != "QUALIFIED":
            raise ValueError("only a qualified lesson may have an activation time")
        return self


class StrategyArtifact(FrozenModel):
    kind: Literal["artifact"] = "artifact"
    artifact_hash: Hash
    code_hash: Hash
    configuration_hash: Hash
    feature_version: Identifier
    news_policy_version: Identifier
    interpretation_version: Identifier


class PromotionEvidence(FrozenModel):
    kind: Literal["promotion"] = "promotion"
    artifact_hash: Hash
    engineering_passed: bool
    strategy_evidence_passed: bool
    paper_observation_complete: bool
    result: Literal["RECORDED_ONLY", "REJECTED"]
    activation_enabled: Literal[False] = False
    reason: Text


class NewsRevision(FrozenModel):
    kind: Literal["news"] = "news"
    source: Identifier
    item_id: Identifier
    revision: Annotated[int, Field(ge=1)]
    url: Annotated[str, Field(pattern=r"^https://", max_length=2048)]
    headline: Text
    content_excerpt: Text
    content_hash: Hash
    story_cluster: Identifier
    currencies: tuple[Literal["USD", "EUR", "JPY"], ...]
    event_time: Timestamp | None = None
    published_at: Timestamp
    source_updated_at: Timestamp | None = None
    first_observed_at: Timestamp
    ingested_at: Timestamp
    available_at: Timestamp
    original_timezone: Identifier = "UTC"
    retention: Literal["FIXTURE", "LICENSED_EXCERPT", "HASH_ONLY"] = "FIXTURE"

    @model_validator(mode="after")
    def availability_order(self) -> NewsRevision:
        if not self.published_at <= self.first_observed_at <= self.ingested_at <= self.available_at:
            raise ValueError("publication/observation/ingestion/availability must be ordered")
        if self.source_updated_at and self.source_updated_at > self.first_observed_at:
            raise ValueError("source revision cannot arrive before it exists")
        return self


class SourceHealth(FrozenModel):
    kind: Literal["health"] = "health"
    source: Identifier
    checked_at: Timestamp
    last_success_at: Timestamp | None
    connection: Literal["OK", "FAILED", "UNKNOWN"]
    coverage: Literal["CURRENT", "STALE", "INCOMPLETE", "UNKNOWN"]
    required: bool
    reason: Text


class ConversationMessage(FrozenModel):
    kind: Literal["message"] = "message"
    conversation_id: UUID
    message_id: UUID
    actor_id: Identifier
    authenticated: bool
    role: Literal["USER", "ADVISOR"]
    language: Literal["en", "zh"]
    text: Text
    interpretation: Literal["READ_ONLY", "AMBIGUOUS", "EXPLICIT_COMMAND", "UNAUTHORIZED"]
    interpreted_action: (
        Literal["PAUSE_ENTRIES", "RESUME_ENTRIES", "CLOSE_OWNED_POSITION", "FLATTEN_OWNED_AND_HALT"]
        | None
    ) = None


class AdministrativeCommand(FrozenModel):
    kind: Literal["command"] = "command"
    actor_id: Identifier
    authenticated: Literal[True] = True
    conversation_id: UUID
    message_id: UUID
    request_id: UUID
    action: Literal[
        "PAUSE_ENTRIES", "RESUME_ENTRIES", "CLOSE_OWNED_POSITION", "FLATTEN_OWNED_AND_HALT"
    ]
    position_id: Identifier | None = None
    expires_at: Timestamp
    expected_state_version: Annotated[int, Field(ge=0)]
    status: Literal[
        "INTERPRETED", "ACCEPTED", "REJECTED", "SUBMITTED", "OUTCOME_UNKNOWN", "COMPLETED"
    ]
    outcome: Text

    @model_validator(mode="after")
    def close_position(self) -> AdministrativeCommand:
        if self.action == "CLOSE_OWNED_POSITION" and not self.position_id:
            raise ValueError("close command needs an explicit position")
        return self


class ObservedSymbol(FrozenModel):
    symbol: Identifier
    digits: Annotated[int, Field(ge=0, le=12)]
    volume_min: Annotated[Amount, Field(gt=0)]
    volume_step: Annotated[Amount, Field(gt=0)]
    point: Annotated[Amount, Field(gt=0)]


class ObservedTick(FrozenModel):
    symbol: Identifier
    at: Timestamp
    bid: Annotated[Amount, Field(gt=0)]
    ask: Annotated[Amount, Field(gt=0)]

    @model_validator(mode="after")
    def spread(self):
        if self.ask < self.bid:
            raise ValueError("crossed quote")
        return self


class ObservedBar(FrozenModel):
    symbol: Identifier
    opened_at: Timestamp
    period_seconds: Literal[900, 3600]
    open: Annotated[Amount, Field(gt=0)]
    high: Annotated[Amount, Field(gt=0)]
    low: Annotated[Amount, Field(gt=0)]
    close: Annotated[Amount, Field(gt=0)]

    @model_validator(mode="after")
    def range(self):
        if not self.low <= min(self.open, self.close) <= max(self.open, self.close) <= self.high:
            raise ValueError("invalid OHLC range")
        return self


class ObservedItem(FrozenModel):
    """Account-scoped observation, never an instruction to manage an external order."""

    ticket: Identifier
    symbol: Annotated[str, Field(max_length=160)]
    side: Literal["BUY", "SELL", "OTHER"]
    volume: NonNegative
    price: NonNegative
    at: Timestamp
    type_code: int | None = None
    profit: Amount = Decimal("0")
    commission: Amount = Decimal("0")
    swap: Amount = Decimal("0")
    fee: Amount = Decimal("0")
    stop_loss: NonNegative = Decimal("0")
    take_profit: NonNegative = Decimal("0")
    position_id: str | None = None
    order_id: str | None = None
    initial_volume: NonNegative | None = None
    done_at: Timestamp | None = None
    state_code: int | None = None
    entry_code: int | None = None
    reason_code: int | None = None
    magic: int | None = None


class TerminalSnapshot(FrozenModel):
    sdk_time_offset_seconds: Annotated[int, Field(ge=-50400, le=50400)] = 0
    time_policy_from: Timestamp | None = None
    time_policy_until: Timestamp | None = None
    time_policy_evidence: Text | None = None
    account_before: AccountIdentity
    account_after: AccountIdentity
    terminal_path: Text
    data_path: Text
    build: Annotated[int, Field(gt=0)]
    currency: Annotated[str, Field(pattern=r"^[A-Z]{3}$")]
    connected: bool
    observed_at: Timestamp
    history_from: Timestamp
    history_to: Timestamp
    symbols: Annotated[tuple[ObservedSymbol, ...], Field(max_length=100)]
    ticks: Annotated[tuple[ObservedTick, ...], Field(max_length=100)]
    bars: Annotated[tuple[ObservedBar, ...], Field(max_length=2000)]
    positions: Annotated[tuple[ObservedItem, ...], Field(max_length=2000)]
    orders: Annotated[tuple[ObservedItem, ...], Field(max_length=2000)]
    deals: Annotated[tuple[ObservedItem, ...], Field(max_length=2000)]
    history_complete: bool
    history_orders: Annotated[tuple[ObservedItem, ...], Field(max_length=2000)] = ()
    company: Text | None = None
    margin_mode: int | None = None
    balance: Amount | None = None
    equity: Amount | None = None


class ObservationHealth(FrozenModel):
    schema_version: Literal[2] = 2
    collection_started_at: Timestamp
    transport: Literal["READ_OK", "READ_FAILED", "UNVERIFIED"]
    integrity: Literal["VALID", "INVALID", "UNVERIFIED"]
    complete_read: bool
    quote_max_age_seconds: Annotated[int, Field(ge=1, le=5)] = 5
    transport_failures: Annotated[int, Field(ge=0)]
    completeness_failures: Annotated[int, Field(ge=0)]
    last_successful_read_at: Timestamp | None = None
    quote_ages_seconds: dict[Identifier, Annotated[float, Field(allow_inf_nan=False)]]
    quote_quality: dict[Identifier, Literal["FRESH", "STALE", "UNKNOWN"]]
    final_verification: bool = False
    entry_authorized: Literal[False] = False

    @model_validator(mode="after")
    def coherent(self):
        if self.complete_read and (self.transport != "READ_OK" or self.integrity != "VALID"):
            raise ValueError("complete read requires verified transport")
        if self.complete_read and (self.transport_failures or self.completeness_failures):
            raise ValueError("complete read resets operational failure streaks")
        if set(self.quote_ages_seconds) - set(self.quote_quality):
            raise ValueError("quote ages require corresponding quality states")
        for symbol, quality in self.quote_quality.items():
            age = self.quote_ages_seconds.get(symbol)
            expected = (
                "UNKNOWN"
                if age is None or age < 0
                else "STALE"
                if age > self.quote_max_age_seconds
                else "FRESH"
            )
            if quality != expected:
                raise ValueError("quote quality disagrees with its age")
        return self


class TerminalObservation(FrozenModel):
    kind: Literal["observation"] = "observation"
    binding_hash: Hash
    state: Literal["HEALTHY", "DEGRADED", "BACKOFF", "HALTED"]
    reason: Literal[
        "CURRENT",
        "DISCONNECTED",
        "STALE_TICKS",
        "MISSING_DATA",
        "TIMEOUT",
        "READER_FAILED",
        "INVALID_DATA",
        "IDENTITY_MISMATCH",
        "PATH_MISMATCH",
        "BUILD_CHANGED",
        "CURRENCY_MISMATCH",
        "MODE_MISMATCH",
        "COMPANY_MISMATCH",
        "SDK_MISMATCH",
    ]
    failures: Annotated[int, Field(ge=0)]
    last_success_at: Timestamp | None = None
    next_retry_at: Timestamp | None = None
    snapshot: TerminalSnapshot | None = None
    # Omit absent v2 evidence so legacy wire payloads and hashes remain unchanged.
    health: ObservationHealth | None = None

    @model_serializer(mode="wrap")
    def legacy_wire_compatible(self, handler):
        data = handler(self)
        if self.health is None:
            data.pop("health", None)
        return data

    @model_validator(mode="after")
    def coherent_state(self):
        if self.health and self.health.complete_read != (self.reason in {"CURRENT", "STALE_TICKS"}):
            raise ValueError("complete-read status disagrees with assessment")
        if self.health and self.health.complete_read and self.snapshot is None:
            raise ValueError("complete read requires a snapshot")
        if self.state == "HEALTHY":
            if (
                self.reason != "CURRENT"
                or self.failures
                or self.snapshot is None
                or self.last_success_at is None
                or self.next_retry_at is not None
            ):
                raise ValueError("healthy observation needs a successful snapshot")
        else:
            if self.reason == "CURRENT" or not self.failures:
                raise ValueError("failed observation needs a failure reason/count")
            if (self.state == "HALTED") != (self.next_retry_at is None):
                raise ValueError("only a terminal halt can omit its retry deadline")
        return self


Body = Annotated[
    DecisionAttempt
    | RiskEvaluation
    | ExecutionEvent
    | ExperienceCase
    | Lesson
    | StrategyArtifact
    | PromotionEvidence
    | NewsRevision
    | SourceHealth
    | ConversationMessage
    | AdministrativeCommand
    | TerminalObservation,
    Field(discriminator="kind"),
]


class Record(FrozenModel):
    record_id: UUID = Field(default_factory=uuid4)
    account: AccountIdentity
    recorded_at: Timestamp
    correlation_id: UUID
    provenance: Literal["SCRIPTED_FIXTURE", "OFFLINE_SIMULATION", "BROKER_OBSERVATION"] = (
        "SCRIPTED_FIXTURE"
    )
    versions: Versions = Field(default_factory=Versions)
    costs: Cost = Field(default_factory=Cost)
    supersedes: UUID | None = None
    references: tuple[EvidenceLink, ...] = ()
    body: Body

    @model_validator(mode="after")
    def consistent_record(self) -> Record:
        if self.account.venue == "BROKER_DEMO":
            if (
                not isinstance(self.body, TerminalObservation)
                or self.provenance != "BROKER_OBSERVATION"
            ):
                raise ValueError("demo storage accepts only broker observation evidence")
        elif self.provenance == "BROKER_OBSERVATION":
            raise ValueError("broker observation requires a demo binding")
        if self.supersedes == self.record_id:
            raise ValueError("a correction must reference an earlier record")
        if len(set((r.record_id, r.relation) for r in self.references)) != len(self.references):
            raise ValueError("duplicate evidence references")
        if any(r.record_id == self.record_id for r in self.references):
            raise ValueError("self-reference is not evidence")
        if isinstance(self.body, DecisionAttempt):
            if self.body.cutoff > self.recorded_at:
                raise ValueError("decision cutoff cannot be in the future")
            if self.body.result in {"VALID", "HOLD"} and self.body.decision:
                if self.body.decision.account != self.account:
                    raise ValueError("validated response cannot redirect the account")
                if self.body.decision.expires_at <= self.recorded_at:
                    raise ValueError("valid decision is expired")
        if isinstance(self.body, TerminalObservation):
            health = self.body.health
            if health and (
                health.collection_started_at > self.recorded_at
                or (
                    health.last_successful_read_at
                    and health.last_successful_read_at > self.recorded_at
                )
            ):
                raise ValueError("observation health timestamps cannot be in the future")
            if self.account.environment != Environment.PAPER:
                raise ValueError("observer records require PAPER")
            if self.account.venue == "SIMULATOR" and self.provenance != "SCRIPTED_FIXTURE":
                raise ValueError("observer foundation must be labelled as a scripted fixture")
            snapshot = self.body.snapshot
            if snapshot and (
                snapshot.account_before != self.account
                or snapshot.account_after != self.account
                or snapshot.observed_at > self.recorded_at
            ):
                raise ValueError("observation identity or availability mismatch")
        if isinstance(self.body, NewsRevision) and self.body.available_at > self.recorded_at:
            raise ValueError("news cannot be recorded before availability")
        if isinstance(self.body, ExperienceCase) and self.body.outcome_known_at:
            if self.body.outcome_known_at > self.recorded_at:
                raise ValueError("outcome cannot be known in the future")
        if isinstance(self.body, AdministrativeCommand):
            if self.body.status in {"INTERPRETED", "ACCEPTED"}:
                if self.body.expires_at <= self.recorded_at:
                    raise ValueError("command is expired")
            if not any(r.relation == "MESSAGE" for r in self.references):
                raise ValueError("command must link its original message")
        return self
