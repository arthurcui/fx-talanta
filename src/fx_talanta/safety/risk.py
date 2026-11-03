"""Independent Decimal governor for a reconciled, account-currency snapshot.

Inputs are trusted observations/pinned mandate, never model-supplied overrides.
The native implementation is separately authored in mql5/safety/Risk.mqh.
No binding is qualified by this arithmetic alone.
"""

from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from typing import Annotated, Literal

from pydantic import Field

from fx_talanta.domain.models import Amount, FrozenModel

D = Decimal
Number = Annotated[Amount, Field(ge=0, le=100000000)]
Signed = Annotated[Amount, Field(ge=-100000000, le=100000000)]
Positive = Annotated[Number, Field(gt=0)]
MICRO = D("0.000001")


class SafetyInput(FrozenModel):
    measured_at_ms: Annotated[int, Field(ge=0, le=9000000000000000)]
    symbol: Literal["EURUSD", "USDJPY"]
    currency: Literal["USD", "CAD"]
    side: Literal["BUY", "SELL"]
    bid: Positive
    ask: Positive
    stop: Positive
    benchmark: Positive
    maximum_spread: Positive
    maximum_adverse: Number
    usd_to_account: Number
    base_to_account: Number
    quote_to_account: Number
    cost_to_account: Number
    commission_currency: Literal["USD", "CAD"]
    conversion_age_ms: Annotated[int, Field(ge=-100000000, le=100000000)]
    quote_age_ms: Annotated[int, Field(ge=-100000000, le=100000000)]
    clock_error_ms: Annotated[int, Field(ge=0, le=100000000)]
    expires_in_ms: Annotated[int, Field(ge=-100000000, le=100000000)]
    inputs_ok: bool
    blackout: bool
    session_open: bool
    # HARD=1 LOSS=2 UNKNOWN=4 PROTECTION=8 STARTUP=16 DEGRADED=32 OWNER=64.
    flags: Annotated[int, Field(ge=0, le=127)]
    occupied_slots: Annotated[int, Field(ge=0, le=1000000)]
    symbol_occupied: bool
    cashflows_known: bool
    equity: Positive
    capital: Positive
    day_start: Positive
    day_loss: Number
    commission: Number
    slippage: Number
    financing: Number
    contract: Positive
    tick_size: Positive
    tick_value_loss: Positive
    broker_loss_per_lot: Number
    broker_margin_per_lot: Positive
    minimum: Positive
    step: Positive
    maximum: Positive
    request_volume: Positive
    request_risk: Positive
    existing_risk: Number
    existing_gross: Number
    existing_margin: Number
    base_exposure: Signed
    quote_exposure: Signed
    other_exposure: Number
    stress_loss: Number
    stopout_ratio: Positive


def up(value: D) -> D:
    return (value + D("0.0000001")).quantize(MICRO, rounding=ROUND_CEILING)


def down(value: D) -> D:
    return (value - D("0.0000001")).quantize(MICRO, rounding=ROUND_FLOOR)


def state_reason(flags: int) -> str | None:
    for bit, reason in (
        (1, "HARD_HALT"),
        (2, "LOSS_PAUSE"),
        (4, "OUTCOME_UNKNOWN"),
        (8, "PROTECTION_PENDING"),
        (16, "STARTUP_RECONCILE"),
        (32, "DEGRADED_PROTECT"),
        (64, "OWNER_PAUSED"),
    ):
        if flags & bit:
            return reason
    return None


def evaluate(v: SafetyInput) -> dict[str, str]:
    """Return an upper bound only. Current-to-stop risk includes reserved remainder.

    Existing exposure must include ALL positions (also external/unowned), pending,
    submitting and unknown work exactly once. Unknown/unprotected exposure blocks
    via flags. Loss accounting and single-writer fencing are separate prerequisites.
    """

    def hold(reason):
        return {"reason": reason}

    reason = state_reason(v.flags)
    if reason:
        return hold(reason)
    if not v.cashflows_known:
        return hold("UNKNOWN_CASHFLOW")
    if not v.inputs_ok:
        return hold("REQUIRED_INPUTS")
    if v.blackout or not v.session_open:
        return hold("BLACKOUT_OR_SESSION")
    if v.clock_error_ms > 100:
        return hold("CLOCK_UNVERIFIED")
    if v.expires_in_ms <= v.clock_error_ms:
        return hold("EXPIRED")
    if not v.clock_error_ms <= v.quote_age_ms <= 2000 - v.clock_error_ms:
        return hold("QUOTE_STALE")
    if not v.clock_error_ms <= v.conversion_age_ms <= 2000 - v.clock_error_ms:
        return hold("CONVERSION_STALE")
    if not all((v.usd_to_account, v.base_to_account, v.quote_to_account, v.cost_to_account)):
        return hold("CONVERSION_MISSING")
    base = v.bid * v.usd_to_account if v.symbol == "EURUSD" else v.usd_to_account
    quote = v.usd_to_account if v.symbol == "EURUSD" else v.usd_to_account / v.bid
    cost = v.usd_to_account if v.commission_currency == "USD" else D(1)
    if (
        (v.currency == "USD" and (v.usd_to_account != 1 or v.commission_currency != "USD"))
        or abs(base - v.base_to_account) > D("0.000000000001")
        or abs(quote - v.quote_to_account) > D("0.000000000001")
        or v.cost_to_account != cost
    ):
        return hold("CONVERSION_INCONSISTENT")
    buy = v.side == "BUY"
    price = v.ask if buy else v.bid
    if (
        v.bid > v.ask
        or not (v.stop < v.bid if buy else v.stop > v.ask)
        or v.minimum > v.maximum
        or v.minimum % v.step
        or v.step < D("0.00000001")
        or v.step % D("0.00000001")
        or v.maximum / v.step > 1000000
        or v.stop % v.tick_size
        or any(
            x % D("0.00000001")
            for x in (
                v.bid,
                v.ask,
                v.stop,
                v.benchmark,
                v.maximum_spread,
                v.maximum_adverse,
                v.tick_size,
            )
        )
    ):
        return hold("INVALID_SPECIFICATION")
    adverse = price - v.benchmark if buy else v.benchmark - price
    if v.ask - v.bid > v.maximum_spread or adverse > v.maximum_adverse:
        return hold("COST_LIMIT")
    if v.occupied_slots >= 2 or v.symbol_occupied:
        return hold("POSITION_LIMIT")
    if v.day_loss >= v.day_start * D("0.01"):
        return hold("LOSS_PAUSE")
    distance = abs(price - v.stop)
    # The larger independent estimate wins; fee conversion is explicit and fresh.
    risk = up(
        max(
            distance * v.contract * v.quote_to_account,
            distance / v.tick_size * v.tick_value_loss,
            v.broker_loss_per_lot,
        )
        + (2 * v.commission + v.slippage + v.financing) * v.cost_to_account
    )
    raw_base = v.contract * v.base_to_account
    raw_counter = v.contract * price * v.quote_to_account
    gross = up(raw_base)
    counter = up(raw_counter)
    charge = up(
        (v.ask - v.bid) * v.contract * v.quote_to_account + v.commission * v.cost_to_account
    )
    margin = up(v.broker_margin_per_lot)
    if max(risk, gross, counter, charge, margin) > 100000000:
        return hold("ARITHMETIC_RANGE")
    eligible = min(v.equity, v.capital)
    sign = D(1) if buy else D(-1)

    def allowed(volume):
        r, g, m = up(volume * risk), up(volume * gross), up(volume * margin)
        capacity = down(eligible - up(volume * charge))
        total_risk = v.existing_risk + r
        return (
            r <= down(capacity * D("0.0025"))
            and r <= v.request_risk
            and total_risk <= down(capacity * D("0.005"))
            and total_risk + v.day_loss <= down(v.day_start * D("0.01"))
            and v.existing_gross + g <= down(capacity * 2)
            and v.existing_margin + m <= down(capacity * D("0.20"))
            and capacity - max(total_risk, v.stress_loss)
            > up((v.existing_margin + m) * v.stopout_ratio)
            and up(abs(v.base_exposure + sign * volume * raw_base)) <= capacity
            and up(abs(v.quote_exposure - sign * volume * raw_counter)) <= capacity
            and v.other_exposure <= capacity
        )

    # Upper bounds shrink the bounded grid scan. Scan permits a feasible interval
    # with a nonzero lower bound when an existing currency leg is being reduced.
    upper = min(
        v.maximum,
        v.request_volume,
        eligible * D("0.0025") / risk,
        v.request_risk / risk,
        eligible * 2 / gross,
        eligible * D("0.20") / margin,
    )
    units = int(upper / v.step)
    minimum_units = int(v.minimum / v.step)
    for n in range(units, minimum_units - 1, -1):
        if units - n >= 4096:
            return hold("COMPUTE_BUDGET")
        volume = n * v.step
        if allowed(volume):
            return {
                "reason": "ACCEPTED",
                "volume": format(volume, "f"),
                "risk": format(up(volume * risk), "f"),
                "gross": format(up(volume * gross), "f"),
                "margin": format(up(volume * margin), "f"),
            }
    return hold("MINIMUM_LOT")
