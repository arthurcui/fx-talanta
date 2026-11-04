"""Durable bounded-demo budget; this component grants no execution permission.

Use a dedicated journal and retain its checkpoint outside that journal. Charges
are conservative: refusals and uncertain calls never refund an entry or risk.
An independently verified closure or definite no-execution audit is required
before another entry reservation. Neither outcome refunds the original charge.
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
    reference_equity_cents: int
    equity_evidence_hash: str
    entries: int = 2
    lot_units: int = 2_000_000  # 0.02 lot, using the native 1e8 lot unit.
    per_entry_bps: int = 25
    total_bps: int = 50
    currency: str = "CAD"

    def __post_init__(self):
        numbers = (
            self.starts_ms,
            self.expires_ms,
            self.entries,
            self.lot_units,
            self.reference_equity_cents,
            self.per_entry_bps,
            self.total_bps,
        )
        if (
            not hex64(self.campaign)
            or not hex64(self.equity_evidence_hash)
            or self.equity_evidence_hash == "0" * 64
            or any(type(n) is not int or n <= 0 for n in numbers)
            or not 0 < self.expires_ms - self.starts_ms <= 300_000
            or self.entries > 2
            or self.lot_units > 2_000_000
            or not self.per_entry_bps <= self.total_bps <= 50
            or self.per_entry_bps > 25
            or self.reference_equity_cents > 1_000_000_000_000
            or self.currency not in {"CAD", "USD"}
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
            "schema": "percentage-budget/2",
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
        # A future plan can be inspected during disabled warm-up. Only recorded
        # events establish a monotonic watermark; the entry start is not an event.
        last = max(e.get("at_ms", 0) for e in events.records)
        if type(now_ms) is not int or now_ms < last:
            raise ValueError("BUDGET_TIME_REGRESSION")

    def _expired(self, now_ms):
        with self.store.transaction() as events:
            self._check(events, now_ms)
            expired = any(e["kind"] == "demo_budget_expired" for e in events.records)
            if now_ms >= self.plan.expires_ms and not expired:
                events.append(
                    dict(kind="demo_budget_expired", at_ms=now_ms, execution_enabled=False)
                )
                expired = True
            tip = events.tip
        self.tip = tip
        return expired

    def reserve(
        self, request_hash, symbol, lot_units, risk_cents, now_ms, *, eligible_equity_cents
    ):
        if (
            not hex64(request_hash)
            or symbol not in {"EURUSD", "USDJPY"}
            or type(lot_units) is not int
            or not 0 < lot_units <= self.plan.lot_units
            or type(risk_cents) is not int
            or risk_cents <= 0
            or type(eligible_equity_cents) is not int
            or not 0 < eligible_equity_cents <= 1_000_000_000_000
        ):
            raise ValueError("BUDGET_ENTRY_INVALID")
        if self._expired(now_ms):
            raise ValueError("BUDGET_ENTRY_WINDOW_CLOSED")
        with self.store.transaction() as events:
            self._check(events, now_ms)
            if not self.plan.starts_ms <= now_ms < self.plan.expires_ms:
                raise ValueError("BUDGET_ENTRY_WINDOW_CLOSED")
            charges = [e for e in events.records if e["kind"] == "demo_budget_charge"]
            if any(e["request_hash"] == request_hash for e in charges):
                # Idempotent bookkeeping must not become permission to dispatch twice.
                raise ValueError("BUDGET_ALREADY_CHARGED")
            closed = {
                e["request_hash"]
                for e in events.records
                if e["kind"] in {"demo_budget_closed", "demo_budget_no_execution"}
            }
            if any(e["request_hash"] not in closed for e in charges):
                raise ValueError("BUDGET_OUTCOME_UNRESOLVED")
            basis = min(
                self.plan.reference_equity_cents,
                eligible_equity_cents,
                *(e["equity_basis_cents"] for e in charges),
            )
            if risk_cents * 10_000 > basis * self.plan.per_entry_bps:
                raise ValueError("BUDGET_ENTRY_INVALID")
            if len(charges) >= self.plan.entries or (
                (sum(e["risk_cents"] for e in charges) + risk_cents) * 10_000
                > basis * self.plan.total_bps
            ):
                raise ValueError("DEMO_BUDGET_EXHAUSTED")
            events.append(
                dict(
                    kind="demo_budget_charge",
                    request_hash=request_hash,
                    symbol=symbol,
                    lot_units=lot_units,
                    risk_cents=risk_cents,
                    equity_basis_cents=basis,
                    at_ms=now_ms,
                    execution_enabled=False,
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
                    e["kind"] in {"demo_budget_closed", "demo_budget_no_execution"}
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
                    kind="demo_budget_closed",
                    request_hash=request_hash,
                    audit=audit,
                    at_ms=now_ms,
                    execution_enabled=False,
                )
            )
            tip = events.tip
        self.tip = tip
        return tip

    def record_verified_no_execution(self, request_hash, audit, now_ms):
        """Record a trusted local audit of a durable pre-submission rejection.

        Position absence alone is insufficient. The auditor must independently
        validate the authenticated native receipt, complete native journal and
        unchanged broker order/deal history. This is not a network operation or
        permission to replay the request. Keep all underlying evidence privately.
        """
        fields = {
            "scope",
            "request_hash",
            "source",
            "evidence_sha256",
            "observed_at_ms",
            "native_receipt_sha256",
            "native_journal_tip",
            "native_state",
            "native_mutation_attempts",
            "native_submission_started",
            "broker_history_unchanged",
            "open_positions",
            "pending_orders",
        }
        if (
            not isinstance(audit, dict)
            or set(audit) != fields
            or audit["scope"] != self.binding["scope"]
            or audit["request_hash"] != request_hash
            or audit["source"] != "INDEPENDENT_NO_EXECUTION_AUDIT"
            or any(
                not hex64(audit[k])
                for k in ("evidence_sha256", "native_receipt_sha256", "native_journal_tip")
            )
            or any(
                type(audit[k]) is not int
                for k in (
                    "observed_at_ms",
                    "native_mutation_attempts",
                    "open_positions",
                    "pending_orders",
                )
            )
            or type(now_ms) is not int
            or not 0 <= now_ms - audit["observed_at_ms"] <= 2000
            or audit["native_state"] != "REJECTED"
            or audit["native_mutation_attempts"] != 0
            or audit["native_submission_started"] is not False
            or audit["broker_history_unchanged"] is not True
            or audit["open_positions"] != 0
            or audit["pending_orders"] != 0
        ):
            raise ValueError("POSITIVE_NO_EXECUTION_AUDIT_REQUIRED")
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
                or audit["observed_at_ms"] < charge["at_ms"]
                or any(
                    e["kind"] in {"demo_budget_closed", "demo_budget_no_execution"}
                    and (
                        e["request_hash"] == request_hash
                        or e["audit"]["evidence_sha256"] == audit["evidence_sha256"]
                    )
                    for e in events.records
                )
            ):
                raise ValueError("BUDGET_CLOSURE_CONFLICT")
            events.append(
                dict(
                    kind="demo_budget_no_execution",
                    request_hash=request_hash,
                    audit=audit,
                    at_ms=now_ms,
                    execution_enabled=False,
                )
            )
            tip = events.tip
        self.tip = tip
        return tip

    def status(self, now_ms):
        self._expired(now_ms)
        with self.store.transaction() as events:
            self._check(events, now_ms)
            charges = [e for e in events.records if e["kind"] == "demo_budget_charge"]
            closed = {
                e["request_hash"]
                for e in events.records
                if e["kind"] in {"demo_budget_closed", "demo_budget_no_execution"}
            }
            return dict(
                entries_charged=len(charges),
                per_entry_percent=self.plan.per_entry_bps / 100,
                total_percent=self.plan.total_bps / 100,
                equity_basis_cents=min(
                    self.plan.reference_equity_cents, *(e["equity_basis_cents"] for e in charges)
                )
                if charges
                else self.plan.reference_equity_cents,
                risk_cents_charged=sum(e["risk_cents"] for e in charges),
                unresolved=sum(e["request_hash"] not in closed for e in charges),
                entry_window_open=self.plan.starts_ms <= now_ms < self.plan.expires_ms,
                checkpoint=self.tip,
                execution_enabled=False,
            )
