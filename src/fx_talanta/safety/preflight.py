"""Read-only M2A request -> composed M2C decision. Never dispatches an order."""

from datetime import datetime
from decimal import ROUND_CEILING, Decimal

from fx_talanta.domain.ea_protocol import Envelope, ExecutionRequest, payload_hash
from fx_talanta.domain.models import AccountIdentity, utc
from fx_talanta.safety.control import LossState
from fx_talanta.safety.risk import SafetyInput, evaluate


def shadow_preflight(
    envelope: Envelope,
    snapshot: SafetyInput,
    ledger: LossState,
    *,
    account: AccountIdentity,
    release_hash: str,
    policy_hash: str,
    now: datetime,
    storage_ok: bool,
    fenced: bool,
    native_result: dict[str, str] | None,
) -> dict:
    """Caller supplies authenticated native evidence; this is not a network API.

    No result, including ACCEPTED, enables sending. Disagreement is a veto.
    Full snapshot hashes, request digest and loss state belong in the caller's
    durable event, so offline decisions are reproducible.
    """

    def result(reason, **extra):
        return {"reason": reason, "send_enabled": False, **extra}

    work = envelope.payload
    if not isinstance(work, ExecutionRequest) or work.action != "ENTER":
        return result("ENTRY_ONLY_SHADOW")
    if work.account != account:
        return result("ACCOUNT_MISMATCH")
    if account.venue != "SIMULATOR":
        return result("CONNECTED_EXECUTION_DISABLED")
    if work.release_hash != release_hash or work.policy_hash != policy_hash:
        return result("RELEASE_POLICY_MISMATCH")
    if not storage_ok or not fenced:
        return result("STORAGE_OR_FENCE_BLOCK")
    now = utc(now)
    now_ms = Decimal(str(now.timestamp())) * 1000
    elapsed = int((now_ms - snapshot.measured_at_ms).to_integral_value(rounding=ROUND_CEILING))
    if elapsed < 0:
        return result("SNAPSHOT_FUTURE")
    error = Decimal(snapshot.clock_error_ms) / 1000
    if (
        Decimal(str((now - work.created_at).total_seconds())) < error
        or Decimal(str((work.expires_at - now).total_seconds())) <= error
    ):
        return result("EXPIRED_OR_FUTURE")
    if (
        work.snapshot_hash != payload_hash(snapshot)
        or ledger.day != now.date()
        or snapshot.day_start != ledger.start
        or snapshot.day_loss != ledger.daily_loss
        or (snapshot.symbol, snapshot.currency, snapshot.side, snapshot.stop)
        != (work.symbol, work.currency, work.side, work.stop)
    ):
        return result("SNAPSHOT_STATE_CONFLICT")
    flags = snapshot.flags | (1 if ledger.hard_halt else 0) | (2 if ledger.loss_pause else 0)
    flags |= 64 if ledger.owner_pause else 0
    value = snapshot.model_copy(
        update={
            "flags": flags,
            "request_volume": min(snapshot.request_volume, work.max_volume),
            "request_risk": min(snapshot.request_risk, work.max_risk),
            "quote_age_ms": snapshot.quote_age_ms + elapsed,
            "conversion_age_ms": snapshot.conversion_age_ms + elapsed,
            "expires_in_ms": min(
                snapshot.expires_in_ms - elapsed,
                int((work.expires_at - now).total_seconds() * 1000),
            ),
        }
    )
    backend = evaluate(value)
    if backend["reason"] != "ACCEPTED":
        return result(**backend)
    if native_result is None or native_result.get("reason") != "ACCEPTED":
        return result("NATIVE_PARITY_BLOCK")
    try:
        agrees = all(
            Decimal(native_result[k]) == Decimal(backend[k])
            for k in ("volume", "risk", "gross", "margin")
        )
    except (KeyError, ValueError, ArithmeticError):
        agrees = False
    if not agrees:
        return result("NATIVE_PARITY_BLOCK")
    return result(**backend)
