"""Persistent offline broker. No network broker SDK and no real execution venue."""

from decimal import ROUND_FLOOR, Decimal
from uuid import UUID, uuid5

from fx_talanta.domain.offline import (
    BrokerBook,
    BrokerOrder,
    BrokerRequest,
    CashFlow,
    Deal,
    Fault,
    Market,
    Position,
)
from fx_talanta.risk.governor import equity
from fx_talanta.storage.offline import OfflineStore
from fx_talanta.storage.repository import AccountMismatch

ZERO = Decimal("0")


class UncertainOutcome(TimeoutError):
    pass


class Simulator:
    def __init__(self, store: OfflineStore, initial_balance: Decimal):
        self.store = store
        self.book = store.load("broker")
        if self.book is None:
            self.book = BrokerBook(
                account=store.account, initial_balance=initial_balance, balance=initial_balance
            )
            self._save("INITIALIZED")
        self.next_fault = Fault()
        self.connected = True
        self.history_visible = True

    def _save(self, event: str):
        self.store.save("broker", self.book, event)

    def _available(self):
        self.store.assert_owner()
        if not self.connected:
            raise UncertainOutcome("simulated broker disconnected")

    def snapshot(self) -> BrokerBook:
        self._available()
        return self.book

    def lookup(self, request_id: UUID) -> BrokerOrder | None:
        self._available()
        if not self.history_visible:
            raise UncertainOutcome("simulated history unavailable")
        return next((o for o in self.book.orders if o.request.request_id == request_id), None)

    def mutate(self, request: BrokerRequest, market: Market) -> BrokerOrder:
        self._available()
        if request.account != self.book.account or request.account != self.store.account:
            raise AccountMismatch("broker request account mismatch")
        # Deliberately NOT broker-idempotent: resending an entry is an error. Gateway
        # must reconcile; this simulator cannot hide duplicate-send bugs.
        if any(o.request.request_id == request.request_id for o in self.book.orders):
            raise RuntimeError("duplicate broker submission")
        fault, self.next_fault = self.next_fault, Fault()
        self.book = self.book.model_copy(update={"calls": self.book.calls + (request.request_id,)})
        self._save("CALL_RECEIVED")
        if fault.kind == "TIMEOUT_BEFORE":
            raise UncertainOutcome("request receipt unknown; no result evidence")
        order = BrokerOrder(request=request, state="REJECTED", reason="simulated rejection")
        if not market.session_open:
            order = order.model_copy(update={"reason": "market closed"})
        elif fault.kind != "REJECT":
            if request.action == "ENTER":
                order = self._enter(request, market, fault)
            else:
                order = self._manage(request, market)
        self.book = self.book.model_copy(update={"orders": self.book.orders + (order,)})
        self._save("REQUEST_" + order.state)
        if fault.kind == "LOST_RESPONSE":
            raise UncertainOutcome("response lost after broker mutation committed")
        return order

    def _enter(self, request: BrokerRequest, market: Market, fault: Fault) -> BrokerOrder:
        spec, q = market.spec_for(request.symbol), market.quote_for(request.symbol)
        if (
            request.volume < spec.minimum_volume
            or request.volume > spec.maximum_volume
            or request.volume % spec.volume_step
        ):
            return BrokerOrder(request=request, state="REJECTED", reason="invalid volume")
        if any(p.symbol == request.symbol and p.volume for p in self.book.positions):
            return BrokerOrder(request=request, state="REJECTED", reason="position exists")
        if fault.kind == "ACK_ONLY":
            return BrokerOrder(request=request, state="ACKNOWLEDGED", remaining=request.volume)
        volume = request.volume
        if fault.kind == "PARTIAL":
            volume = (volume * fault.fraction / spec.volume_step).to_integral_value(
                rounding=ROUND_FLOOR
            ) * spec.volume_step
        if volume == 0:
            return BrokerOrder(request=request, state="ACKNOWLEDGED", remaining=request.volume)
        price = (q.ask if request.side == "BUY" else q.bid) + fault.price_delta
        if price <= 0:
            raise ValueError("invalid simulated fill price")
        position_id = uuid5(request.entry_id, "position")
        commission = volume * spec.commission_per_lot
        position = Position(
            position_id=position_id,
            entry_id=request.entry_id,
            symbol=request.symbol,
            side=request.side,
            volume=volume,
            price=price,
            stop=request.stop if request.initial_stop and fault.kind != "NO_STOP" else None,
            target=request.target,
            entry_cost=commission,
            realized=-commission,
        )
        deal = Deal(
            deal_id=uuid5(request.request_id, "entry-fill"),
            request_id=request.request_id,
            position_id=position_id,
            action="ENTER",
            volume=volume,
            price=price,
            commission=commission,
            realized=-commission,
            at=self.store.clock.now(),
        )
        self.book = self.book.model_copy(
            update={
                "balance": self.book.balance - commission,
                "positions": self.book.positions + (position,),
                "deals": self.book.deals + (deal,),
            }
        )
        return BrokerOrder(
            request=request,
            state="FILLED" if volume == request.volume else "PARTIALLY_FILLED",
            filled=volume,
            remaining=request.volume - volume,
        )

    def _manage(self, request: BrokerRequest, market: Market) -> BrokerOrder:
        def reject(reason):
            return BrokerOrder(request=request, state="REJECTED", reason=reason)

        if request.action == "CANCEL":
            original = next(
                (o for o in self.book.orders if o.request.request_id == request.entry_id), None
            )
            if original is None:
                return reject("no known entry to cancel")
            self.book = self.book.model_copy(
                update={
                    "orders": tuple(
                        o.model_copy(update={"state": "CANCELLED", "remaining": ZERO})
                        if o == original
                        else o
                        for o in self.book.orders
                    )
                }
            )
            return BrokerOrder(request=request, state="FILLED")
        position = next(
            (p for p in self.book.positions if p.position_id == request.position_id), None
        )
        if (
            position is None
            or not position.owned
            or not position.volume
            or position.version != request.expected_version
            or position.entry_id != request.entry_id
        ):
            return reject("unowned, closed or stale position")
        spec, q = market.spec_for(position.symbol), market.quote_for(position.symbol)
        if request.symbol != position.symbol:
            return reject("wrong position symbol")
        if request.action == "TIGHTEN_STOP":
            stop = request.stop
            if stop is None:
                return reject("stop removal forbidden")
            distance = q.bid - stop if position.side == "BUY" else stop - q.ask
            if distance < spec.minimum_stop:
                return reject("invalid stop distance")
            if position.stop and (
                (position.side == "BUY" and stop < position.stop)
                or (position.side == "SELL" and stop > position.stop)
            ):
                return reject("stop widening forbidden")
            updated = position.model_copy(update={"stop": stop, "version": position.version + 1})
        else:
            if (
                request.volume <= 0
                or request.volume > position.volume
                or request.volume % spec.volume_step
            ):
                return reject("invalid close volume; reversal forbidden")
            price = q.bid if position.side == "BUY" else q.ask
            difference = (
                price - position.price if position.side == "BUY" else position.price - price
            )
            commission = request.volume * spec.commission_per_lot
            pnl = (
                difference * request.volume * spec.contract_size * market.conversion[spec.quote]
                - commission
            )
            updated = position.model_copy(
                update={
                    "volume": position.volume - request.volume,
                    "version": position.version + 1,
                    "realized": position.realized + pnl,
                }
            )
            deal = Deal(
                deal_id=uuid5(request.request_id, "close-fill"),
                request_id=request.request_id,
                position_id=position.position_id,
                action="CLOSE",
                volume=request.volume,
                price=price,
                commission=commission,
                realized=pnl,
                at=self.store.clock.now(),
            )
            self.book = self.book.model_copy(
                update={"balance": self.book.balance + pnl, "deals": self.book.deals + (deal,)}
            )
        self.book = self.book.model_copy(
            update={
                "positions": tuple(
                    updated if p.position_id == updated.position_id else p
                    for p in self.book.positions
                )
            }
        )
        return BrokerOrder(request=request, state="FILLED", filled=request.volume)

    def cash_flow(self, amount: Decimal, market: Market, flow_id: UUID, *, classified=True):
        """Fixture-only external cash movement, with pre-flow equity retained for NAV."""
        self._available()
        if any(f.flow_id == flow_id for f in self.book.cash_flows):
            raise ValueError("duplicate cash flow")
        flow = CashFlow(
            flow_id=flow_id,
            amount=amount,
            equity_before=equity(self.book, market),
            at=self.store.clock.now(),
            classified=classified,
        )
        self.book = self.book.model_copy(
            update={
                "balance": self.book.balance + amount,
                "cash_flows": self.book.cash_flows + (flow,),
            }
        )
        self._save("CASH_FLOW")

    def settle_entry(self, request_id: UUID, market: Market):
        """Venue fixture: a previously acknowledged/partial order fills its remainder."""
        self._available()
        original = self.lookup(request_id)
        if original is None or not original.remaining:
            raise ValueError("no pending remainder")
        request = original.request
        position = next((p for p in self.book.positions if p.entry_id == request.entry_id), None)
        if position is None:
            filled = self._enter(request, market, Fault())
        else:
            spec, quote = market.spec_for(request.symbol), market.quote_for(request.symbol)
            price = quote.ask if request.side == "BUY" else quote.bid
            amount = original.remaining
            fee = amount * spec.commission_per_lot
            volume = position.volume + amount
            updated = position.model_copy(
                update={
                    "price": (position.price * position.volume + price * amount) / volume,
                    "volume": volume,
                    "entry_cost": position.entry_cost + fee,
                    "realized": position.realized - fee,
                    "version": position.version + 1,
                }
            )
            deal = Deal(
                deal_id=uuid5(request_id, "remaining-fill"),
                request_id=request_id,
                position_id=position.position_id,
                action="ENTER",
                volume=amount,
                price=price,
                commission=fee,
                realized=-fee,
                at=self.store.clock.now(),
            )
            self.book = self.book.model_copy(
                update={
                    "balance": self.book.balance - fee,
                    "positions": tuple(
                        updated if p == position else p for p in self.book.positions
                    ),
                    "deals": self.book.deals + (deal,),
                }
            )
            filled = original.model_copy(
                update={"state": "FILLED", "filled": request.volume, "remaining": ZERO}
            )
        self.book = self.book.model_copy(
            update={"orders": tuple(filled if o == original else o for o in self.book.orders)}
        )
        self._save("REMAINDER_FILLED")

    def confirm_not_executed(self, request: BrokerRequest):
        """Explicit synthetic broker evidence, unlike an empty history lookup."""
        self._available()
        if request.account != self.book.account or self.lookup(request.request_id) is not None:
            raise ValueError("invalid non-execution attestation")
        rejected = BrokerOrder(
            request=request, state="REJECTED", reason="venue confirmed not executed"
        )
        self.book = self.book.model_copy(update={"orders": self.book.orders + (rejected,)})
        self._save("CONFIRMED_NOT_EXECUTED")

    def inject_position(self, position: Position):
        """Fixture of external activity; never exposed to the decision source."""
        self._available()
        self.book = self.book.model_copy(update={"positions": self.book.positions + (position,)})
        self._save("EXTERNAL_POSITION")
