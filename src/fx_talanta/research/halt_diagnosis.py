"""Bounded, simulator-only reconstruction of a retained risk checkpoint."""

from datetime import datetime
from decimal import Decimal, localcontext
from uuid import UUID, uuid4

from fx_talanta.clock import FakeClock
from fx_talanta.domain.models import Record
from fx_talanta.domain.offline import BrokerBook, GatewayBook, Market
from fx_talanta.gateway.offline import Gateway
from fx_talanta.research.replay import Costs, CostSimulator
from fx_talanta.risk.governor import equity, exposure


def measure(book, broker, market):
    eligible = min(equity(broker, market), book.policy.capital)
    used = exposure(broker, book.entries, market)
    if used is None:
        raise ValueError("unprotected position; cannot diagnose bounded stop risk")
    positions = []
    for position in broker.positions:
        if not position.volume:
            continue
        quote, spec = market.quote_for(position.symbol), market.spec_for(position.symbol)
        liquidation = quote.bid if position.side == "BUY" else quote.ask
        sign = Decimal(1) if position.side == "BUY" else Decimal(-1)
        unit = position.volume * spec.contract_size * market.conversion[spec.quote]
        pnl = sign * (liquidation - position.price) * unit
        entry_stop = sign * (position.price - position.stop) * unit
        giveback = max(Decimal(0), sign * (liquidation - position.stop)) * unit
        exit_costs = (
            spec.commission_per_lot + spec.slippage_per_lot + spec.financing_per_lot
        ) * position.volume
        positions.append(
            dict(
                symbol=position.symbol,
                side=position.side,
                volume=str(position.volume),
                entry_to_stop_loss=str(entry_stop),
                unrealized_pnl=str(pnl),
                current_to_stop_loss=str(giveback),
                incremental_exit_buffer=str(exit_costs),
                aggregate_contribution=str(giveback + exit_costs),
            )
        )
    pending = sum(
        (e.reservation.volume * e.reservation.risk_per_lot for e in book.entries if e.reservation),
        Decimal(0),
    )
    return dict(
        equity=str(equity(broker, market)),
        balance=str(broker.balance),
        eligible_equity=str(eligible),
        aggregate_fraction=str(book.policy.aggregate_fraction),
        aggregate_limit=str(eligible * book.policy.aggregate_fraction),
        aggregate_risk=str(used[0]),
        excess=str(used[0] - eligible * book.policy.aggregate_fraction),
        pending_reservation_risk=str(pending),
        positions=positions,
    )


def reproduce(checkpoint, costs):
    """Two retained historical quotes, then a repeated-quote latch check; no new entries."""
    book = GatewayBook.model_validate(checkpoint["gateway"])
    broker = BrokerBook.model_validate(checkpoint["broker"])
    if book.integrity_halt or broker.account != book.account:
        raise ValueError("unhalted matching simulator checkpoint required")
    costs = Costs.model_validate(costs)
    before = Market.model_validate(checkpoint["previous_market"])
    trigger = Market.model_validate(checkpoint["market"])
    first, second = map(datetime.fromisoformat, (checkpoint["previous_at"], checkpoint["at"]))
    if not first < second or (second - first).total_seconds() > 5:
        raise ValueError("targeted replay requires adjacent fresh checkpoint observations")
    clock = FakeClock(first)
    gateway = Gateway.for_replay(book.account, uuid4(), clock, book.policy)
    try:
        gateway.book = book
        gateway.store.records = {
            UUID(r["record_id"]): Record.model_validate(r) for r in checkpoint["records"]
        }
        gateway.store.books["broker"] = broker
        gateway.broker = CostSimulator(gateway.store, book.policy.capital, costs)
        with localcontext() as context:
            context.prec = 34
            preceding = measure(book, broker, before)
            crossing = measure(book, broker, trigger)
            gateway.reconcile(before)
            if gateway.book.integrity_halt:
                raise ValueError("preceding checkpoint already breaches policy")
            clock.advance(second - first)
            gateway.reconcile(trigger)
            if not gateway.book.integrity_halt or not hasattr(gateway, "integrity_breach"):
                raise ValueError("targeted replay did not reproduce a measured breach")
            breach = gateway.integrity_breach
            after = gateway.broker.book
            new_deals = after.deals[len(broker.deals) :]
            gateway.reconcile(trigger)
            if gateway.book.state != "HARD_HALT" or gateway.book.policy != book.policy:
                raise ValueError("halt latch or policy changed")
            if any(p.volume for p in gateway.broker.book.positions):
                raise ValueError("protective close incomplete")
            return dict(
                previous_at=first.isoformat(),
                trigger_at=second.isoformat(),
                historical_observations=2,
                elapsed_seconds=(second - first).total_seconds(),
                before=preceding,
                trigger=crossing,
                breach=breach,
                new_deals=[d.model_dump(mode="json") for d in new_deals],
                final_balance=str(after.balance),
                final_state=gateway.book.state,
                remaining_positions=0,
                policy_unchanged=True,
                repeated_quote_stays_halted=True,
                execution_enabled=False,
            )
    finally:
        gateway.close()
