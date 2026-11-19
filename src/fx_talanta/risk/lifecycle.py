"""Additional admission restriction; never alters ongoing giveback or HALT policy."""

from decimal import Decimal

HEADROOM = Decimal("0.90")


def finite_target_bound(intent, spec, market, policy, eligible, initial_per_lot, used_risk):
    if (
        intent.symbol != "EURUSD"
        or spec.quote != "USD"
        or market.conversion[spec.quote] != 1
        or policy.maximum_positions != 1
        or used_risk != 0
    ):
        raise ValueError("lifecycle bound requires one unoccupied EURUSD/USD account slot")
    peak_per_lot = (
        abs(intent.target - intent.stop) * spec.contract_size
        + spec.commission_per_lot
        + spec.slippage_per_lot
        + spec.financing_per_lot
    )
    fraction = HEADROOM * policy.aggregate_fraction
    # peak*v <= .90*aggregate_fraction*(eligible - initial_loss_per_lot*v)
    upper = fraction * eligible / (peak_per_lot + fraction * initial_per_lot)
    return upper, peak_per_lot
