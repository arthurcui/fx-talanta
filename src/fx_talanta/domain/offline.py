"""Typed, decimal-safe contracts for the M0B offline execution boundary."""

from datetime import date
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, model_validator

from fx_talanta.domain.models import (
    AccountIdentity,
    Amount,
    FrozenModel,
    Identifier,
    NonNegative,
    Timestamp,
)

Positive = Annotated[Amount, Field(gt=0)]
Fraction = Annotated[Amount, Field(gt=0, le=1)]
Side = Literal["BUY", "SELL"]
OrderState = Literal[
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


class Instrument(FrozenModel):
    symbol: Literal["EURUSD", "USDJPY"]
    base: Literal["EUR", "USD"]
    quote: Literal["USD", "JPY"]
    contract_size: Positive = Decimal("100000")
    minimum_volume: Positive = Decimal("0.01")
    volume_step: Positive = Decimal("0.01")
    maximum_volume: Positive = Decimal("100")
    minimum_stop: Positive
    maximum_spread: Positive
    maximum_adverse_move: NonNegative
    margin_rate: Fraction = Decimal("0.02")
    commission_per_lot: NonNegative = Decimal("4")  # Each side, in account currency.
    slippage_per_lot: NonNegative = Decimal("5")
    financing_per_lot: NonNegative = Decimal("0")

    @model_validator(mode="after")
    def coherent(self):
        if self.base + self.quote != self.symbol:
            raise ValueError("currency legs must match the symbol")
        if self.minimum_volume > self.maximum_volume:
            raise ValueError("minimum volume exceeds maximum")
        if self.minimum_volume % self.volume_step:
            raise ValueError("minimum volume must align to volume step")
        return self


class Quote(FrozenModel):
    symbol: Literal["EURUSD", "USDJPY"]
    bid: Positive
    ask: Positive
    at: Timestamp

    @model_validator(mode="after")
    def ordered(self):
        if self.bid > self.ask:
            raise ValueError("crossed quote")
        return self


class Market(FrozenModel):
    at: Timestamp
    quotes: tuple[Quote, ...]
    instruments: tuple[Instrument, ...]
    # Account-currency value of one unit of each currency, at this snapshot time.
    conversion: dict[str, Positive]
    calendar_ok: bool = True
    news_ok: bool = True
    session_open: bool = True
    event_blackout: bool = False

    @model_validator(mode="after")
    def complete(self):
        symbols = [q.symbol for q in self.quotes]
        if len(symbols) != len(set(symbols)):
            raise ValueError("duplicate quote")
        if set(symbols) != {i.symbol for i in self.instruments}:
            raise ValueError("quote/specification mismatch")
        if len(self.instruments) != len(symbols):
            raise ValueError("duplicate specification")
        if self.conversion.get("USD") != Decimal("1"):
            raise ValueError("M0B simulator uses USD account currency")
        for instrument in self.instruments:
            if not {instrument.base, instrument.quote} <= self.conversion.keys():
                raise ValueError("missing currency conversion")
        if any(q.at > self.at for q in self.quotes):
            raise ValueError("quote from the future")
        return self

    def quote_for(self, symbol: str) -> Quote:
        return next(q for q in self.quotes if q.symbol == symbol)

    def spec_for(self, symbol: str) -> Instrument:
        return next(i for i in self.instruments if i.symbol == symbol)


class Policy(FrozenModel):
    version: Identifier = "offline-risk/1"
    capital: Positive = Decimal("10000")
    trade_fraction: Fraction = Decimal("0.0025")
    aggregate_fraction: Fraction = Decimal("0.005")
    daily_fraction: Fraction = Decimal("0.01")
    drawdown_fraction: Fraction = Decimal("0.05")
    gross_multiple: Positive = Decimal("2")
    currency_multiple: Positive = Decimal("1")
    margin_fraction: Fraction = Decimal("0.20")
    maximum_positions: Annotated[int, Field(ge=1, le=2)] = 2
    quote_age_seconds: Annotated[int, Field(ge=1, le=2)] = 2
    protection_seconds: Annotated[int, Field(ge=1)] = 5
    healthy_samples: Annotated[int, Field(ge=2)] = 2
    protection_mode: Literal["INITIAL_STOP", "FILL_THEN_PROTECT"] = "INITIAL_STOP"


class EntryIntent(FrozenModel):
    intent_id: UUID
    account: AccountIdentity
    decision_id: UUID
    strategy: Identifier = "fixture/1"
    policy_version: Identifier = "offline-risk/1"
    symbol: Literal["EURUSD", "USDJPY"]
    side: Side
    stop: Positive
    target: Positive
    benchmark: Positive
    expires_at: Timestamp
    exit_at: Timestamp


class Position(FrozenModel):
    position_id: UUID
    entry_id: UUID
    symbol: Literal["EURUSD", "USDJPY"]
    side: Side
    volume: NonNegative
    price: Positive
    stop: Positive | None
    target: Positive | None
    version: Annotated[int, Field(ge=1)] = 1
    owned: bool = True
    entry_cost: NonNegative = Decimal("0")
    realized: Amount = Decimal("0")


class BrokerRequest(FrozenModel):
    request_id: UUID
    account: AccountIdentity
    action: Literal["ENTER", "CLOSE", "TIGHTEN_STOP", "CANCEL"]
    entry_id: UUID
    symbol: Literal["EURUSD", "USDJPY"]
    volume: NonNegative = Decimal("0")
    side: Side = "BUY"
    stop: Positive | None = None
    target: Positive | None = None
    position_id: UUID | None = None
    expected_version: int | None = None
    initial_stop: bool = True


class BrokerOrder(FrozenModel):
    request: BrokerRequest
    state: Literal["ACKNOWLEDGED", "PARTIALLY_FILLED", "FILLED", "REJECTED", "CANCELLED"]
    filled: NonNegative = Decimal("0")
    remaining: NonNegative = Decimal("0")
    reason: str = ""


class Deal(FrozenModel):
    deal_id: UUID
    request_id: UUID
    position_id: UUID
    action: Literal["ENTER", "CLOSE"]
    volume: Positive
    price: Positive
    commission: NonNegative
    realized: Amount
    at: Timestamp


class CashFlow(FrozenModel):
    flow_id: UUID
    amount: Amount
    equity_before: Positive
    at: Timestamp
    classified: bool = True


class BrokerBook(FrozenModel):
    account: AccountIdentity
    initial_balance: Positive
    balance: Amount
    orders: tuple[BrokerOrder, ...] = ()
    positions: tuple[Position, ...] = ()
    deals: tuple[Deal, ...] = ()
    cash_flows: tuple[CashFlow, ...] = ()
    calls: tuple[UUID, ...] = ()


class Reservation(FrozenModel):
    volume: NonNegative
    risk_per_lot: NonNegative
    gross_per_lot: NonNegative
    margin_per_lot: NonNegative
    currency_per_lot: dict[str, Amount]


class Entry(FrozenModel):
    intent: EntryIntent
    state: OrderState
    reservation: Reservation | None = None
    request: BrokerRequest | None = None
    submitted_at: Timestamp | None = None
    reason: str = ""
    case_id: UUID | None = None


class Operation(FrozenModel):
    request: BrokerRequest
    state: Literal["SUBMITTING", "OUTCOME_UNKNOWN", "COMPLETED", "REJECTED"]
    reason: str = ""


class LossLedger(FrozenModel):
    day: date
    start_equity: Amount
    day_flow_base: Amount
    processed_flows: tuple[UUID, ...] = ()
    units: Positive
    high_water_nav: Positive = Decimal("1")
    hard_halt: bool = False
    loss_pause_day: date | None = None
    day_loss: NonNegative = Decimal("0")


class GatewayBook(FrozenModel):
    account: AccountIdentity
    policy: Policy
    state: Literal[
        "STARTUP_RECONCILE",
        "RUNNING",
        "DEGRADED_PROTECT",
        "OUTCOME_UNKNOWN",
        "PROTECTION_PENDING",
        "LOSS_PAUSE",
        "HARD_HALT",
    ] = "STARTUP_RECONCILE"
    entries: tuple[Entry, ...] = ()
    operations: tuple[Operation, ...] = ()
    losses: LossLedger | None = None
    healthy_count: int = 0
    health_at: Timestamp | None = None
    administrative_pause: bool = False
    integrity_halt: bool = False


class Fault(FrozenModel):
    """Deterministic simulator transport/venue outcomes, never trading policy."""

    kind: Literal[
        "NORMAL",
        "REJECT",
        "ACK_ONLY",
        "PARTIAL",
        "LOST_RESPONSE",
        "TIMEOUT_BEFORE",
        "NO_STOP",
        "GAP_FILL",
    ] = "NORMAL"
    fraction: Fraction = Decimal("0.5")
    price_delta: Amount = Decimal("0")
