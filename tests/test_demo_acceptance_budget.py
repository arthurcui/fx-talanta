from dataclasses import replace

import pytest

from fx_talanta.demo.acceptance_budget import AcceptanceBudget, BudgetPlan
from fx_talanta.shadow.store import SQLiteStore
from scripts.demo_execution_fixtures import ACCOUNT

NOW = 100_000
PLAN = BudgetPlan("a" * 64, NOW, NOW + 300_000, 200_000, "e" * 64)


def make(tmp_path):
    store = SQLiteStore(tmp_path / "budget.db", bootstrap=True)
    return AcceptanceBudget(store, ACCOUNT, PLAN, bootstrap=True)


def close(b, request="b" * 64, now=NOW + 100, **changes):
    audit = (
        dict(
            scope=b.binding["scope"],
            request_hash=request,
            source="INDEPENDENT_BROKER_AUDIT",
            evidence_sha256=request,
            observed_at_ms=now,
            entry_units=1_000_000,
            exit_units=1_000_000,
            open_positions=0,
            pending_orders=0,
        )
        | changes
    )
    return b.record_verified_closure(request, audit, now)


def test_charged_before_attempt_and_no_retry_after_restart(tmp_path):
    b = make(tmp_path)
    tip = b.reserve("b" * 64, "EURUSD", 1_000_000, 500, NOW, eligible_equity_cents=200_000)
    restored = AcceptanceBudget(b.store, ACCOUNT, PLAN, expected_tip=tip)
    with pytest.raises(ValueError, match="ALREADY_CHARGED"):
        restored.reserve("b" * 64, "EURUSD", 1_000_000, 500, NOW + 1, eligible_equity_cents=200_000)
    with pytest.raises(ValueError, match="OUTCOME_UNRESOLVED"):
        restored.reserve("c" * 64, "USDJPY", 1_000_000, 500, NOW + 1, eligible_equity_cents=200_000)
    assert restored.status(NOW + 1)["risk_cents_charged"] == 500
    assert not restored.status(NOW + 1)["execution_enabled"]


def test_positive_closure_does_not_refund_budget(tmp_path):
    b = make(tmp_path)
    b.reserve("b" * 64, "EURUSD", 1_000_000, 500, NOW, eligible_equity_cents=200_000)
    close(b)
    b.reserve("c" * 64, "USDJPY", 1_000_000, 500, NOW + 200, eligible_equity_cents=200_000)
    close(b, "c" * 64, NOW + 300)
    with pytest.raises(ValueError, match="EXHAUSTED"):
        b.reserve("d" * 64, "EURUSD", 1_000_000, 1, NOW + 400, eligible_equity_cents=200_000)
    assert b.status(NOW + 400)["risk_cents_charged"] == 1000


@pytest.mark.parametrize(
    "change",
    [
        {"source": "EA_BROKER_RECONCILIATION"},
        {"entry_units": 0, "exit_units": 0},
        {"exit_units": 500_000},
        {"open_positions": 1},
        {"pending_orders": 1},
        {"scope": "c" * 64},
        {"observed_at_ms": NOW - 1},
        {"observed_at_ms": NOW + 101},
        {"evidence_sha256": None},
        {"entry_units": True},
        {"entry_units": 2_000_000, "exit_units": 2_000_000},
    ],
)
def test_absence_claim_stale_mismatch_or_overfill_cannot_clear_charge(tmp_path, change):
    b = make(tmp_path)
    b.reserve("b" * 64, "EURUSD", 1_000_000, 500, NOW, eligible_equity_cents=200_000)
    with pytest.raises(ValueError):
        close(b, **change)
    assert b.status(NOW + 100)["unresolved"] == 1


def test_expiry_blocks_entry_not_late_reconciliation(tmp_path):
    b = make(tmp_path)
    b.reserve("b" * 64, "EURUSD", 1_000_000, 500, NOW, eligible_equity_cents=200_000)
    close(b, now=PLAN.expires_ms + 100)
    with pytest.raises(ValueError, match="WINDOW_CLOSED"):
        b.reserve(
            "c" * 64, "USDJPY", 1_000_000, 500, PLAN.expires_ms + 101, eligible_equity_cents=200_000
        )
    assert b.status(PLAN.expires_ms + 101)["unresolved"] == 0


def test_stale_checkpoint_competing_instance_and_new_plan_refuse(tmp_path):
    b = make(tmp_path)
    initial = b.tip
    peer = AcceptanceBudget(b.store, ACCOUNT, PLAN, expected_tip=initial)
    b.reserve("b" * 64, "EURUSD", 1_000_000, 500, NOW, eligible_equity_cents=200_000)
    with pytest.raises(ValueError, match="CHECKPOINT"):
        peer.reserve("c" * 64, "USDJPY", 1_000_000, 500, NOW, eligible_equity_cents=200_000)
    with pytest.raises(ValueError, match="CHECKPOINT"):
        AcceptanceBudget(b.store, ACCOUNT, PLAN, expected_tip=initial)
    with pytest.raises(ValueError, match="CHECKPOINT"):
        AcceptanceBudget(b.store, ACCOUNT, PLAN)
    with pytest.raises(ValueError, match="BINDING"):
        AcceptanceBudget(b.store, ACCOUNT, replace(PLAN, campaign="c" * 64), expected_tip=b.tip)
    with pytest.raises(ValueError, match="ALREADY_EXISTS"):
        AcceptanceBudget(b.store, ACCOUNT, PLAN, bootstrap=True)


@pytest.mark.parametrize(
    "change",
    [
        {"campaign": None},
        {"entries": True},
        {"entries": 3},
        {"currency": "JPY"},
        {"lot_units": 2_000_001},
        {"total_bps": 51},
        {"per_entry_bps": 26},
        {"expires_ms": PLAN.expires_ms + 1},
        {"starts_ms": PLAN.expires_ms},
    ],
)
def test_plan_cannot_exceed_bounded_mandate(change):
    with pytest.raises(ValueError, match="INVALID_DEMO_BUDGET"):
        replace(PLAN, **change)


@pytest.mark.parametrize(
    "lot,risk", [(True, 1), (1, True), (0, 1), (1, 0), (2_000_001, 1), (1, 501)]
)
def test_invalid_charge_leaves_journal_unchanged(tmp_path, lot, risk):
    b = make(tmp_path)
    tip = b.tip
    with pytest.raises(ValueError):
        b.reserve("b" * 64, "EURUSD", lot, risk, NOW, eligible_equity_cents=200_000)
    assert b.status(NOW)["checkpoint"] == tip


def test_account_binding_and_time_regression(tmp_path):
    b = make(tmp_path)
    other = ACCOUNT.model_copy(update={"venue": "SIMULATOR"})
    with pytest.raises(ValueError, match="BROKER_DEMO_REQUIRED"):
        AcceptanceBudget(b.store, other, PLAN, expected_tip=b.tip)
    b.reserve("b" * 64, "EURUSD", 1_000_000, 500, NOW + 10, eligible_equity_cents=200_000)
    with pytest.raises(ValueError, match="TIME_REGRESSION"):
        b.status(NOW)


def test_lost_journal_and_valid_prefix_rollback_refuse(tmp_path):
    b = make(tmp_path)
    backup = b.store.path.read_bytes()
    b.reserve("b" * 64, "EURUSD", 1_000_000, 500, NOW, eligible_equity_cents=200_000)
    b.store.path.write_bytes(backup)
    with pytest.raises(ValueError, match="CHECKPOINT"):
        AcceptanceBudget(b.store, ACCOUNT, PLAN, expected_tip=b.tip)
    b.store.path.unlink()
    with pytest.raises(ValueError, match="MISSING_JOURNAL"):
        b.status(NOW)


def test_expiry_is_durable_and_cannot_be_reopened(tmp_path):
    b = make(tmp_path)
    assert not b.status(PLAN.expires_ms)["entry_window_open"]
    b = AcceptanceBudget(b.store, ACCOUNT, PLAN, expected_tip=b.tip)
    with pytest.raises(ValueError, match="TIME_REGRESSION"):
        b.reserve(
            "b" * 64, "EURUSD", 1_000_000, 500, PLAN.expires_ms - 1, eligible_equity_cents=200_000
        )
    with pytest.raises(ValueError, match="WINDOW_CLOSED"):
        b.reserve(
            "b" * 64, "EURUSD", 1_000_000, 500, PLAN.expires_ms + 1, eligible_equity_cents=200_000
        )


def test_historical_native_budget_evidence_and_original_entry_ceiling(historical_source):
    import hashlib
    import json
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    report = json.loads((root / "docs/evidence/m2-native-budget.json").read_text())
    for name, expected in report["native_dependency_sha256"].items():
        assert hashlib.sha256(historical_source(name, expected)).hexdigest() == expected
    raw = (root / "tests/fixtures/demo-budget/demo-checks.tsv").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == report["checks_sha256"]
    rows = [line.split("\t") for line in raw.decode().splitlines()]
    assert len(rows) == len(dict(rows)) == report["check_count"]
    assert all(value == "1" for _, value in rows)
    assert not report["execution_enabled"] and not report["demo_order_acceptance"]
    port = (root / "mql5/demo/NativePort.mqh").read_text()
    assert "const bool FX_DEMO_SUBMISSION_AUTHORIZED=false;" in port
    assert "budget.Charge(w,now_ms,PositionsTotal()==0 && OrdersTotal()==0," in port
    assert "at+error-c.tick_ms>2000" in port


@pytest.mark.parametrize("equity,allowed", [(100_000, 250), (400_000, 1000), (123_456, 308)])
def test_percentage_scales_and_rounds_limits_down(tmp_path, equity, allowed):
    b = AcceptanceBudget(
        SQLiteStore(tmp_path / "percent.db", bootstrap=True),
        ACCOUNT,
        replace(PLAN, reference_equity_cents=equity),
        bootstrap=True,
    )
    with pytest.raises(ValueError, match="BUDGET_ENTRY_INVALID"):
        b.reserve("b" * 64, "EURUSD", 1_000_000, allowed + 1, NOW, eligible_equity_cents=equity)
    b.reserve("b" * 64, "EURUSD", 1_000_000, allowed, NOW, eligible_equity_cents=equity)
    assert b.status(NOW)["per_entry_percent"] == 0.25
    assert b.status(NOW)["total_percent"] == 0.5


def test_percentage_falls_with_equity_and_never_expands_with_gains(tmp_path):
    b = make(tmp_path)
    b.reserve("b" * 64, "EURUSD", 1_000_000, 250, NOW, eligible_equity_cents=100_000)
    close(b)
    restored = AcceptanceBudget(b.store, ACCOUNT, PLAN, expected_tip=b.tip)
    with pytest.raises(ValueError, match="BUDGET_ENTRY_INVALID"):
        restored.reserve(
            "c" * 64, "EURUSD", 1_000_000, 251, NOW + 200, eligible_equity_cents=400_000
        )
    assert restored.status(NOW + 200)["equity_basis_cents"] == 100_000
    with pytest.raises(ValueError, match="EXHAUSTED"):
        restored.reserve("c" * 64, "EURUSD", 1_000_000, 1, NOW + 200, eligible_equity_cents=50_000)


@pytest.mark.parametrize(
    "change",
    [
        {"reference_equity_cents": 0},
        {"reference_equity_cents": True},
        {"reference_equity_cents": 1_000_000_000_001},
        {"equity_evidence_hash": "0" * 64},
        {"equity_evidence_hash": None},
        {"per_entry_bps": True},
        {"total_bps": 0},
    ],
)
def test_percentage_requires_verified_bounded_basis(change):
    with pytest.raises(ValueError, match="INVALID_DEMO_BUDGET"):
        replace(PLAN, **change)


def test_percentage_policy_and_basis_cannot_change_on_restore(tmp_path):
    b = make(tmp_path)
    for plan in [
        replace(PLAN, reference_equity_cents=400_000),
        replace(PLAN, per_entry_bps=20),
        replace(PLAN, currency="USD"),
    ]:
        with pytest.raises(ValueError, match="BINDING"):
            AcceptanceBudget(b.store, ACCOUNT, plan, expected_tip=b.tip)


def test_current_percentage_native_evidence():
    import hashlib
    import json
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    report = json.loads((root / "docs/evidence/m2-percentage-budget.json").read_text())
    for name, expected in report["native_dependency_sha256"].items():
        assert hashlib.sha256((root / name).read_bytes()).hexdigest() == expected
    raw = (root / "tests/fixtures/demo-percent/demo-checks.tsv").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == report["checks_sha256"]
    rows = [line.split("\t") for line in raw.decode().splitlines()]
    assert len(rows) == len(dict(rows)) == report["native_check_count"]
    assert all(value == "1" for _, value in rows)
    assert not report["execution_enabled"] and not report["demo_order_acceptance"]
