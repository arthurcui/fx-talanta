import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5

import pytest
from pydantic import ValidationError

from fx_talanta.domain.ea_protocol import (
    ChannelTelemetry,
    DecisionIntent,
    Envelope,
    ExecutionAck,
    ExecutionRequest,
    ExecutionState,
    ReconciliationResult,
    canonical_bytes,
)
from fx_talanta.domain.models import Environment
from fx_talanta.execution_contracts.replay import (
    Allocation,
    ReferenceInbox,
    entry_reason,
    management_reason,
)
from fx_talanta.storage.config import fixture_account

D = Decimal
NOW = datetime(2026, 1, 5, 12, tzinfo=UTC)
ACCOUNT = fixture_account(Environment.PAPER)
HASH = "a" * 64


def uid(n):
    return UUID(int=n)


def message(**changes):
    return (
        dict(
            message_id=uid(1),
            account=ACCOUNT,
            sequence=1,
            created_at=NOW,
            release_hash=HASH,
            policy_hash=HASH,
        )
        | changes
    )


def request(**changes):
    return ExecutionRequest(
        **(
            message(
                expires_at=NOW + timedelta(seconds=60),
                intent_hash=HASH,
                snapshot_hash=HASH,
                reservation_id=uid(2),
                action="ENTER",
                symbol="EURUSD",
                broker_symbol="EURUSD",
                currency="USD",
                max_volume="0.09",
                max_risk="20.97",
                side="BUY",
                stop="1.098",
                target="1.1046",
            )
            | changes
        )
    )


def inbox(journal=()):
    return ReferenceInbox(ACCOUNT, HASH, HASH, journal)


def receive(box, envelope, now=None, **extra):
    return box.receive(
        envelope, now or NOW + timedelta(seconds=1), clock_uncertainty_ms=D(10), **extra
    )


def test_decimal_canonicalization_and_utc_are_stable():
    first = request(max_volume="0.0900", max_risk="20.97000")
    second = request()
    assert canonical_bytes(first) == canonical_bytes(second)
    assert Envelope.seal(first).digest == Envelope.seal(second).digest
    raw = second.model_dump(mode="json")
    raw["created_at"] = "2026-01-05T04:00:00-08:00"
    assert canonical_bytes(ExecutionRequest.model_validate(raw)) == canonical_bytes(second)


@pytest.mark.parametrize("value", [0.09, 1, True, "NaN", "Infinity", "-0.01", "0"])
def test_wire_decimal_requires_finite_positive_string(value):
    with pytest.raises(ValidationError):
        request(max_volume=value)


@pytest.mark.parametrize(
    "change",
    [
        {"version": "ea-protocol/2"},
        {"surprise": 1},
        {"sequence": True},
        {"sequence": 0},
        {"created_at": datetime(2026, 1, 5)},
        {"expires_at": NOW},
        {"side": None},
        {"stop": None},
    ],
)
def test_malformed_command_fails_closed(change):
    with pytest.raises(ValidationError):
        request(**change)


def test_digest_tampering_rejected_before_inbox():
    raw = Envelope.seal(request()).model_dump(mode="json")
    raw["payload"]["max_risk"] = "1000"
    with pytest.raises(ValidationError, match="payload hash mismatch"):
        inbox().receive(json.dumps(raw), NOW, clock_uncertainty_ms=D(0))


def test_replay_after_restart_and_expiry_has_no_new_allocation():
    box, e = inbox(), Envelope.seal(request())
    assert receive(box, e) == ("ACCEPTED", False)
    saved = json.loads(json.dumps(box.rows))
    restored = inbox(saved)
    assert receive(restored, e, NOW + timedelta(days=1)) == ("ACCEPTED", True)
    assert len(restored.rows) == len(restored.reservations) == 1
    conflict = Envelope.seal(request(max_risk="21"))
    assert receive(restored, conflict) == ("HASH_CONFLICT", False)


@pytest.mark.parametrize(
    "change,reason",
    [
        ({"account": ACCOUNT.model_copy(update={"login": "other-fixture"})}, "ACCOUNT_MISMATCH"),
        ({"release_hash": "b" * 64}, "RELEASE_MISMATCH"),
        ({"policy_hash": "b" * 64}, "POLICY_MISMATCH"),
        ({"sequence": 2}, "SEQUENCE_GAP"),
    ],
)
def test_identity_and_ordering_fail_closed(change, reason):
    assert receive(inbox(), Envelope.seal(request(**change))) == (reason, False)


def test_reservation_cannot_be_consumed_by_second_request():
    box = inbox()
    receive(box, Envelope.seal(request()))
    e = Envelope.seal(request(message_id=uid(3), sequence=2))
    assert receive(box, e) == ("RESERVATION_CONFLICT", False)
    assert len(box.rows) == 1


def test_corrupt_checkpoint_and_duplicate_rows_rejected():
    box = inbox()
    receive(box, Envelope.seal(request()))
    with pytest.raises(ValueError):
        inbox(box.rows * 2)
    rows = json.loads(json.dumps(box.rows))
    rows[0]["envelope"]["payload"]["max_risk"] = "9999"
    with pytest.raises(ValueError):
        inbox(rows)


def test_expiry_clock_bounds_and_stale_close():
    close = Envelope.seal(
        request(action="CLOSE", max_risk="0", position_id="owned-fixture", expected_state_version=3)
    )
    assert receive(inbox(), close, state_version=4)[0] == "STATE_MISMATCH"
    assert receive(inbox(), close, state_version=3, now=NOW + timedelta(seconds=60))[0] == "EXPIRED"
    assert receive(inbox(), close, state_version=3)[0] == "ACCEPTED"
    assert (
        receive(inbox(), Envelope.seal(request()), now=NOW - timedelta(seconds=1))[0]
        == "FUTURE_MESSAGE"
    )
    assert (
        inbox().receive(Envelope.seal(request()), NOW, clock_uncertainty_ms=D("NaN"))[0]
        == "CLOCK_UNCERTAIN"
    )


def reconciliation(req, **changes):
    return Envelope.seal(
        ReconciliationResult(
            **(
                message(
                    message_id=uid(8),
                    request_id=req.payload.message_id,
                    request_hash=req.digest,
                    reservation_id=req.payload.reservation_id,
                    predecessor_hash=req.digest,
                    result="CONFIRMED",
                    filled_volume="0.03",
                    released_volume="0",
                    evidence=(HASH,),
                )
                | changes
            )
        )
    )


def test_partial_fill_and_unknown_remainder_do_not_double_count():
    req = Envelope.seal(request())
    a = Allocation(req)
    part = reconciliation(req)
    a.reconcile(part)
    assert (a.filled, a.reserved, a.released) == (D("0.03"), D("0.06"), D(0))
    assert (a.filled + a.reserved) * D(233) == D("20.97")
    a.reconcile(part)
    assert len(a.events) == 1
    unknown = reconciliation(
        req, message_id=uid(9), sequence=2, predecessor_hash=part.digest, result="UNKNOWN"
    )
    a.reconcile(unknown)
    assert a.reserved == D("0.06")
    released = reconciliation(
        req, message_id=uid(10), sequence=3, predecessor_hash=unknown.digest, released_volume="0.06"
    )
    a.reconcile(released)
    assert a.reserved == 0 and a.filled == D("0.03")


@pytest.mark.parametrize(
    "change",
    [
        {"filled_volume": "0.10"},
        {"sequence": 2},
        {"predecessor_hash": "b" * 64},
        {"reservation_id": uid(99)},
        {"request_hash": "b" * 64},
    ],
)
def test_reconciliation_cannot_overconsume_or_cross_scope(change):
    req = Envelope.seal(request())
    with pytest.raises(ValueError):
        Allocation(req).reconcile(reconciliation(req, **change))


@pytest.mark.parametrize(
    "change",
    [
        {"result": "UNKNOWN", "released_volume": "0.01"},
        {"evidence": ()},
        {"result": "PROVEN_NOT_EXECUTED"},
    ],
)
def test_unknown_or_empty_history_never_proves_release(change):
    req = Envelope.seal(request())
    with pytest.raises(ValidationError):
        reconciliation(req, **change)


def test_ack_is_not_a_fill_and_state_requires_evidence():
    fields = message(request_id=uid(2), request_hash=HASH, reservation_id=uid(3))
    ack = ExecutionAck(**fields, stage="EA_RECEIVED", reason="ACCEPTED")
    assert "filled_volume" not in ack.model_dump()
    with pytest.raises(ValidationError):
        ExecutionAck(**fields, stage="REJECTED", reason="ACCEPTED")
    state = dict(
        predecessor_hash=HASH,
        state="PROTECTED",
        requested_volume="0.09",
        filled_volume="0.09",
        open_volume="0.09",
        protected_volume="0.09",
        broker_time_basis="fixture-UTC",
    )
    with pytest.raises(ValidationError):
        ExecutionState(**fields, **state)
    assert ExecutionState(
        **fields,
        **state,
        broker_evidence=(HASH,),
        broker_position_id="fixture-pos",
        accepted_stop="1.098",
    )


def test_unknown_state_cannot_fabricate_confirmed_fill_or_protection():
    fields = message(
        request_id=uid(2),
        request_hash=HASH,
        reservation_id=uid(3),
        predecessor_hash=HASH,
        state="OUTCOME_UNKNOWN",
        requested_volume="0.09",
        filled_volume="0.03",
        open_volume="0.03",
        protected_volume="0.03",
        broker_time_basis="fixture-UTC",
        broker_position_id="fixture-pos",
    )
    with pytest.raises(ValidationError):
        ExecutionState(**fields)
    with pytest.raises(ValidationError):
        ExecutionState(**fields, broker_evidence=(HASH,))
    assert ExecutionState(**fields, broker_evidence=(HASH,), accepted_stop="1.098")


def test_proposal_has_no_authority_and_validates_evidence_cutoff():
    intent = DecisionIntent(
        **message(),
        expires_at=NOW + timedelta(seconds=60),
        cutoff=NOW,
        evidence=(HASH,),
        decision_id=uid(2),
        strategy="fixture/1",
        action="ENTER",
        symbol="EURUSD",
        candidate_id=uid(3),
        side="BUY",
    )
    assert receive(inbox(), Envelope.seal(intent)) == ("UNSUPPORTED", False)
    with pytest.raises(ValidationError):
        DecisionIntent.model_validate(intent.model_dump() | {"cutoff": NOW + timedelta(seconds=1)})


def test_composed_gates_preserve_two_second_entry_ceiling():
    gates = dict(
        hard_halt=False,
        loss_pause=False,
        outcome_unknown=False,
        protection_pending=False,
        owner_pause=False,
        input_health=True,
        quote_age=D(2),
    )
    assert entry_reason(**gates) is None
    assert entry_reason(**(gates | {"quote_age": D("2.001")})) == "STALE_QUOTE"
    assert entry_reason(**(gates | {"outcome_unknown": True})) == "UNKNOWN_OUTCOME"
    assert entry_reason(**(gates | {"owner_pause": False, "hard_halt": True})) == "LOSS_BLOCK"
    assert (
        entry_reason(**(gates | {"owner_pause": False, "protection_pending": True}))
        == "HEALTH_BLOCK"
    )
    assert (
        management_reason(owned=True, reconciled=True, mutation_unknown=True, expected=1, current=1)
        == "UNKNOWN_OUTCOME"
    )
    assert (
        management_reason(
            owned=False, reconciled=True, mutation_unknown=False, expected=1, current=1
        )
        == "NOT_OWNED"
    )


@pytest.mark.parametrize("channel", ["EA", "PYTHON_PACKAGE", "MCP"])
def test_healthy_heartbeat_never_refreshes_quote(channel):
    telemetry = ChannelTelemetry(
        account=ACCOUNT,
        symbol="EURUSD",
        channel=channel,
        capability="QUOTES",
        state="HEALTHY",
        measured_at=NOW,
        last_heartbeat=NOW,
        last_success=NOW,
        original_tick_at=NOW - timedelta(seconds=30),
        last_quote_receipt=NOW,
    )
    assert telemetry.quote_age_seconds(NOW) == 30 and not telemetry.quote_fresh(NOW)
    assert telemetry.delivery_median_ms is None


def test_missing_and_future_ticks_are_not_fresh_and_latency_requires_samples():
    fields = dict(
        account=ACCOUNT,
        symbol="EURUSD",
        channel="MCP",
        capability="QUOTES",
        state="NOT_CONFIGURED",
        measured_at=NOW,
    )
    assert not ChannelTelemetry(**fields).quote_fresh(NOW)
    assert not ChannelTelemetry(**fields, original_tick_at=NOW + timedelta(seconds=1)).quote_fresh(
        NOW
    )
    with pytest.raises(ValidationError):
        ChannelTelemetry(**fields, delivery_median_ms="47")


def test_fixture_native_source_has_no_external_or_trading_capabilities():
    path = Path(__file__).resolve().parents[1] / "tests/native/offline/ProtocolReference.mq5"
    source = path.read_text(encoding="utf-8")
    for forbidden in (
        "OrderSend",
        "CTrade",
        "#import",
        "WebRequest",
        "Socket",
        "SymbolInfo",
        "AccountInfo",
        "FILE_COMMON",
        "OnTick",
    ):
        assert forbidden not in source
    assert "void OnStart()" in source and "MathFloor" in source


def test_shared_replay_vectors_against_real_envelopes():
    path = Path(__file__).resolve().parents[1] / "tests/fixtures/ea_protocol/replay.json"
    cases = json.loads(path.read_text(encoding="utf-8"))["cases"]
    box = inbox()
    for case in cases:
        fields = dict(
            version=case["version"],
            message_id=uuid5(NAMESPACE_URL, case["request"]),
            reservation_id=uuid5(NAMESPACE_URL, "reservation/" + case["request"]),
            sequence=case["sequence"],
            max_risk="20.97" if case["hash"] == HASH else "21",
            expires_at=NOW + timedelta(seconds=case["expires"]),
        )
        if case["account"] != "fixture-usd":
            fields["account"] = ACCOUNT.model_copy(update={"login": "other-fixture"})
        if case["version"] != "ea-protocol/1":
            with pytest.raises(ValidationError):
                request(**fields)
            continue
        code, replay = box.receive(
            Envelope.seal(request(**fields)),
            NOW + timedelta(seconds=case["now"]),
            clock_uncertainty_ms=D(0),
        )
        actual = ("REPLAY" if code == "ACCEPTED" else "REPLAY_" + code) if replay else code
        assert actual == case["expected"], case["id"]


def test_channel_fixture_scope_and_missing_metrics():
    path = Path(__file__).resolve().parents[1] / "tests/fixtures/ea_protocol/channels.json"
    for data in json.loads(path.read_text(encoding="utf-8")):
        telemetry = ChannelTelemetry(account=ACCOUNT, symbol="EURUSD", **data)
        assert not telemetry.quote_fresh(telemetry.measured_at)
        if telemetry.channel != "EA":
            assert telemetry.delivery_median_ms is None


def test_reconciliation_conflicts_and_regression_keep_existing_allocation():
    req = Envelope.seal(request())
    allocation = Allocation(req)
    first = reconciliation(req)
    allocation.reconcile(first)
    for event in (
        reconciliation(req, filled_volume="0.04"),
        reconciliation(
            req, message_id=uid(9), sequence=2, predecessor_hash=first.digest, filled_volume="0.02"
        ),
    ):
        with pytest.raises(ValueError):
            allocation.reconcile(event)
        assert allocation.filled == D("0.03") and allocation.reserved == D("0.06")
