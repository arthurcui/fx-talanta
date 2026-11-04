from dataclasses import replace

import pytest

from fx_talanta.demo.activation import DemoActivation, QuoteTimePolicy
from fx_talanta.demo.bounded import BoundedDemoCoordinator
from fx_talanta.shadow.store import SQLiteStore
from scripts.shadow_fixtures import CLIENT, KEY, NOW, POLICY, RELEASE
from tests.test_demo_bounded import ACCOUNT, INC, bounded, packet


def activation(c):
    plan = c.acceptance_budget.plan
    mapping = QuoteTimePolicy(
        c.scope, 7_200_000, NOW - 1000, NOW + 600_000, "b" * 64, "BROKER_TIME_DECLARATION"
    )
    return DemoActivation(
        c.scope,
        RELEASE,
        POLICY,
        c.acceptance_budget.binding_hash,
        mapping,
        "c" * 64,
        plan.starts_ms,
        plan.expires_ms,
    )


def test_mapping_does_not_infer_offset_from_tick_arrival(tmp_path):
    policy = activation(bounded(tmp_path)).time_policy
    for kind in ("PROVISIONAL_CONSISTENCY", "TICK_FIT", "", "MCP_CLOCK"):
        with pytest.raises(ValueError, match="QUALIFIED_BROKER_TIME_POLICY"):
            replace(policy, source_kind=kind)
    assert policy.age_upper(NOW + 7_200_000 + 1010, NOW + 4000, 10) == 3000
    with pytest.raises(ValueError, match="QUOTE_TIME_UNVERIFIED"):
        policy.age_upper(NOW + 7_200_000, NOW, 10)


def test_mapping_exact_two_second_boundary_and_expiry(tmp_path):
    policy = activation(bounded(tmp_path)).time_policy
    now = NOW + 2000
    assert policy.age_upper(now + 7_200_000 - 1990, now, 10) == 2000
    assert policy.age_upper(now + 7_200_000 - 1991, now, 10) == 2001
    with pytest.raises(ValueError, match="QUOTE_TIME_UNVERIFIED"):
        policy.age_upper(policy.expires_ms + 7_200_000 - 500, policy.expires_ms, 10)


@pytest.mark.parametrize(
    "change",
    [
        {"budget_hash": "d" * 64},
        {"scope": "d" * 64},
        {"release": "d" * 64},
        {"policy": "d" * 64},
        {"starts_ms": NOW + 1},
        {"operating_evidence": "0" * 64},
    ],
)
def test_activation_rejects_changed_binding(tmp_path, change):
    c = bounded(tmp_path)
    with pytest.raises(ValueError, match="ACTIVATION_BINDING"):
        replace(activation(c), **change).validate(c.acceptance_budget, RELEASE, POLICY)


def test_activation_requires_time_for_controlled_close(tmp_path):
    c = bounded(tmp_path)
    a = activation(c)
    with pytest.raises(ValueError, match="ACTIVATION_BINDING"):
        replace(a, time_policy=replace(a.time_policy, expires_ms=a.expires_ms)).validate(
            c.acceptance_budget, RELEASE, POLICY
        )


def test_activated_backend_remains_budget_bound_and_not_strategy_enabled(tmp_path):
    c = bounded(tmp_path)
    a = activation(c)
    with c.store.transaction() as events:
        ledger = c._ledger(events)
    args = (c.authority, ACCOUNT, CLIENT, INC, 1, RELEASE, POLICY, KEY, lambda: NOW)
    active = BoundedDemoCoordinator(
        SQLiteStore(tmp_path / "active.db", bootstrap=True),
        *args,
        budget=c.acceptance_budget,
        activation=a,
        bootstrap=True,
        initial=ledger,
        clock_error_ms=10,
    )
    assert active.status(NOW)["native_execution_authorized"]
    assert not active.status(NOW)["strategy_trading_enabled"]
    with pytest.raises(ValueError, match="ACTIVATION_ENTRY_WINDOW_CLOSED"):
        active.backend.publish(*packet(), NOW)
    assert active.acceptance_budget.status(NOW)["entries_charged"] == 0
    with pytest.raises(ValueError, match="BINDING_CONFLICT"):
        BoundedDemoCoordinator(
            active.store, *args, budget=c.acceptance_budget, expected_tip=active.checkpoint()
        )
    assert not a.entry_open(a.expires_ms - 10, 10)
    assert a.entry_open(NOW + 10, 10)
    assert a.native_manifest().startswith("BOUNDED_DEMO_ACTIVATION_1\t")


@pytest.mark.parametrize(
    "outcome,mutation,halt",
    [("ACKNOWLEDGED", "ATTEMPTED", False), ("OUTCOME_UNKNOWN", "UNKNOWN", True)],
)
def test_authorized_receipts_preserve_uncertainty_halt(tmp_path, outcome, mutation, halt):
    from fx_talanta.demo.projection import project
    from fx_talanta.shadow.work import assess
    from tests.test_demo_execution import call

    c = bounded(tmp_path)
    with c.store.transaction() as events:
        ledger = c._ledger(events)
    active = BoundedDemoCoordinator(
        SQLiteStore(tmp_path / "authorized.db", bootstrap=True),
        c.authority,
        ACCOUNT,
        CLIENT,
        INC,
        1,
        RELEASE,
        POLICY,
        KEY,
        lambda: NOW + 20,
        budget=c.acceptance_budget,
        activation=activation(c),
        bootstrap=True,
        initial=ledger,
        clock_error_ms=10,
    )
    e, snapshot = packet()
    with pytest.raises(ValueError, match="NATIVE_DEMO_NOT_READY"):
        active.publish(e, snapshot, NOW + 20)
    assert active.acceptance_budget.status(NOW + 20)["entries_charged"] == 0
    native_ready(active, NOW + 20)
    active.publish(e, snapshot, NOW + 20)
    call(active, now=NOW + 20)
    reference = assess(project(e, snapshot), NOW + 20)
    report = "\t".join(["demo-receipt/2", reference.encode().hex(), outcome, outcome, mutation])
    assert call(active, "REPORT", report, "b" * 64, now=NOW + 20).operation == "ACK"
    with active.store.transaction() as events:
        assert active._ledger(events).hard_halt is halt
    from fx_talanta.connected_shadow.authority import backend_checkpoint

    assert backend_checkpoint(active.store, active.scope).sequence == 1
    assert active.status(NOW + 20)["orders_sent"] is None
    assert active.acceptance_budget.status(NOW + 20)["unresolved"] == 1


def test_capture_mapping_preserves_original_and_m1_holds():
    from copy import deepcopy

    from fx_talanta.connected_shadow.inputs import canonical_hash, normalize
    from tests.test_connected_inputs import capture

    raw = capture()
    raw.update(
        timestamp_mapping_qualified=False, time_policy_evidence="PROVISIONAL_CONSISTENCY_ONLY"
    )
    raw["capture_sha256"] = canonical_hash({k: v for k, v in raw.items() if k != "capture_sha256"})
    original = deepcopy(raw)
    now = raw["measured_at_ms"]
    policy = QuoteTimePolicy(
        raw["account_scope"],
        0,
        now - 10000,
        now + 15000,
        "c" * 64,
        "INDEPENDENT_EVENT_AND_NATIVE_CLOCK",
    )
    mapped = policy.bind_capture(raw)
    assert raw == original
    assert mapped["source_capture_sha256"] == raw["capture_sha256"]
    assert mapped["capture_sha256"] != raw["capture_sha256"]
    assert not mapped["qualified_for_trading"]
    result = normalize(mapped, symbol="EURUSD", side="BUY")
    assert "TIMESTAMP_MAPPING_UNQUALIFIED" not in result.missing
    assert "PROVIDERS" in result.missing and result.snapshot is None
    for change in ({"account_scope": "e" * 64}, {"sdk_time_offset_seconds": 7200}):
        bad = deepcopy(raw)
        bad.update(change)
        bad["capture_sha256"] = canonical_hash(
            {k: v for k, v in bad.items() if k != "capture_sha256"}
        )
        with pytest.raises(ValueError, match="TIME_POLICY_CAPTURE_BINDING"):
            policy.bind_capture(bad)
    bad = deepcopy(raw)
    bad["conversion"]["tick_ms"] -= 1
    bad["capture_sha256"] = canonical_hash({k: v for k, v in bad.items() if k != "capture_sha256"})
    with pytest.raises(ValueError, match="MAPPING_CONFLICT"):
        policy.bind_capture(bad)


def test_current_native_activation_evidence():
    import hashlib
    import json
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    report = json.loads((root / "docs/evidence/m2-bounded-activation.json").read_text())
    for name, expected in report["native_dependency_sha256"].items():
        assert hashlib.sha256((root / name).read_bytes()).hexdigest() == expected
    raw = (root / "tests/fixtures/demo-activation/demo-checks.tsv").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == report["checks_sha256"]
    rows = [line.split("\t") for line in raw.decode().splitlines()]
    assert len(rows) == len(dict(rows)) == report["native_check_count"]
    assert all(value == "1" for _, value in rows)
    assert not report["execution_enabled"] and not report["demo_order_acceptance"]


def test_capture_during_activation_is_read_only_and_expires(tmp_path):
    from fx_talanta.connected_shadow.inputs import capture_once
    from fx_talanta.demo.acceptance_budget import AcceptanceBudget, BudgetPlan
    from fx_talanta.observer.mt5 import ObservationFailure
    from fx_talanta.shadow.work import scope_for
    from tests.test_connected_inputs import NOW as CAPTURE_NOW
    from tests.test_connected_inputs import SDK, binding

    bound = binding()
    plan = BudgetPlan("a" * 64, CAPTURE_NOW - 100, CAPTURE_NOW + 1000, 1000000, "b" * 64)
    budget = AcceptanceBudget(
        SQLiteStore(tmp_path / "budget.db", bootstrap=True), bound.account, plan, bootstrap=True
    )
    policy = QuoteTimePolicy(
        scope_for(bound.account),
        0,
        CAPTURE_NOW - 1000,
        CAPTURE_NOW + 65000,
        "c" * 64,
        "BROKER_TIME_DECLARATION",
    )
    permit = DemoActivation(
        scope_for(bound.account),
        RELEASE,
        POLICY,
        budget.binding_hash,
        policy,
        "d" * 64,
        plan.starts_ms,
        plan.expires_ms,
    )
    sdk = SDK()
    sdk.terminal.trade_allowed = True
    now = [CAPTURE_NOW]

    def read(**kw):
        return capture_once(
            sdk,
            bound,
            clock_error_ms=10,
            clock_evidence_sha256="a" * 64,
            process_check=lambda _: [123],
            now_ms=lambda: now[0],
            **kw,
        )

    with pytest.raises(ObservationFailure, match="ALGORITHMIC_TRADING_MUST_BE_DISABLED"):
        read()
    result = read(demo_activation=permit, demo_budget=budget)
    assert result["terminal_algo_enabled"] and not result["execution_enabled"]
    assert result["bounded_read_activation_sha256"] == permit.validate(budget, RELEASE, POLICY)
    assert "order_send" not in result["sdk_calls"]
    now[0] = plan.expires_ms
    with pytest.raises(ObservationFailure, match="BOUNDED_DEMO_READ_EXPIRED"):
        read(demo_activation=permit, demo_budget=budget)
    assert budget.status(CAPTURE_NOW)["entries_charged"] == 0


def native_ready(active, now):
    from fx_talanta.shadow.wire import digest
    from tests.test_demo_execution import call

    payload = "bounded-sync/1\t" + digest(active.activation.native_manifest()) + "\t1"
    assert call(active, payload=payload, nonce="d" * 64, now=now).operation == "WORK"
    assert active.native_ready(now)
    assert not active.native_ready(now + 2001)
