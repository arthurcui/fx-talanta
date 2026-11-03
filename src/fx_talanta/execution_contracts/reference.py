"""Small BUY-only USD/CAD fixture calculator, not an execution risk governor.

All monetary limits/costs are in the named account currency. Fixed fractions
match the M0B defaults. Production conversion sourcing/rounding is M2C work.
"""

from decimal import ROUND_FLOOR, Decimal
from typing import Literal

from fx_talanta.domain.ea_protocol import Money, NonNegative, Positive, decimal_text
from fx_talanta.domain.models import FrozenModel

D = Decimal


class RiskVector(FrozenModel):
    symbol: Literal["EURUSD", "USDJPY"]
    currency: Literal["USD", "CAD"]
    bid: Positive
    ask: Positive
    stop: Positive
    usd_to_account: Positive | None
    base_to_account: Positive | None
    quote_to_account: Positive | None
    conversion_age: Money
    equity: Positive
    capital: Positive
    commission: NonNegative
    slippage: NonNegative
    financing: NonNegative = D(0)
    minimum: Positive = D("0.01")
    step: Positive = D("0.01")
    maximum: Positive = D("100")
    existing_risk: NonNegative = D(0)
    existing_gross: NonNegative = D(0)
    existing_margin: NonNegative = D(0)
    base_exposure: Money = D(0)
    quote_exposure: Money = D(0)
    day_start: Positive
    day_loss: NonNegative = D(0)
    high_water_equity: Positive
    hard_halt: bool = False
    cashflows_known: bool = True


def calculate(v: RiskVector):
    if not all((v.usd_to_account, v.base_to_account, v.quote_to_account)):
        return {"reason": "CONVERSION_MISSING"}
    if not 0 <= v.conversion_age <= 2:
        return {"reason": "CONVERSION_STALE"}
    if v.currency == "USD" and v.usd_to_account != 1:
        return {"reason": "CONVERSION_INCONSISTENT"}
    expected_base = v.bid * v.usd_to_account if v.symbol == "EURUSD" else v.usd_to_account
    expected_quote = v.usd_to_account if v.symbol == "EURUSD" else v.usd_to_account / v.bid
    if abs(v.base_to_account - expected_base) > D("0.000000000001") or abs(
        v.quote_to_account - expected_quote
    ) > D("0.000000000001"):
        return {"reason": "CONVERSION_INCONSISTENT"}
    if not v.stop < v.bid <= v.ask or v.minimum > v.maximum or v.minimum % v.step:
        return {"reason": "INVALID_SPECIFICATION"}
    if not v.cashflows_known:
        return {"reason": "UNKNOWN_CASHFLOW"}
    if v.hard_halt or v.equity <= v.high_water_equity * D("0.95"):
        return {"reason": "LOSS_BLOCK"}
    eligible = min(v.equity, v.capital)
    risk = (
        (v.ask - v.stop) * 100000 * v.quote_to_account + 2 * v.commission + v.slippage + v.financing
    )
    base = 100000 * v.base_to_account
    quote = 100000 * v.ask * v.quote_to_account
    charge = (v.ask - v.bid) * 100000 * v.quote_to_account + v.commission
    daily = v.day_start * D("0.01") - v.day_loss - v.existing_risk
    upper = min(
        v.maximum,
        eligible * D("0.0025") / (risk + D("0.0025") * charge),
        (eligible * D("0.005") - v.existing_risk) / (risk + D("0.005") * charge),
        daily / risk,
        (eligible * 2 - v.existing_gross) / (base + 2 * charge),
        (eligible * D("0.20") - v.existing_margin) / (base * D("0.02") + D("0.20") * charge),
    )
    cap = max(D(0), eligible - max(D(0), upper) * charge)
    lower = D(0)
    for existing, leg in ((v.base_exposure, base), (v.quote_exposure, -quote)):
        bounds = sorted(((-cap - existing) / leg, (cap - existing) / leg))
        lower, upper = max(lower, bounds[0]), min(upper, bounds[1])
    volume = (upper / v.step).to_integral_value(rounding=ROUND_FLOOR) * v.step
    if volume < max(v.minimum, lower):
        return {"reason": "MINIMUM_LOT"}
    # Reference report precision is six decimals; sizing always uses exact Decimal.
    return {
        "reason": "ACCEPTED",
        **{
            name: decimal_text(value.quantize(D("0.000001")))
            for name, value in {
                "volume": volume,
                "risk": volume * risk,
                "gross": volume * base,
                "margin": volume * base * D("0.02"),
                "risk_per_lot": risk,
            }.items()
        },
    }
