"""Pure safety transitions. Actions are recommendations, never broker calls."""

from datetime import date
from decimal import Decimal
from typing import Literal

from fx_talanta.domain.models import FrozenModel
from fx_talanta.safety.risk import Number, Positive, Signed

D = Decimal
ZERO = D(0)


class LossState(FrozenModel):
    day: date
    start: Positive
    day_flows: Signed = D(0)
    units: Positive
    high_nav: Positive = D(1)
    daily_loss: Number = D(0)
    loss_pause: bool = False
    hard_halt: bool = False
    owner_pause: bool = True


def losses(
    old: LossState,
    *,
    day: date,
    equity: Decimal,
    flow: Decimal = ZERO,
    equity_before_flow: Decimal | None = None,
    reconciled: bool,
    midnight_equity: Decimal | None = None,
) -> LossState:
    """Flow identity/dedup belongs to the durable journal, outside this pure reducer.

    A new UTC day requires a reconciled boundary equity, not the first late poll.
    Flow observations must be chronological; only classified flows reach here.
    """
    if not reconciled or day < old.day or equity <= 0:
        raise ValueError("unreconciled/invalid loss snapshot")
    units, high, hard = old.units, old.high_nav, old.hard_halt
    if flow:
        if equity_before_flow is None or equity_before_flow <= 0:
            raise ValueError("classified flow requires pre-flow equity")
        nav = equity_before_flow / units
        high = max(high, nav)
        hard |= equity_before_flow <= high * units * D("0.95")
        units += flow / nav
        if units <= 0:
            raise ValueError("cash flow exhausted units")
    nav = equity / units
    high = max(high, nav)
    hard |= equity <= high * units * D("0.95")
    new_day = day > old.day
    if new_day and (midnight_equity is None or midnight_equity <= 0 or flow):
        raise ValueError("UTC rollover requires boundary evidence before new-day flows")
    start = midnight_equity if new_day else old.start
    flows = D(0) if new_day else old.day_flows + flow
    loss = max(D(0), start + flows - equity)
    return LossState(
        day=day,
        start=start,
        day_flows=flows,
        units=units,
        high_nav=high,
        daily_loss=loss,
        loss_pause=(False if new_day else old.loss_pause) or loss >= start * D("0.01"),
        hard_halt=hard,
        owner_pause=old.owner_pause,
    )


class Protection(FrozenModel):
    """Deadlines are approved fixture parameters, not broker-qualified defaults."""

    phase: Literal[
        "PENDING",
        "REPAIRING",
        "EXITING",
        "UNKNOWN",
        "PROTECTED",
        "CLOSED",
        "REPAIR_REJECTED",
        "EXIT_REJECTED",
    ]
    submitted_ms: int
    repair_deadline_ms: int
    exit_deadline_ms: int
    last_ms: int
    boot_id: str
    hard_halt: bool = False


def protection_step(
    p: Protection,
    *,
    now_ms: int,
    boot_id: str,
    storage_ok: bool,
    broker_ok: bool,
    reconciled: bool,
    protected: bool,
    closed: bool,
    mutation_unknown: bool,
    rejected: bool = False,
) -> tuple[Protection, str]:
    """Persist returned state BEFORE the action; uncertain repair/exit is not retried.

    Reboot/monotonic rollback requires reconciliation and retained absolute evidence;
    this reducer cannot silently restart its elapsed timer or grant new deadlines.
    """
    if p.repair_deadline_ms <= p.submitted_ms or p.exit_deadline_ms <= p.repair_deadline_ms:
        raise ValueError("invalid deadlines")
    if not storage_ok:
        return p, "ALERT_STORAGE_NO_MUTATION"
    if boot_id != p.boot_id or now_ms < p.last_ms or now_ms < p.submitted_ms:
        return p.model_copy(update={"hard_halt": True}), "RECONCILE_CLOCK_NO_MUTATION"
    settled = (
        p.phase == "PROTECTED" and protected or p.phase == "CLOSED" and closed
    ) and reconciled
    update = {
        "last_ms": now_ms,
        "hard_halt": p.hard_halt or (not settled and now_ms >= p.exit_deadline_ms),
    }
    if p.phase == "CLOSED" and not closed:
        return p.model_copy(update=update | {"hard_halt": True}), "RECONCILE_NO_RESEND"
    if p.phase == "EXIT_REJECTED" or (rejected and reconciled and p.phase == "EXITING"):
        return p.model_copy(
            update=update | {"phase": "EXIT_REJECTED", "hard_halt": True}
        ), "ALERT_EXIT_REJECTED"
    if rejected and reconciled and p.phase == "REPAIRING":
        p = p.model_copy(update={"phase": "REPAIR_REJECTED"})
    if mutation_unknown or p.phase == "UNKNOWN":
        if not reconciled:
            return p.model_copy(update=update | {"phase": "UNKNOWN"}), "RECONCILE_NO_RESEND"
        if not closed and not protected:
            return p.model_copy(update=update | {"phase": "UNKNOWN"}), "RECONCILE_NO_RESEND"
    if reconciled and closed:
        return p.model_copy(update=update | {"phase": "CLOSED"}), "CLOSED_CONFIRMED"
    if reconciled and protected:
        return p.model_copy(update=update | {"phase": "PROTECTED"}), "PROTECTED_CONFIRMED"
    if not reconciled or not broker_ok:
        return p.model_copy(update=update), "ALERT_UNRESOLVED_NO_MUTATION"
    if p.phase in ("REPAIRING", "EXITING"):
        return p.model_copy(update=update | {"phase": "UNKNOWN"}), "RECONCILE_NO_RESEND"
    if now_ms >= p.repair_deadline_ms or p.phase == "REPAIR_REJECTED":
        return p.model_copy(update=update | {"phase": "EXITING"}), "CONTROLLED_EXIT_ONCE"
    return p.model_copy(update=update | {"phase": "REPAIRING"}), "ATTACH_STOP_ONCE"
