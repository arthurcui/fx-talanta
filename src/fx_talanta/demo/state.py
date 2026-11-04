"""Validate reconciled native states without granting submission or risk authority."""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid5

from fx_talanta.domain.ea_protocol import Envelope, ExecutionState, ReconciliationResult
from fx_talanta.shadow.wire import digest, hex64, integer


def decode_state(payload, request, now, previous=None):
    f = payload.split("\t")
    if len(f) != 14 or f[0] != "demo-state/1" or len(payload) > 4096:
        raise ValueError("INVALID_BROKER_STATE")
    p = request.payload
    if f[1] != str(p.message_id) or f[2] != request.digest:
        raise ValueError("BROKER_STATE_REQUEST_MISMATCH")
    revision, filled, opened, remaining, order, position, at, error = map(
        integer, [f[3], f[5], f[6], f[7], f[8], f[9], f[11], f[12]]
    )
    if (
        revision < 1
        or error > 100
        or at > now + error
        or at < int(p.created_at.timestamp() * 1000) - error
        or not hex64(f[13])
    ):
        raise ValueError("BROKER_STATE_TIME_OR_PROOF")
    units = Decimal(100000000)
    if (
        filled > p.max_volume * units
        or filled + remaining > p.max_volume * units
        or (p.action == "ENTER" and opened > filled)
    ):
        raise ValueError("BROKER_STATE_QUANTITIES")
    try:
        stop = Decimal(f[10])
    except Exception as exc:
        raise ValueError("INVALID_BROKER_STOP") from exc
    if (
        not stop.is_finite()
        or stop < 0
        or stop > Decimal(100000000)
        or stop.as_tuple().exponent < -8
    ):
        raise ValueError("INVALID_BROKER_STOP")
    if p.action != "ENTER":
        if f[4] not in {"CLOSED", "PROTECTED", "PROTECTION_PENDING"}:
            raise ValueError("UNCONFIRMED_BROKER_STATE")
        if p.action == "CLOSE" and (order == 0 or (opened > 0 and str(position) != p.position_id)):
            raise ValueError("BROKER_STATE_TARGET_MISMATCH")
        if p.action == "CANCEL" and (
            str(order) != p.order_id
            or position
            or filled
            or opened
            or remaining
            or f[4] != "CLOSED"
        ):
            raise ValueError("BROKER_STATE_CANCEL_CONFLICT")
        if p.action == "TIGHTEN_STOP" and (
            str(position) != p.position_id
            or order
            or filled
            or opened
            or remaining
            or stop <= 0
            or f[4] != "CLOSED"
        ):
            raise ValueError("BROKER_STATE_STOP_CONFLICT")
        if previous:
            old = Envelope.model_validate(previous["state"]).payload
            if (
                revision <= old.sequence
                or at < int(old.created_at.timestamp() * 1000)
                or filled / units < old.filled_volume
            ):
                raise ValueError("BROKER_STATE_REGRESSION")
        return (
            Envelope.seal(
                ReconciliationResult(
                    message_id=uuid5(p.message_id, f"broker-query:{revision}:{digest(payload)}"),
                    account=p.account,
                    sequence=revision,
                    created_at=datetime.fromtimestamp(at / 1000, UTC),
                    release_hash=p.release_hash,
                    policy_hash=p.policy_hash,
                    request_id=p.message_id,
                    request_hash=request.digest,
                    reservation_id=p.reservation_id,
                    predecessor_hash=previous["state"]["digest"] if previous else request.digest,
                    result="CONFIRMED",
                    filled_volume=filled / units,
                    released_volume=Decimal(0),
                    evidence=(f[13], digest(payload)),
                )
            ),
            remaining / units,
            error,
        )
    if f[4] not in {"PROTECTED", "PROTECTION_PENDING", "CLOSED"} or order == 0:
        raise ValueError("UNCONFIRMED_BROKER_STATE")
    protected = opened > 0 and stop > 0 and (stop >= p.stop if p.side == "BUY" else stop <= p.stop)
    if (
        (f[4] == "PROTECTED") != protected
        or (f[4] == "CLOSED") != (opened == 0)
        or (opened > 0 and position == 0)
        or (f[4] == "CLOSED" and remaining != 0)
    ):
        raise ValueError("BROKER_STATE_PROTECTION_CONFLICT")
    if previous:
        old = Envelope.model_validate(previous["state"]).payload
        if (
            revision <= old.sequence
            or at < int(old.created_at.timestamp() * 1000)
            or filled / units < old.filled_volume
        ):
            raise ValueError("BROKER_STATE_REGRESSION")
        if old.state == "CLOSED" and (opened or filled / units != old.filled_volume):
            raise ValueError("CLOSED_EXECUTION_CANNOT_REOPEN")
    message = ExecutionState(
        message_id=uuid5(p.message_id, f"broker-state:{revision}:{digest(payload)}"),
        account=p.account,
        sequence=revision,
        created_at=datetime.fromtimestamp(at / 1000, UTC),
        release_hash=p.release_hash,
        policy_hash=p.policy_hash,
        request_id=p.message_id,
        request_hash=request.digest,
        reservation_id=p.reservation_id,
        predecessor_hash=previous["state"]["digest"] if previous else request.digest,
        state=f[4],
        requested_volume=p.max_volume,
        filled_volume=filled / units,
        open_volume=opened / units,
        protected_volume=opened / units if protected else Decimal(0),
        broker_evidence=(f[13], digest(payload)),
        broker_order_id=str(order),
        broker_position_id=str(position) if position else None,
        accepted_stop=stop if stop else None,
        broker_time_basis="EA_VERIFIED_UTC_INTERVAL",
    )
    return Envelope.seal(message), remaining / units, error


def reconcile_claim(state):
    """Typed native-query claim. Does not release reservations or assert an audit pass."""
    p = state.payload
    if p.kind == "reconciliation_result":
        return state
    return Envelope.seal(
        ReconciliationResult(
            message_id=uuid5(p.message_id, "native-reconciliation"),
            account=p.account,
            sequence=p.sequence,
            created_at=p.created_at,
            release_hash=p.release_hash,
            policy_hash=p.policy_hash,
            request_id=p.request_id,
            request_hash=p.request_hash,
            reservation_id=p.reservation_id,
            predecessor_hash=state.digest,
            result="PROVEN_NOT_EXECUTED"
            if p.state == "CLOSED" and p.filled_volume == 0
            else "CONFIRMED",
            filled_volume=p.filled_volume,
            released_volume=Decimal(0),
            evidence=p.broker_evidence,
        )
    )
