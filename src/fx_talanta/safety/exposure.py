"""Reconciled open exposure plus unfilled reservations, in account currency."""

from decimal import Decimal
from typing import Literal

from fx_talanta.domain.models import FrozenModel, Hash, Identifier
from fx_talanta.safety.risk import Number, Positive

D = Decimal


class Position(FrozenModel):
    scope: Hash
    position_id: Identifier
    reservation_id: Identifier | None
    symbol: Literal["EURUSD", "USDJPY"]
    side: Literal["BUY", "SELL"]
    volume: Positive
    liquidation: Positive
    stop: Positive | None
    contract: Positive
    base_to_account: Positive
    quote_to_account: Positive
    exit_cost_per_lot: Number
    margin: Number
    owned: bool


class Reservation(FrozenModel):
    scope: Hash
    reservation_id: Identifier
    symbol: Literal["EURUSD", "USDJPY"]
    side: Literal["BUY", "SELL"]
    authorized_volume: Positive  # The admitted rounded allocation, not the original requested lot.
    cumulative_filled: Number
    pending_confirmed: Number
    final_order: bool
    outcome_unknown: bool
    risk_per_lot: Positive
    gross_per_lot: Positive
    counter_per_lot: Positive
    margin_per_lot: Positive


def aggregate(scope: str, positions: tuple[Position, ...], reservations: tuple[Reservation, ...]):
    risk = gross = margin = D(0)
    flags = 0
    currencies: dict[str, D] = {}
    slots, symbols, ids = set(), set(), set()
    by_id = {r.reservation_id: r for r in reservations}
    if len(by_id) != len(reservations):
        raise ValueError("duplicate reservation")

    def legs(symbol, side, base, counter):
        sign = 1 if side == "BUY" else -1
        for currency, amount in ((symbol[:3], sign * base), (symbol[3:], -sign * counter)):
            currencies[currency] = currencies.get(currency, D(0)) + amount

    for p in positions:
        if p.scope != scope or p.position_id in ids:
            raise ValueError("mixed account or duplicate position")
        ids.add(p.position_id)
        flags |= 0 if p.owned else 32
        if p.stop is None:
            flags |= 8
        else:
            distance = p.liquidation - p.stop if p.side == "BUY" else p.stop - p.liquidation
            risk += (
                max(D(0), distance) * p.contract * p.quote_to_account + p.exit_cost_per_lot
            ) * p.volume
        base = p.volume * p.contract * p.base_to_account
        counter = p.volume * p.contract * p.liquidation * p.quote_to_account
        gross += base
        margin += p.margin
        legs(p.symbol, p.side, base, counter)
        key = "r:" + p.reservation_id if p.reservation_id else "p:" + p.position_id
        slots.add(key)
        symbols.add(p.symbol)
        if p.reservation_id and p.reservation_id not in by_id:
            flags |= 4
    for r in reservations:
        if r.scope != scope or r.cumulative_filled + r.pending_confirmed > r.authorized_volume:
            raise ValueError("mixed account or allocation expanded")
        matched = [p for p in positions if p.reservation_id == r.reservation_id]
        if (
            any((p.symbol, p.side) != (r.symbol, r.side) for p in matched)
            or sum((p.volume for p in matched), D(0)) > r.cumulative_filled
        ):
            raise ValueError("fill/position mismatch")
        remaining = (
            r.pending_confirmed
            if r.final_order
            else max(r.pending_confirmed, r.authorized_volume - r.cumulative_filled)
        )
        flags |= 4 if r.outcome_unknown else 0
        risk += remaining * r.risk_per_lot
        gross += remaining * r.gross_per_lot
        margin += remaining * r.margin_per_lot
        legs(r.symbol, r.side, remaining * r.gross_per_lot, remaining * r.counter_per_lot)
        if remaining:
            slots.add("r:" + r.reservation_id)
            symbols.add(r.symbol)
    return {
        "risk": risk,
        "gross": gross,
        "margin": margin,
        "currencies": currencies,
        "occupied_slots": len(slots),
        "symbols": symbols,
        "flags": flags,
    }
