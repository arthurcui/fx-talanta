"""Versioned, USD-ledger broker-cost scenarios. No broker/network dependency."""

from datetime import datetime, time, timedelta
from decimal import Decimal
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import Field, model_validator

from fx_talanta.brokers.simulator import Simulator
from fx_talanta.domain.models import Amount, FrozenModel, NonNegative, Timestamp
from fx_talanta.domain.offline import Market
from fx_talanta.research.cost_calibration import commission
from fx_talanta.research.store import ReplayStore


class SwapDay(FrozenModel):
    cutoff: Timestamp
    available_at: Timestamp
    multiplier: int = Field(ge=0, le=10)
    buy_usd_per_lot: Amount
    sell_usd_per_lot: Amount
    evidence: str = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def timing(self):
        local = self.cutoff.astimezone(ZoneInfo("America/New_York"))
        if local.time() != time(17) or local.weekday() >= 5:
            raise ValueError("FOREX-style weekday 17:00 New York cutoff required")
        if self.available_at > self.cutoff:
            raise ValueError("financing rate was unavailable at cutoff")
        return self


class BrokerCosts(FrozenModel):
    version: Literal["broker-costs/1"]
    symbol: Literal["EURUSD", "USDJPY"]
    account_currency: Literal["USD"]  # Existing replay ledger is USD-only.
    broker: str = Field(min_length=1, max_length=100)
    account_plan: str = Field(min_length=1, max_length=100)
    status: Literal["SYNTHETIC", "UNQUALIFIED_SCENARIO"]
    evidence: str = Field(min_length=1, max_length=500)
    basis: str = Field(min_length=1, max_length=500)
    valid_from: Timestamp
    valid_until: Timestamp
    available_at: Timestamp
    commission_usd_per_100k: NonNegative
    slippage_per_lot_per_side: NonNegative
    commission_reserve_per_lot_per_side: NonNegative
    financing_reserve_per_lot: NonNegative
    rollover_convention: Literal["NEW_YORK_17_WEEKDAYS_EXPLICIT_MULTIPLIERS"]
    swap_days: tuple[SwapDay, ...] = Field(default=(), max_length=366)

    @model_validator(mode="after")
    def coverage(self):
        if not self.available_at <= self.valid_from < self.valid_until:
            raise ValueError("dated cost terms must be available before their effective window")
        if self.valid_until - self.valid_from > timedelta(days=366):
            raise ValueError("cost coverage exceeds one year")
        cutoffs = [s.cutoff for s in self.swap_days]
        if cutoffs != sorted(set(cutoffs)):
            raise ValueError("ordered unique rollover rows required")
        expected = []
        zone = ZoneInfo("America/New_York")
        day = self.valid_from.astimezone(zone).date()
        while day <= self.valid_until.astimezone(zone).date():
            cutoff = datetime.combine(day, time(17), zone)
            if day.weekday() < 5 and self.valid_from <= cutoff < self.valid_until:
                expected.append(cutoff)
            day += timedelta(days=1)
        if cutoffs != expected:
            raise ValueError("explicit rates/multipliers required for every covered rollover")
        debit_bound = max(
            sum(
                (max(Decimal(0), -getattr(s, side)) * s.multiplier for s in self.swap_days),
                Decimal(0),
            )
            for side in ("buy_usd_per_lot", "sell_usd_per_lot")
        )
        if self.financing_reserve_per_lot < debit_bound:
            raise ValueError("financing reserve cannot be smaller than covered debit exposure")
        return self

    def check_time(self, at):
        if not self.valid_from <= at < self.valid_until:
            raise ValueError("cost terms outside their effective window")

    def per_lot(self, spec, price):
        base_usd = price if spec.base == "EUR" else Decimal(1)
        value = commission(spec.contract_size, base_usd, self.commission_usd_per_100k, Decimal(1))
        if value > self.commission_reserve_per_lot_per_side:
            raise ValueError("observed commission exceeds declared risk reserve")
        return value

    def price_risk(self, market, at=None):
        self.check_time(at or market.at)
        if {s.symbol for s in market.instruments} != {self.symbol}:
            raise ValueError("cost profile must match the replay symbol")
        instruments = []
        for spec in market.instruments:
            q = market.quote_for(spec.symbol)
            adverse = self.slippage_per_lot_per_side / (
                spec.contract_size * market.conversion[spec.quote]
            )
            self.per_lot(spec, q.ask + adverse)
            instruments.append(
                spec.model_copy(
                    update={
                        "commission_per_lot": self.commission_reserve_per_lot_per_side,
                        "slippage_per_lot": 2 * self.slippage_per_lot_per_side,
                        "financing_per_lot": self.financing_reserve_per_lot,
                    }
                )
            )
        return Market.model_validate({**market.model_dump(), "instruments": tuple(instruments)})


class BrokerCostSimulator(Simulator):
    def __init__(self, store, capital, costs):
        if not isinstance(store, ReplayStore):
            raise ValueError("broker-cost simulator requires an ephemeral offline replay store")
        super().__init__(store, capital)
        if (
            self.book.deals
            or self.book.positions
            or self.book.orders
            or self.book.calls
            or self.book.cash_flows
            or self.book.balance != capital
            or self.book.initial_balance != capital
        ):
            raise ValueError("broker-cost replay cannot reset an existing execution ledger")
        self.costs = costs
        self.financing, self.fill_costs = [], []
        self.posted = set()

    def mutate(self, request, market):
        self.costs.check_time(self.store.clock.now())
        self.accrue(self.store.clock.now())
        return super().mutate(request, market)

    def fill_market(self, market, symbol, buy):
        if symbol != self.costs.symbol:
            raise ValueError("fill symbol differs from cost profile")
        self.costs.check_time(self.store.clock.now())
        spec, quote = market.spec_for(symbol), market.quote_for(symbol)
        shift = self.costs.slippage_per_lot_per_side / (
            spec.contract_size * market.conversion[spec.quote]
        )
        delta = shift if buy else -shift
        changed = quote.model_copy(update={"bid": quote.bid + delta, "ask": quote.ask + delta})
        price = changed.ask if buy else changed.bid
        fee = self.costs.per_lot(spec, price)
        return Market.model_validate(
            {
                **market.model_dump(),
                "quotes": tuple(changed if q.symbol == symbol else q for q in market.quotes),
                "instruments": tuple(
                    s.model_copy(update={"commission_per_lot": fee}) if s.symbol == symbol else s
                    for s in market.instruments
                ),
            }
        )

    def record_cost(self, request, market, result):
        if result.filled:
            spec, quote = market.spec_for(request.symbol), market.quote_for(request.symbol)
            self.fill_costs.append(
                {
                    "request_id": str(request.request_id),
                    "commission": str(self.book.deals[-1].commission),
                    "slippage": str(result.filled * self.costs.slippage_per_lot_per_side),
                    "half_spread": str(
                        (quote.ask - quote.bid)
                        / 2
                        * result.filled
                        * spec.contract_size
                        * market.conversion[spec.quote]
                    ),
                }
            )

    def _enter(self, request, market, fault):
        result = super()._enter(
            request, self.fill_market(market, request.symbol, request.side == "BUY"), fault
        )
        self.record_cost(request, market, result)
        return result

    def _manage(self, request, market):
        position = next(
            (p for p in self.book.positions if p.position_id == request.position_id), None
        )
        if request.action != "CLOSE" or position is None:
            return super()._manage(request, market)
        result = super()._manage(
            request, self.fill_market(market, request.symbol, position.side == "SELL")
        )
        self.record_cost(request, market, result)
        return result

    def accrue(self, at):
        """Rollover precedes same-time fills; open-at-cutoff entries pay next cutoff."""
        changed = False
        for row in self.costs.swap_days:
            if row.cutoff > at:
                break
            if row.cutoff in self.posted:
                continue
            for position in self.book.positions:
                if not position.volume:
                    continue
                entered = min(
                    d.at
                    for d in self.book.deals
                    if d.position_id == position.position_id and d.action == "ENTER"
                )
                if entered >= row.cutoff:
                    continue
                rate = row.buy_usd_per_lot if position.side == "BUY" else row.sell_usd_per_lot
                cash = position.volume * rate * row.multiplier
                posting = {
                    "position_id": str(position.position_id),
                    "cutoff": row.cutoff.isoformat(),
                    "posted_at": at.isoformat(),
                    "volume": str(position.volume),
                    "rate": str(rate),
                    "multiplier": row.multiplier,
                    "charge": str(-cash),
                    "evidence": row.evidence,
                }
                self.financing.append(posting)
                self.store._append({"stream": "financing", "event": "ROLLOVER", "posting": posting})
                self.book = self.book.model_copy(
                    update={
                        "balance": self.book.balance + cash,
                        "positions": tuple(
                            p.model_copy(update={"realized": p.realized + cash})
                            if p.position_id == position.position_id
                            else p
                            for p in self.book.positions
                        ),
                    }
                )
                self._save("ROLLOVER")
                changed = True
            self.posted.add(row.cutoff)
        return changed

    def settle_entry(self, *args, **kwargs):
        raise ValueError("deferred remainder settlement is outside broker-cost replay v1")
