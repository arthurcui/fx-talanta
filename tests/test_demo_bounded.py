from decimal import Decimal

import pytest

from fx_talanta.demo.acceptance_budget import AcceptanceBudget, BudgetPlan
from fx_talanta.demo.bounded import BoundedDemoCoordinator
from fx_talanta.domain.ea_protocol import Envelope
from fx_talanta.shadow.store import SQLiteStore
from fx_talanta.shadow.work import snapshot_hash
from scripts.demo_execution_fixtures import ACCOUNT, example
from scripts.shadow_fixtures import CLIENT, KEY, NOW, POLICY, RELEASE
from tests.test_demo_execution import INC, make, restart


def bounded(tmp_path):
    base = make(tmp_path)
    budget = AcceptanceBudget(
        SQLiteStore(tmp_path / "budget.db", bootstrap=True),
        ACCOUNT,
        BudgetPlan("a" * 64, NOW, NOW + 300_000, 200_000, "e" * 64),
        bootstrap=True,
    )
    with base.store.transaction() as events:
        initial = base._ledger(events)
    return BoundedDemoCoordinator(
        SQLiteStore(tmp_path / "bounded.db", bootstrap=True),
        base.authority,
        ACCOUNT,
        CLIENT,
        INC,
        1,
        RELEASE,
        POLICY,
        KEY,
        lambda: NOW,
        budget=budget,
        initial=initial,
        bootstrap=True,
        clock_error_ms=10,
    )


def packet(volume="0.01", risk="1"):
    e, s = example()
    s = type(s).model_validate(
        s.model_dump()
        | {
            "currency": "CAD",
            "request_volume": Decimal(volume),
            "request_risk": Decimal(risk),
        }
    )
    e = Envelope.seal(
        type(e.payload).model_validate(
            e.payload.model_dump()
            | {
                "currency": "CAD",
                "max_volume": Decimal(volume),
                "max_risk": Decimal(risk),
                "snapshot_hash": snapshot_hash(s),
            }
        )
    )
    return e, s


def test_publication_is_charged_and_cannot_restore_without_budget(tmp_path):
    c = bounded(tmp_path)
    e, s = packet(risk="1.001")
    assert c.publish(e, s, NOW)
    assert c.status(NOW)["acceptance_budget"]["risk_cents_charged"] == 101
    assert c.status(NOW)["orders_sent"] == 0
    with pytest.raises(ValueError, match="BINDING_CONFLICT"):
        restart(c)
    with pytest.raises(ValueError, match="ALREADY_CHARGED"):
        c.publish(e, s, NOW)


@pytest.mark.parametrize("volume,risk", [("0.020000001", "1"), ("0.01", "5.001")])
def test_rounding_cannot_hide_excess_budget(tmp_path, volume, risk):
    c = bounded(tmp_path)
    e, s = packet(volume, risk)
    with pytest.raises(ValueError, match="BUDGET_ENTRY_INVALID"):
        c.publish(e, s, NOW)
    assert c.acceptance_budget.status(NOW)["entries_charged"] == 0


def test_unknown_enqueue_failure_never_refunds_charge(tmp_path, monkeypatch):
    c = bounded(tmp_path)
    from fx_talanta.demo.coordinator import DemoBackend

    def fail(*args):
        raise OSError("simulated commit response loss")

    monkeypatch.setattr(DemoBackend, "publish", fail)
    e, s = packet()
    with pytest.raises(OSError):
        c.publish(e, s, NOW)
    assert c.acceptance_budget.status(NOW)["unresolved"] == 1
    assert c.acceptance_budget.status(NOW)["risk_cents_charged"] == 100
