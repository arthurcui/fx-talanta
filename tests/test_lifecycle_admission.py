from decimal import Decimal

import pytest
from test_risk import evaluate, intent

from fx_talanta.domain.offline import Entry, Policy

D = Decimal


@pytest.mark.parametrize("side", ["BUY", "SELL"])
def test_admission_only_restricts_with_auditable_equity_floor(side):
    policy = Policy(maximum_positions=1, trade_fraction="0.001", aggregate_fraction="0.001")
    plain = intent(side=side)
    legacy, _ = evaluate(policy, proposal=plain)
    guarded, reason = evaluate(
        policy, proposal=plain.model_copy(update={"lifecycle_guard": "FINITE_TARGET_90_PERCENT"})
    )
    assert reason == "approved"
    assert guarded.volume < legacy.volume
    e = guarded.lifecycle_bound
    assert e["peak_planned_giveback"] <= e["equity_floor"] * policy.aggregate_fraction * D("0.9")
    assert e["equity_floor"] == policy.capital - guarded.risk_per_lot * guarded.volume
    assert "lifecycle_guard" not in plain.model_dump()
    assert "lifecycle_bound" not in legacy.model_dump()
    assert policy.quote_age_seconds == 2


def test_minimum_lot_is_hold_and_unproved_scope_rejected():
    guarded = intent().model_copy(update={"lifecycle_guard": "FINITE_TARGET_90_PERCENT"})
    value, reason = evaluate(
        Policy(maximum_positions=1, aggregate_fraction="0.0001"), proposal=guarded
    )
    assert value is None and "minimum lot" in reason
    assert evaluate(Policy(maximum_positions=2), proposal=guarded)[0] is None
    assert (
        evaluate(
            Policy(maximum_positions=1),
            proposal=intent("USDJPY").model_copy(
                update={"lifecycle_guard": "FINITE_TARGET_90_PERCENT"}
            ),
        )[0]
        is None
    )


def test_pending_reservation_cannot_borrow_lifecycle_capacity():
    policy = Policy(maximum_positions=1)
    guarded = intent().model_copy(update={"lifecycle_guard": "FINITE_TARGET_90_PERCENT"})
    reserved, _ = evaluate(policy, proposal=guarded)
    entries = (Entry(intent=guarded, state="OUTCOME_UNKNOWN", reservation=reserved),)
    value, reason = evaluate(policy, proposal=guarded, entries=entries)
    assert value is None and reason == "position slot occupied"
