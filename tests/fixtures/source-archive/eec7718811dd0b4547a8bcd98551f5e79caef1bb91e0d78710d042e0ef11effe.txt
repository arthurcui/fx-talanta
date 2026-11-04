"""Durable bounded-demo budget; this component grants no execution permission.

Use a dedicated journal and retain its checkpoint outside that journal. Charges
are conservative: refusals and uncertain calls never refund an entry or risk.
An independently verified closure is required before another entry reservation.
Native dispatch, source qualification and the two-second rule remain separate.
"""

from dataclasses import asdict, dataclass

from fx_talanta.shadow.store import canonical
from fx_talanta.shadow.wire import digest
from fx_talanta.shadow.wire import hex64 as _hex64
from fx_talanta.shadow.work import scope_for


def hex64(value):
    return isinstance(value, str) and _hex64(value)


@dataclass(frozen=True)
class BudgetPlan:
    campaign: str
    starts_ms: int
    expires_ms: int
    entries: int = 2
    lot_units: int = 2_000_000  # 0.02 lot, using the native 1e8 lot unit.
    per_entry_cents: int = 500
    total_cents: int = 1000
    currency: str = "CAD"

    def __post_init__(self):
        numbers = (
            self.starts_ms,
            self.expires_ms,
            self.entries,
            self.lot_units,
            self.per_entry_cents,
            self.total_cents,
        )
        if (
            not hex64(self.campaign)
            or any(type(n) is not int or n <= 0 for n in numbers)
            or not 0 < self.expires_ms - self.starts_ms <= 300_000
            or self.entries > 2
            or self.lot_units > 2_000_000
            or not self.per_entry_cents <= self.total_cents <= 1000
            or self.per_entry_cents > 500
            or self.currency != "CAD"
        ):
            raise ValueError("INVALID_DEMO_BUDGET")


class AcceptanceBudget:
    """Trusted local admission component, not an HTTP activation endpoint.

    Store transactions serialize charges. A stale/missing external checkpoint refuses
    recovery; callers must never discover and adopt an unknown journal tip. Even a
    successful reservation is not a permit to call OrderSend or retry an unknown call.
    """

    def __init__(self, store, account, plan, *, bootstrap=False, expected_tip=None):
        if account.environment.value != "PAPER" or account.venue != "BROKER_DEMO":
            raise ValueError("BROKER_DEMO_REQUIRED")
        if not isinstance(plan, BudgetPlan):
            raise ValueError("INVALID_DEMO_BUDGET")
        self.store, self.plan = store, plan
        self.binding = {
            "kind": "demo_budget_binding",
            "scope": scope_for(account),
            "plan": asdict(plan),
            "execution_enabled": False,
        }
        self.binding_hash = digest(canonical(self.binding))
        with store.transaction() as events:
            if bootstrap:
                if events.records or expected_tip is not None:
                    raise ValueError("BUDGET_ALREADY_EXISTS")
                events.append(self.binding)
            elif not hex64(expected_tip) or events.tip != expected_tip:
                raise ValueError("BUDGET_CHECKPOINT_REQUIRED")
            if not events.records or events.records[0] != self.binding:
                raise ValueError("BUDGET_BINDING_MISMATCH")
            tip = events.tip
        self.tip = tip

    def _check(self, events, now_ms):
        if events.tip != self.tip or events.records[0] != self.binding:
            raise ValueError("BUDGET_CHECKPOINT_MISMATCH")
        last = max(e.get("at_ms", self.plan.starts_ms) for e in events.records)
        if type(now_ms) is not int or now_ms < last:
            raise ValueError("BUDGET_TIME_REGRESSION")

    def reserve(self, request_hash, symbol, lot_units, risk_cents, now_ms):
        if (
            not hex64(request_hash)
            or symbol not in {"EURUSD", "USDJPY"}
            or type(lot_units) is not int
            or not 0 < lot_units <= self.plan.lot_units
            or type(risk_cents) is not int
            or not 0 < risk_cents <= self.plan.per_entry_cents
        ):
            raise ValueError("BUDGET_ENTRY_INVALID")
        with self.store.transaction() as events:
            self._check(events, now_ms)
            if not self.plan.starts_ms <= now_ms < self.plan.expires_ms:
                raise ValueError("BUDGET_ENTRY_WINDOW_CLOSED")
            charges = [e for e in events.records if e["kind"] == "demo_budget_charge"]
            if any(e["request_hash"] == request_hash for e in charges):
                # Idempotent bookkeeping must not become permission to dispatch twice.
                raise ValueError("BUDGET_ALREADY_CHARGED")
            closed = {
                e["request_hash"] for e in events.records if e["kind"] == "demo_budget_closed"
            }
            if any(e["request_hash"] not in closed for e in charges):
                raise ValueError("BUDGET_OUTCOME_UNRESOLVED")
            if len(charges) >= self.plan.entries or (
                sum(e["risk_cents"] for e in charges) + risk_cents > self.plan.total_cents
            ):
                raise ValueError("DEMO_BUDGET_EXHAUSTED")
            events.append(
                dict(
                    kind="demo_budget_charge",
                    request_hash=request_hash,
                    symbol=symbol,
                    lot_units=lot_units,
                    risk_cents=risk_cents,
                    at_ms=now_ms,
                )
            )
            tip = events.tip
        self.tip = tip
        return tip

    def record_verified_closure(self, request_hash, audit, now_ms):
        """Accept an independent auditor's positive closure, never position absence.

        This trusted call records a completed audit; a supplied hash alone does not
        verify broker truth. No network endpoint or EA claim may call it directly.
        Keep the referenced audit and actual entry/exit deal witnesses privately.
        """
        expected_fields = {
            "scope",
            "request_hash",
            "source",
            "evidence_sha256",
            "observed_at_ms",
            "entry_units",
            "exit_units",
            "open_positions",
            "pending_orders",
        }
        if (
            not isinstance(audit, dict)
            or set(audit) != expected_fields
            or audit["scope"] != self.binding["scope"]
            or audit["request_hash"] != request_hash
            or audit["source"] != "INDEPENDENT_BROKER_AUDIT"
            or not hex64(audit["evidence_sha256"])
            or any(
                type(audit[k]) is not int
                for k in (
                    "observed_at_ms",
                    "entry_units",
                    "exit_units",
                    "open_positions",
                    "pending_orders",
                )
            )
            or type(now_ms) is not int
            or not 0 <= now_ms - audit["observed_at_ms"] <= 2000
            or not 0 < audit["entry_units"] == audit["exit_units"]
            or audit["open_positions"] != 0
            or audit["pending_orders"] != 0
        ):
            raise ValueError("POSITIVE_INDEPENDENT_CLOSURE_REQUIRED")
        with self.store.transaction() as events:
            self._check(events, now_ms)
            charge = next(
                (
                    e
                    for e in events.records
                    if e["kind"] == "demo_budget_charge" and e["request_hash"] == request_hash
                ),
                None,
            )
            if (
                charge is None
                or audit["entry_units"] > charge["lot_units"]
                or audit["observed_at_ms"] < charge["at_ms"]
                or any(
                    e["kind"] == "demo_budget_closed"
                    and (
                        e["request_hash"] == request_hash
                        or e["audit"]["evidence_sha256"] == audit["evidence_sha256"]
                    )
                    for e in events.records
                )
            ):
                raise ValueError("BUDGET_CLOSURE_CONFLICT")
            # Allowed after entry expiry: expiry must not strand reconciliation.
            events.append(
                dict(
                    kind="demo_budget_closed", request_hash=request_hash, audit=audit, at_ms=now_ms
                )
            )
            tip = events.tip
        self.tip = tip
        return tip

    def status(self, now_ms):
        with self.store.transaction() as events:
            self._check(events, now_ms)
            charges = [e for e in events.records if e["kind"] == "demo_budget_charge"]
            closed = {
                e["request_hash"] for e in events.records if e["kind"] == "demo_budget_closed"
            }
            return dict(
                entries_charged=len(charges),
                risk_cents_charged=sum(e["risk_cents"] for e in charges),
                unresolved=sum(e["request_hash"] not in closed for e in charges),
                entry_window_open=self.plan.starts_ms <= now_ms < self.plan.expires_ms,
                checkpoint=self.tip,
                execution_enabled=False,
            )
