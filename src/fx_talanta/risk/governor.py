"""All limits use USD equity and independently valued currency legs."""

from datetime import datetime
from decimal import ROUND_FLOOR, Decimal

from fx_talanta.domain.offline import (
    BrokerBook,
    Entry,
    EntryIntent,
    LossLedger,
    Market,
    Policy,
    Reservation,
)

ZERO = Decimal("0")


def equity(book: BrokerBook, market: Market) -> Decimal:
    value = book.balance
    for p in book.positions:
        q, spec = market.quote_for(p.symbol), market.spec_for(p.symbol)
        liquidation = q.bid if p.side == "BUY" else q.ask
        signed = liquidation - p.price if p.side == "BUY" else p.price - liquidation
        value += signed * p.volume * spec.contract_size * market.conversion[spec.quote]
    return value


def losses(
    previous: LossLedger | None, book: BrokerBook, market: Market, policy: Policy, now: datetime
) -> LossLedger:
    current = equity(book, market)
    total_flows = sum((f.amount for f in book.cash_flows), ZERO)
    old = previous or LossLedger(
        day=now.date(),
        start_equity=book.initial_balance,
        day_flow_base=ZERO,
        units=book.initial_balance,
    )
    data = old.model_dump()
    units, high = old.units, old.high_water_nav
    processed = list(old.processed_flows)
    for flow in book.cash_flows:
        if flow.flow_id in processed:
            continue
        nav = flow.equity_before / units
        high = max(high, nav)
        if nav <= high * (1 - policy.drawdown_fraction):
            data["hard_halt"] = True
        units += flow.amount / nav
        if units <= 0:
            data["hard_halt"] = True
            units = old.units
        processed.append(flow.flow_id)
    nav = current / units
    high = max(high, nav)
    if nav <= high * (1 - policy.drawdown_fraction) or current <= 0:
        data["hard_halt"] = True
    if now.date() > old.day:
        # Reconciled first snapshot of the new UTC risk day, never a process restart.
        data.update(day=now.date(), start_equity=current, day_flow_base=total_flows)
    day_loss = max(ZERO, data["start_equity"] + total_flows - data["day_flow_base"] - current)
    if day_loss >= data["start_equity"] * policy.daily_fraction:
        data["loss_pause_day"] = now.date()
    data.update(
        units=units, high_water_nav=high, processed_flows=tuple(processed), day_loss=day_loss
    )
    return LossLedger(**data)


def health_reason(market: Market, now: datetime, policy: Policy) -> str | None:
    if not market.calendar_ok or not market.news_ok:
        return "required input coverage unavailable"
    if not market.session_open or market.event_blackout:
        return "session closed or scheduled-event blackout"
    if not 0 <= (now - market.at).total_seconds() <= policy.quote_age_seconds:
        return "stale or future conversion snapshot"
    if any(
        not 0 <= (now - q.at).total_seconds() <= policy.quote_age_seconds for q in market.quotes
    ):
        return "stale or future quote"
    return None


def exposure(book: BrokerBook, entries: tuple[Entry, ...], market: Market):
    risk, gross, margin = ZERO, ZERO, ZERO
    currencies: dict[str, Decimal] = {}
    symbols: set[str] = set()
    for p in book.positions:
        if not p.volume:
            continue
        spec, quote = market.spec_for(p.symbol), market.quote_for(p.symbol)
        symbols.add(p.symbol)
        if p.stop is None:
            return None  # Cannot size new risk while any position is unprotected.
        liquidation = quote.bid if p.side == "BUY" else quote.ask
        distance = liquidation - p.stop if p.side == "BUY" else p.stop - liquidation
        risk += (
            max(ZERO, distance) * spec.contract_size * market.conversion[spec.quote]
            + spec.commission_per_lot
            + spec.slippage_per_lot
            + spec.financing_per_lot
        ) * p.volume
        base = p.volume * spec.contract_size * market.conversion[spec.base]
        counter = p.volume * spec.contract_size * liquidation * market.conversion[spec.quote]
        gross += base
        margin += base * spec.margin_rate
        sign = 1 if p.side == "BUY" else -1
        currencies[spec.base] = currencies.get(spec.base, ZERO) + sign * base
        currencies[spec.quote] = currencies.get(spec.quote, ZERO) - sign * counter
    for entry in entries:
        r = entry.reservation
        if r and r.volume:
            symbols.add(entry.intent.symbol)
            risk += r.volume * r.risk_per_lot
            gross += r.volume * r.gross_per_lot
            margin += r.volume * r.margin_per_lot
            for currency, value in r.currency_per_lot.items():
                currencies[currency] = currencies.get(currency, ZERO) + r.volume * value
    return risk, gross, margin, currencies, symbols


def size(
    intent: EntryIntent,
    book: BrokerBook,
    entries: tuple[Entry, ...],
    market: Market,
    policy: Policy,
    ledger: LossLedger,
    now: datetime,
) -> tuple[Reservation | None, str]:
    reason = health_reason(market, now, policy)
    if reason:
        return None, reason
    if intent.expires_at <= now or intent.exit_at <= now:
        return None, "intent expired or exit cutoff reached"
    if intent.policy_version != policy.version:
        return None, "policy version mismatch"
    if any(not f.classified for f in book.cash_flows):
        return None, "unclassified cash movement"
    spec, q = market.spec_for(intent.symbol), market.quote_for(intent.symbol)
    price = q.ask if intent.side == "BUY" else q.bid
    distance = price - intent.stop if intent.side == "BUY" else intent.stop - price
    protection_distance = q.bid - intent.stop if intent.side == "BUY" else intent.stop - q.ask
    target_distance = intent.target - price if intent.side == "BUY" else price - intent.target
    adverse = price - intent.benchmark if intent.side == "BUY" else intent.benchmark - price
    if protection_distance < spec.minimum_stop or target_distance <= 0:
        return None, "invalid protective stop or target"
    if q.ask - q.bid > spec.maximum_spread or adverse > spec.maximum_adverse_move:
        return None, "spread or adverse price movement exceeds policy"
    used = exposure(book, entries, market)
    if used is None:
        return None, "unprotected position"
    risk, gross, margin, currencies, symbols = used
    if intent.symbol in symbols or len(symbols) >= policy.maximum_positions:
        return None, "position slot occupied"
    eligible = min(equity(book, market), policy.capital)
    if eligible <= 0 or ledger.hard_halt or ledger.loss_pause_day == now.date():
        return None, "loss mandate blocks entry"
    per_lot = (
        distance * spec.contract_size * market.conversion[spec.quote]
        + 2 * spec.commission_per_lot
        + spec.slippage_per_lot
        + spec.financing_per_lot
    )
    base = spec.contract_size * market.conversion[spec.base]
    counter = spec.contract_size * price * market.conversion[spec.quote]
    sign = 1 if intent.side == "BUY" else -1
    legs = {spec.base: sign * base, spec.quote: -sign * counter}
    # Entry commission and marking to liquidation immediately lower equity.
    # Reserve headroom instead of sizing exactly to an equity-dependent cap.
    equity_charge = (q.ask - q.bid) * spec.contract_size * market.conversion[
        spec.quote
    ] + spec.commission_per_lot
    daily_remaining = ledger.start_equity * policy.daily_fraction - ledger.day_loss - risk
    upper = min(
        spec.maximum_volume,
        eligible * policy.trade_fraction / (per_lot + policy.trade_fraction * equity_charge),
        (eligible * policy.aggregate_fraction - risk)
        / (per_lot + policy.aggregate_fraction * equity_charge),
        daily_remaining / per_lot,
        (eligible * policy.gross_multiple - gross) / (base + policy.gross_multiple * equity_charge),
        (eligible * policy.margin_fraction - margin)
        / (base * spec.margin_rate + policy.margin_fraction * equity_charge),
    )
    lower = ZERO
    cap = max(ZERO, eligible - max(ZERO, upper) * equity_charge) * policy.currency_multiple
    for currency in currencies.keys() | legs.keys():
        current, delta = currencies.get(currency, ZERO), legs.get(currency, ZERO)
        if not delta:
            if abs(current) > cap:
                return None, "existing currency exposure exceeds mandate"
            continue
        bounds = sorted(((-cap - current) / delta, (cap - current) / delta))
        lower, upper = max(lower, bounds[0]), min(upper, bounds[1])
    volume = (max(ZERO, upper) / spec.volume_step).to_integral_value(
        rounding=ROUND_FLOOR
    ) * spec.volume_step
    if volume < spec.minimum_volume or volume < lower:
        return None, "minimum lot exceeds an applicable risk limit"
    return Reservation(
        volume=volume,
        risk_per_lot=per_lot,
        gross_per_lot=base,
        margin_per_lot=base * spec.margin_rate,
        currency_per_lot=legs,
    ), "approved"
