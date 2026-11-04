import hashlib
import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal as D
from pathlib import Path

import pytest
from pydantic import ValidationError

from fx_talanta.domain.ea_protocol import Envelope, payload_hash
from fx_talanta.safety.control import LossState, Protection, losses, protection_step
from fx_talanta.safety.journal import SafetyJournal, canonical, seal
from fx_talanta.safety.preflight import shadow_preflight
from fx_talanta.safety.risk import SafetyInput, evaluate

ROOT = Path(__file__).resolve().parents[1]
SOURCE = json.loads((ROOT / "tests/fixtures/safety/risk.json").read_text())


def vector(**patch):
    return SafetyInput.model_validate(SOURCE["defaults"] | patch)


@pytest.mark.parametrize("case", SOURCE["cases"], ids=lambda c: c["id"])
def test_reviewed_risk_outcomes(case):
    result = evaluate(vector(**case["input"]))
    assert result["reason"] == case["expected"]["reason"]
    if result["reason"] == "ACCEPTED":
        assert D(result["volume"]) == D(case["expected"]["volume"])
        assert D(result["volume"]) <= vector(**case["input"]).request_volume
        assert D(result["risk"]) <= vector(**case["input"]).request_risk


@pytest.mark.parametrize(
    "patch",
    [{"equity": float("nan")}, {"equity": "NaN"}, {"bid": 1.1}, {"extra": True}, {"equity": "-1"}],
)
def test_reject_ambiguous_financial_inputs(patch):
    with pytest.raises(ValidationError):
        vector(**patch)


def loss_state(**patch):
    return LossState(day=date(2026, 1, 5), start=D(10000), units=D(10000), **patch)


def test_loss_flow_restart_utc_and_persistent_halt():
    state = losses(loss_state(), day=date(2026, 1, 5), equity=D(9900), reconciled=True)
    assert state.loss_pause and not state.hard_halt
    state = losses(
        state,
        day=state.day,
        equity=D(19900),
        flow=D(10000),
        equity_before_flow=D(9900),
        reconciled=True,
    )
    assert state.daily_loss == 100 and state.loss_pause and state.owner_pause
    restored = LossState.model_validate_json(state.model_dump_json())
    assert restored == state
    with pytest.raises(ValueError, match="boundary"):
        losses(restored, day=date(2026, 1, 6), equity=D(19900), reconciled=True)
    state = losses(
        restored, day=date(2026, 1, 6), equity=D(19900), reconciled=True, midnight_equity=D(19900)
    )
    assert not state.loss_pause and state.owner_pause
    state = losses(state, day=state.day, equity=state.units * D("0.95"), reconciled=True)
    assert state.hard_halt
    state = losses(
        state, day=date(2026, 1, 7), equity=D(30000), reconciled=True, midnight_equity=D(30000)
    )
    assert state.hard_halt


def test_withdrawal_and_unclassified_flow_do_not_reset_losses():
    state = losses(loss_state(), day=date(2026, 1, 5), equity=D(9900), reconciled=True)
    reduced = losses(
        state,
        day=state.day,
        equity=D(8900),
        flow=D(-1000),
        equity_before_flow=D(9900),
        reconciled=True,
    )
    assert reduced.daily_loss == 100 and reduced.loss_pause and reduced.units < state.units
    for patch in ({"reconciled": False}, {"flow": D(1)}, {"day": date(2026, 1, 4)}):
        with pytest.raises(ValueError):
            losses(state, **({"day": state.day, "equity": D(9900), "reconciled": True} | patch))


def protection(**patch):
    return Protection.model_validate(
        dict(
            phase="PENDING",
            submitted_ms=0,
            repair_deadline_ms=1000,
            exit_deadline_ms=2000,
            last_ms=0,
            boot_id="boot-a",
        )
        | patch
    )


def step(p, **patch):
    return protection_step(
        p,
        **(
            dict(
                now_ms=100,
                boot_id="boot-a",
                storage_ok=True,
                broker_ok=True,
                reconciled=True,
                protected=False,
                closed=False,
                mutation_unknown=False,
            )
            | patch
        ),
    )


def test_protection_never_resends_unknown_mutation_or_resets_deadline():
    p, action = step(protection())
    assert action == "ATTACH_STOP_ONCE"
    p, action = step(p, now_ms=101, mutation_unknown=True, reconciled=False)
    assert action == "RECONCILE_NO_RESEND"
    p, action = step(p, now_ms=2001, broker_ok=False, reconciled=False)
    assert action == "RECONCILE_NO_RESEND" and p.hard_halt
    p, action = step(p, now_ms=2002, closed=True)
    assert action == "CLOSED_CONFIRMED" and p.hard_halt
    p, action = step(p, now_ms=2003)
    assert action == "RECONCILE_NO_RESEND"


def test_protection_failed_repair_exit_and_storage_clock_faults():
    p, _ = step(protection())
    p, action = step(p, rejected=True, now_ms=500)
    assert action == "CONTROLLED_EXIT_ONCE"
    p, action = step(p, rejected=True, now_ms=501)
    assert action == "ALERT_EXIT_REJECTED" and p.hard_halt
    assert step(protection(), now_ms=1000)[1] == "CONTROLLED_EXIT_ONCE"
    assert step(protection(), storage_ok=False)[1] == "ALERT_STORAGE_NO_MUTATION"
    assert step(protection(), boot_id="new-boot")[1] == "RECONCILE_CLOCK_NO_MUTATION"
    assert step(protection(last_ms=101))[1] == "RECONCILE_CLOCK_NO_MUTATION"
    settled, action = step(protection(phase="PROTECTED"), now_ms=3000, protected=True)
    assert action == "PROTECTED_CONFIRMED" and not settled.hard_halt


KEY, SCOPE = b"k" * 32, "a" * 64


def append(j, value=None, **patch):
    event_id = patch.pop("event_id", "event-1")
    value = value or {"hard_halt": True, "reservation": "unknown-full-reserve"}
    args = (
        dict(owner="one", epoch=1, sequence=1, now_ms=1100, clock_error_ms=10, expires_ms=5500)
        | patch
    )
    signature = seal(
        KEY,
        SCOPE,
        args["epoch"],
        args["sequence"],
        args["expires_ms"],
        canonical({"id": event_id, "body": value}),
    )
    return j.append(event_id, value, **args, signature=signature)


def test_durable_idempotency_fencing_conflict_and_restart(tmp_path):
    path = tmp_path / "safety.db"
    with pytest.raises(ValueError, match="missing"):
        SafetyJournal(path, SCOPE, key=KEY)
    journal = SafetyJournal(path, SCOPE, key=KEY, bootstrap=True)
    assert (
        journal.acquire(
            "one",
            1000,
            5000,
            reconciled=True,
            clock_error_ms=10,
            peer_checkpoint=journal.checkpoint(),
        )
        == 1
    )
    assert append(journal)
    assert not append(journal, now_ms=1200)
    assert len(journal.verify()) == 1
    with pytest.raises(ValueError, match="conflict"):
        append(journal, {"hard_halt": False}, now_ms=1200)
    with pytest.raises(ValueError, match="sequence"):
        append(journal, sequence=3, event_id="gap", now_ms=1200)
    second = SafetyJournal(path, SCOPE, key=KEY)
    with pytest.raises(ValueError, match="active"):
        second.acquire(
            "two",
            2000,
            5000,
            reconciled=True,
            clock_error_ms=10,
            peer_checkpoint=second.checkpoint(),
        )
    assert (
        second.acquire(
            "two",
            6010,
            5000,
            reconciled=True,
            clock_error_ms=10,
            peer_checkpoint=second.checkpoint(),
        )
        == 2
    )
    with pytest.raises(ValueError, match="fenced"):
        append(journal, now_ms=6100)
    journal.close()
    second.close()
    reopened = SafetyJournal(path, SCOPE, key=KEY)
    assert reopened.verify() == [{"hard_halt": True, "reservation": "unknown-full-reserve"}]
    reopened.close()
    with pytest.raises(ValueError, match="account mismatch"):
        SafetyJournal(path, "b" * 64, key=KEY)


def test_authentication_expiry_clock_and_corruption(tmp_path):
    j = SafetyJournal(tmp_path / "s.db", SCOPE, key=KEY, bootstrap=True)
    j.acquire("one", 1000, 5000, reconciled=True, clock_error_ms=10, peer_checkpoint=j.checkpoint())
    with pytest.raises(ValueError, match="authentication"):
        j.append(
            "event",
            {},
            owner="one",
            epoch=1,
            sequence=1,
            now_ms=1100,
            clock_error_ms=10,
            expires_ms=5000,
            signature="0" * 64,
        )
    for patch in ({"now_ms": 5490}, {"now_ms": 999}, {"clock_error_ms": 101}):
        with pytest.raises(ValueError, match="fenced"):
            append(j, **patch)
    assert append(j)
    j.db.execute("UPDATE events SET body='{}'")
    with pytest.raises(ValueError, match="integrity"):
        j.verify()
    j.close()


def shadow(snapshot=None, state=None, native=None, **patch):
    snapshot = snapshot or vector()
    raw = json.loads((ROOT / "tests/fixtures/ea_protocol/request.json").read_text())["payload"]
    raw.update(snapshot_hash=payload_hash(snapshot), max_risk="25")
    from fx_talanta.domain.ea_protocol import ExecutionRequest

    work = Envelope.seal(ExecutionRequest.model_validate(raw))
    return shadow_preflight(
        work,
        snapshot,
        state or loss_state(owner_pause=False),
        **(
            dict(
                account=work.payload.account,
                release_hash="a" * 64,
                policy_hash="a" * 64,
                now=datetime(2026, 1, 5, 12, 0, 1, tzinfo=UTC),
                storage_ok=True,
                fenced=True,
                native_result=evaluate(snapshot) if native is None else native,
            )
            | patch
        ),
    )


def test_request_composes_persisted_state_and_native_disagreement():
    assert shadow()["reason"] == "ACCEPTED"
    assert shadow()["send_enabled"] is False
    assert shadow(state=loss_state(hard_halt=True))["reason"] == "HARD_HALT"
    assert shadow(state=loss_state())["reason"] == "OWNER_PAUSED"
    assert shadow(native={"reason": "MINIMUM_LOT"})["reason"] == "NATIVE_PARITY_BLOCK"
    native = evaluate(vector()) | {"volume": "0.10"}
    assert shadow(native=native)["reason"] == "NATIVE_PARITY_BLOCK"
    assert shadow(fenced=False)["reason"] == "STORAGE_OR_FENCE_BLOCK"
    assert shadow(release_hash="b" * 64)["reason"] == "RELEASE_POLICY_MISMATCH"
    assert shadow(now=datetime(2026, 1, 5, 12, 0, 2, tzinfo=UTC))["reason"] == "QUOTE_STALE"
    assert (
        shadow(now=datetime(2026, 1, 5, 12, 0, tzinfo=UTC) - timedelta(seconds=1))["reason"]
        == "SNAPSHOT_FUTURE"
    )


def test_native_evidence_matches_checked_sources(historical_source):
    evidence = json.loads((ROOT / "docs/evidence/m2c-native-20261103.json").read_text())
    assert evidence["all_pass"] and evidence["shadow_compute_pass"] and evidence["hmac_parity"]
    assert len(evidence["results"]) == len(SOURCE["cases"])
    assert evidence["native_failures"] == 0
    for path, digest in evidence["source_sha256"].items():
        assert hashlib.sha256(historical_source(path, digest)).hexdigest() == digest, path


def test_partial_exposure_remaining_reserve_and_unknowns():
    from fx_talanta.safety.exposure import Position, Reservation, aggregate

    p = Position(
        scope=SCOPE,
        position_id="position",
        reservation_id="reserve",
        symbol="EURUSD",
        side="BUY",
        volume="0.04",
        liquidation="1.1",
        stop="1.098",
        contract="100000",
        base_to_account="1.1",
        quote_to_account="1",
        exit_cost_per_lot="4",
        margin="88",
        owned=True,
    )
    r = Reservation(
        scope=SCOPE,
        reservation_id="reserve",
        symbol="EURUSD",
        side="BUY",
        authorized_volume="0.09",
        cumulative_filled="0.04",
        pending_confirmed="0.05",
        final_order=False,
        outcome_unknown=False,
        risk_per_lot="233",
        gross_per_lot="110000",
        counter_per_lot="110020",
        margin_per_lot="2200",
    )
    result = aggregate(SCOPE, (p,), (r,))
    assert (result["risk"], result["gross"], result["margin"], result["occupied_slots"]) == (
        D("19.81"),
        D(9900),
        D(198),
        1,
    )
    assert result["currencies"] == {"EUR": D(9900), "USD": D(-9901)}
    result = aggregate(SCOPE, (p,), (r.model_copy(update={"outcome_unknown": True}),))
    assert result["flags"] == 4 and result["risk"] == D("19.81")
    final = r.model_copy(update={"final_order": True, "pending_confirmed": D(0)})
    assert aggregate(SCOPE, (p,), (final,))["risk"] == D("8.16")
    assert aggregate(SCOPE, (p.model_copy(update={"stop": None}),), (r,))["flags"] == 8
    assert aggregate(SCOPE, (p.model_copy(update={"owned": False}),), (r,))["flags"] == 32
    with pytest.raises(ValueError, match="allocation"):
        aggregate(SCOPE, (p,), (r.model_copy(update={"authorized_volume": D("0.08")}),))
    with pytest.raises(ValueError, match="mixed account"):
        aggregate("b" * 64, (p,), (r,))


def test_retained_peer_checkpoint_rejects_valid_prefix_restore(tmp_path):
    j = SafetyJournal(tmp_path / "s.db", SCOPE, key=KEY, bootstrap=True)
    j.acquire("one", 1000, 5000, reconciled=True, clock_error_ms=10, peer_checkpoint=j.checkpoint())
    append(j)
    peer = j.checkpoint()
    j.db.execute("DELETE FROM events")  # Simulate restoring an older, internally valid file.
    with pytest.raises(ValueError, match="checkpoint"):
        j.acquire("two", 6010, 5000, reconciled=True, clock_error_ms=10, peer_checkpoint=peer)
    j.close()
