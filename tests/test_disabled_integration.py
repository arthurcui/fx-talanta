import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from fx_talanta.connected_shadow.authority import Authority
from fx_talanta.connected_shadow.inputs import GROUPS, canonical_hash
from fx_talanta.integration.coordinator import Coordinator
from fx_talanta.integration.inputs import assemble, load_context
from fx_talanta.safety.control import LossState, Protection
from fx_talanta.shadow.store import SQLiteStore
from fx_talanta.shadow.wire import Frame, digest
from fx_talanta.shadow.work import assess
from tests.test_connected_inputs import capture, context
from tools.fixtures.shadow_fixtures import ACCOUNT, CLIENT, KEY, NOW, POLICY, RELEASE, work

INC = "1" * 64


def make(tmp_path, owner=False):
    authority = Authority(
        SQLiteStore(tmp_path / "authority.db", bootstrap=True), ACCOUNT, bootstrap=True
    )
    authority.claim(CLIENT, INC, NOW)
    store = SQLiteStore(tmp_path / "backend.db", bootstrap=True)
    ledger = LossState(
        day=datetime.fromtimestamp(NOW / 1000, UTC).date(),
        start="10000",
        units="10000",
        owner_pause=owner,
    )
    return Coordinator(
        store,
        authority,
        ACCOUNT,
        CLIENT,
        INC,
        1,
        RELEASE,
        POLICY,
        KEY,
        lambda: NOW,
        initial=ledger,
        bootstrap=True,
        clock_error_ms=10,
    )


def call(c, op="PULL", payload="", nonce="a" * 64):
    raw = Frame("C2S", c.scope, CLIENT, nonce, NOW, NOW + 5000, op, payload).encode(KEY)
    response = c.exchange(raw, NOW)
    return Frame.decode(
        response, KEY, direction="S2C", scope=c.scope, client=CLIENT, now=NOW, nonce=nonce
    )


def restart(c):
    return Coordinator(
        c.store,
        c.authority,
        ACCOUNT,
        CLIENT,
        INC,
        1,
        RELEASE,
        POLICY,
        KEY,
        lambda: NOW,
        expected_tip=c.checkpoint(),
    )


def test_integrated_typed_work_receipt_restart_and_duplicate(tmp_path):
    c = make(tmp_path)
    envelope, snapshot = work()
    c.publish(envelope, snapshot, NOW)
    packet = call(c).payload.split("\t")
    assert packet[0] == "disabled-work/1" and len(packet) == 11
    original = bytes.fromhex(packet[1]).decode()
    receipt = assess(original, NOW)
    c = restart(c)
    ack = call(c, "REPORT", receipt, "b" * 64)
    assert ack.operation == "ACK" and ack.payload == digest(receipt)
    assert call(c, "REPORT", receipt, "b" * 64) == ack
    assert call(c, nonce="c" * 64).operation == "EMPTY"
    assert c.status(NOW)["execution_enabled"] is False
    with c.store.transaction() as events:
        assert len([e for e in events.records if e["kind"] == "receipt"]) == 1
        assert all(e["execution_enabled"] is False for e in events.records)


def test_durable_owner_pause_cannot_be_omitted(tmp_path):
    c = make(tmp_path, owner=True)
    with pytest.raises(ValueError, match="DURABLE_SAFETY_VETO"):
        c.publish(*work(), NOW)
    c.publish(*work(flags=64), NOW)
    packet = call(c).payload.split("\t")
    receipt = assess(bytes.fromhex(packet[1]).decode(), NOW)
    assert "OWNER_PAUSED" in receipt


def test_loss_update_invalidates_queued_work_and_deduplicates_flow(tmp_path):
    c = make(tmp_path)
    c.publish(*work(), NOW)
    observation = dict(
        day=datetime.fromtimestamp(NOW / 1000, UTC).date(), equity=Decimal("9800"), reconciled=True
    )
    state = c.reconcile("statement-1", evidence_hash="f" * 64, now=NOW, **observation)
    assert state.loss_pause
    tip = c.checkpoint()
    assert c.reconcile("statement-1", evidence_hash="f" * 64, now=NOW, **observation) == state
    assert c.checkpoint() == tip
    with pytest.raises(ValueError, match="RECONCILIATION_CONFLICT"):
        c.reconcile("statement-1", evidence_hash="e" * 64, now=NOW, **observation)
    with pytest.raises(ValueError, match="WORK_INVALIDATED"):
        call(c)


def test_checkpoint_required_and_changed_store_not_adopted(tmp_path):
    c = make(tmp_path)
    with pytest.raises(ValueError, match="RETAINED_CHECKPOINT_REQUIRED"):
        Coordinator(
            c.store, c.authority, ACCOUNT, CLIENT, INC, 1, RELEASE, POLICY, KEY, lambda: NOW
        )
    tip = c.checkpoint()
    c.publish(*work(), NOW)
    with pytest.raises(ValueError, match="RETAINED_CHECKPOINT_CONFLICT"):
        Coordinator(
            c.store,
            c.authority,
            ACCOUNT,
            CLIENT,
            INC,
            1,
            RELEASE,
            POLICY,
            KEY,
            lambda: NOW,
            expected_tip=tip,
        )


def test_protection_recommendations_never_claim_unsent_orders(tmp_path):
    c = make(tmp_path)
    p = Protection(
        phase="PENDING",
        submitted_ms=100,
        repair_deadline_ms=200,
        exit_deadline_ms=300,
        last_ms=100,
        boot_id="boot",
    )
    args = dict(
        boot_id="boot",
        storage_ok=True,
        broker_ok=True,
        reconciled=True,
        protected=False,
        closed=False,
        mutation_unknown=False,
    )
    state, action, suppressed = c.protect(
        "position-1", p, evidence_hash="f" * 64, now_ms=150, **args
    )
    assert action == "ATTACH_STOP_ONCE" and suppressed and state.phase == "PENDING"
    state, action, suppressed = c.protect(
        "position-1", state, evidence_hash="e" * 64, now_ms=250, **args
    )
    assert action == "CONTROLLED_EXIT_ONCE" and suppressed and state.phase == "PENDING"
    state, action, suppressed = c.protect(
        "position-1", state, evidence_hash="d" * 64, now_ms=310, **args
    )
    assert state.hard_halt and suppressed


def test_clock_sync_requires_evidence_and_is_nonce_bound(tmp_path):
    c = make(tmp_path)
    response = call(c, payload="disabled-sync/1")
    assert response.payload == f"disabled-clock/1\t{NOW}\t10"
    assert call(c, payload="disabled-sync/1") == response
    c.clock_error_ms = 1000
    with pytest.raises(ValueError, match="CLOCK_EVIDENCE_REQUIRED"):
        call(c, payload="disabled-sync/1", nonce="b" * 64)


def artifacts(tmp_path, raw):
    data = context(raw)
    source = b"synthetic fixture source, never a broker qualification"
    ref = hashlib.sha256(source).hexdigest()
    (tmp_path / (ref + ".source")).write_bytes(source)
    refs = {}
    for group, fields in GROUPS.items():
        artifact = dict(
            schema="operating-facts/1",
            group=group,
            account_scope=raw["account_scope"],
            observed_at_ms=data["observed_at_ms"],
            valid_until_ms=data["valid_until_ms"],
            values={k: data["values"][k] for k in fields},
            sources=[ref],
        )
        h = canonical_hash(artifact)
        (tmp_path / (h + ".json")).write_text(json.dumps(artifact))
        refs[group] = h
    return refs, ref


def test_operating_bundle_retains_real_source_and_no_defaults(tmp_path):
    raw = capture()
    refs, source = artifacts(tmp_path, raw)
    result, missing = assemble(
        raw, tmp_path, refs, symbol="EURUSD", side="BUY", now_ms=raw["measured_at_ms"]
    )
    assert not missing and result.snapshot is not None
    assert result.provenance["qualified_for_trading"] is False
    (tmp_path / (source + ".source")).write_bytes(b"changed")
    with pytest.raises(ValueError, match="OPERATIONAL_SOURCE_HASH"):
        assemble(raw, tmp_path, refs, symbol="EURUSD", side="BUY", now_ms=raw["measured_at_ms"])


def test_missing_expired_and_path_traversal_are_holds(tmp_path):
    raw = capture()
    refs, _ = artifacts(tmp_path, raw)
    value, missing = load_context(
        tmp_path, refs, raw["account_scope"], raw["measured_at_ms"] + 2000
    )
    assert value is None and len(missing) == len(GROUPS)
    refs["costs"] = "../secret"
    value, missing = load_context(tmp_path, refs, raw["account_scope"], raw["measured_at_ms"])
    assert value is None and missing == ("COSTS_MISSING",)


def test_cross_operation_nonce_is_not_reused(tmp_path):
    c = make(tmp_path)
    call(c, payload="disabled-sync/1")
    with pytest.raises(ValueError, match="NONCE_CONFLICT"):
        call(c)


def test_duplicate_pull_preserves_exact_packet_and_journal_tip(tmp_path):
    c = make(tmp_path)
    c.publish(*work(), NOW)
    first = call(c)
    tip = c.checkpoint()
    assert call(c) == first and c.checkpoint() == tip


def test_uncertain_transport_commit_quarantines_coordinator(tmp_path, monkeypatch):
    c = make(tmp_path)
    c.publish(*work(), NOW)
    original = c.backend.exchange

    def lost(raw, now):
        original(raw, now)
        raise OSError("injected response/commit ambiguity")

    monkeypatch.setattr(c.backend, "exchange", lost)
    with pytest.raises(OSError):
        call(c)
    with pytest.raises(ValueError, match="INTEGRATION_CHECKPOINT_CONFLICT"):
        c.checkpoint()


@pytest.mark.integration
def test_postgres_composed_journals_restart_and_loss_veto(settings):
    from dataclasses import replace
    from uuid import uuid4

    from fx_talanta.connected_shadow.authority import PostgresAuthorityStore
    from fx_talanta.domain.models import Environment
    from fx_talanta.shadow.store import PostgresStore
    from fx_talanta.storage.bootstrap import bootstrap

    configured = replace(settings, namespace="fx_dg_" + uuid4().hex[:10])
    bootstrap(configured)
    account = ACCOUNT
    authority = Authority(
        PostgresAuthorityStore(configured.runtime_dsn(Environment.PAPER), account),
        account,
        bootstrap=True,
    )
    authority.claim(CLIENT, INC, NOW)
    store = PostgresStore(configured.runtime_dsn(Environment.PAPER), account, uuid4())
    ledger = LossState(
        day=datetime.fromtimestamp(NOW / 1000, UTC).date(),
        start="10000",
        units="10000",
        owner_pause=False,
    )
    c = Coordinator(
        store,
        authority,
        account,
        CLIENT,
        INC,
        1,
        RELEASE,
        POLICY,
        KEY,
        lambda: NOW,
        initial=ledger,
        bootstrap=True,
    )
    c.publish(*work(), NOW)
    packet = call(c).payload.split("\t")
    receipt = assess(bytes.fromhex(packet[1]).decode(), NOW)
    c = restart(c)
    assert call(c, "REPORT", receipt, "b" * 64).operation == "ACK"
    assert c.status(NOW)["orders_sent"] == 0


def test_receipt_only_recovery_after_lease_expiry(tmp_path):
    c = make(tmp_path)
    c.publish(*work(), NOW)
    packet = call(c).payload.split("\t")
    receipt = assess(bytes.fromhex(packet[1]).decode(), NOW)
    late = NOW + 20000
    c = Coordinator(
        c.store,
        c.authority,
        ACCOUNT,
        CLIENT,
        INC,
        1,
        RELEASE,
        POLICY,
        KEY,
        lambda: late,
        expected_tip=c.checkpoint(),
        receipt_only=True,
        clock_error_ms=10,
    )
    with pytest.raises(ValueError, match="RECEIPT_ONLY_RECOVERY"):
        c.publish(*work(), late)
    raw = Frame("C2S", c.scope, CLIENT, "c" * 64, late, late + 5000, "PULL", "").encode(KEY)
    with pytest.raises(ValueError, match="RECEIPT_ONLY_RECOVERY"):
        c.exchange(raw, late)
    raw = Frame("C2S", c.scope, CLIENT, "d" * 64, late, late + 5000, "REPORT", receipt).encode(KEY)
    response = c.exchange(raw, late)
    assert (
        Frame.decode(
            response, KEY, direction="S2C", scope=c.scope, client=CLIENT, now=late
        ).operation
        == "ACK"
    )


def test_no_order_native_dependency_closure():
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    seen = set()

    def inspect(path):
        path = path.resolve()
        if path in seen:
            return
        seen.add(path)
        text = path.read_text()
        # Comments may name forbidden APIs to explain their absence.
        code = re.sub(r"//[^\n]*|/\*.*?\*/", "", text, flags=re.S)
        assert not re.search(
            r"\b(?:OrderSend|OrderSendAsync|PositionClose|PositionModify)\s*\(", code
        )
        for include in re.findall(r'#include "([^"]+)"', text):
            inspect(path.parent / include)

    inspect(root / "mql5/integration/DisabledEA.mq5")
    assert not any(p.name == "Broker.mqh" for p in seen)


def test_unresolved_protection_veto_and_hard_halt_survive_restart(tmp_path):
    c = make(tmp_path)
    p = Protection(
        phase="PENDING",
        submitted_ms=100,
        repair_deadline_ms=200,
        exit_deadline_ms=300,
        last_ms=100,
        boot_id="boot",
    )
    args = dict(
        boot_id="boot",
        storage_ok=True,
        broker_ok=True,
        reconciled=True,
        protected=False,
        closed=False,
        mutation_unknown=False,
    )
    state, _, _ = c.protect("owned", p, evidence_hash="f" * 64, now_ms=150, **args)
    with pytest.raises(ValueError, match="DURABLE_SAFETY_VETO"):
        c.publish(*work(), NOW)
    assert c.status(NOW)["current_veto_flags"] & 8
    c.protect("owned", state, evidence_hash="e" * 64, now_ms=310, **args)
    resumed = restart(c)
    assert resumed.status(NOW)["current_veto_flags"] & 1
    with pytest.raises(ValueError, match="DURABLE_SAFETY_VETO"):
        resumed.publish(*work(flags=8), NOW)
