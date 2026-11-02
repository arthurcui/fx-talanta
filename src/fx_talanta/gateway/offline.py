"""Durable offline decision → reservation → submission → reconciliation loop."""

from datetime import timedelta
from decimal import Decimal
from threading import RLock
from uuid import UUID, uuid5

from fx_talanta.brokers.simulator import Simulator, UncertainOutcome
from fx_talanta.clock import Clock
from fx_talanta.domain.models import (
    AccountIdentity,
    Cost,
    EvidenceLink,
    ExecutionEvent,
    ExperienceCase,
    Record,
    RiskEvaluation,
    Versions,
)
from fx_talanta.domain.offline import (
    BrokerRequest,
    Entry,
    EntryIntent,
    GatewayBook,
    Market,
    Operation,
    Policy,
)
from fx_talanta.risk.governor import equity, exposure, health_reason, losses, size
from fx_talanta.storage.offline import OfflineStore
from fx_talanta.storage.repository import AccountMismatch, RecordConflict

ZERO = Decimal("0")
TERMINAL = {"COMPLETED", "REJECTED", "CANCELLED"}
ALLOWED = {
    "CREATED": {"VALIDATED", "REJECTED"},
    "VALIDATED": {"RESERVED", "REJECTED"},
    "RESERVED": {"SUBMITTING", "CANCELLED", "REJECTED"},
    "SUBMITTING": {"ACKNOWLEDGED", "PARTIALLY_FILLED", "FILLED", "REJECTED", "OUTCOME_UNKNOWN"},
    "OUTCOME_UNKNOWN": {"ACKNOWLEDGED", "PARTIALLY_FILLED", "FILLED", "REJECTED", "CANCELLED"},
    "ACKNOWLEDGED": {"PARTIALLY_FILLED", "FILLED", "CANCELLED", "OUTCOME_UNKNOWN"},
    "PARTIALLY_FILLED": {"FILLED", "PROTECTION_PENDING", "PROTECTED", "COMPLETED"},
    "FILLED": {"PROTECTION_PENDING", "PROTECTED", "COMPLETED"},
    "PROTECTION_PENDING": {"PROTECTED", "COMPLETED"},
    "PROTECTED": {"PROTECTION_PENDING", "COMPLETED"},
}


class SimulatedCrash(BaseException):
    """Failure injection that behaves like abrupt process termination."""


class Gateway:
    def __init__(
        self,
        dsn: str,
        account: AccountIdentity,
        run_id: UUID,
        clock: Clock,
        policy: Policy | None = None,
    ):
        policy = Policy.model_validate((policy or Policy()).model_dump(mode="json"))
        self.lock = RLock()
        self.store = OfflineStore(dsn, account, run_id, clock)
        self.clock, self.account, self.run_id = clock, account, run_id
        try:
            self.broker = Simulator(self.store, policy.capital)
            self.book = self.store.load("gateway") or GatewayBook(account=account, policy=policy)
            if self.book.policy != policy:
                raise ValueError("restart cannot change the persisted risk mandate")
            self.book = self.book.model_copy(update={"state": "STARTUP_RECONCILE"})
            self._save("STARTUP_RECONCILE")
        except BaseException:
            self.store.close()
            raise

    def close(self):
        self.store.close()

    def _save(self, event, records=()):
        self.store.save("gateway", self.book, event, records)

    def _record(self, body, refs=(), *, supersedes=None, costs=None):
        return Record(
            account=self.account,
            recorded_at=self.clock.now(),
            correlation_id=self.run_id,
            provenance="OFFLINE_SIMULATION",
            body=body,
            references=refs,
            supersedes=supersedes,
            costs=costs or Cost(),
            versions=Versions(component="m0b/0.2.0", policy=self.book.policy.version),
        )

    def entry(self, entry_id: UUID) -> Entry:
        return next(e for e in self.book.entries if e.intent.intent_id == entry_id)

    def _replace(self, entry: Entry):
        self.book = self.book.model_copy(
            update={
                "entries": tuple(
                    entry if e.intent.intent_id == entry.intent.intent_id else e
                    for e in self.book.entries
                )
            }
        )

    def _transition(self, entry: Entry, state: str, reason: str, **changes) -> Entry:
        if entry.state != state and state not in ALLOWED.get(entry.state, set()):
            raise ValueError(f"illegal order transition {entry.state} -> {state}")
        updated = entry.model_copy(update={"state": state, "reason": reason, **changes})
        positions = [p for p in self.broker.book.positions if p.entry_id == entry.intent.intent_id]
        position = positions[0] if positions else None
        refs = (EvidenceLink(record_id=entry.intent.decision_id, relation="DECISION"),)
        event = self._record(
            ExecutionEvent(
                request_id=entry.intent.intent_id,
                state=state,
                evidence=reason,
                order_id=str(entry.intent.intent_id) if entry.request else None,
                position_id=str(position.position_id) if position else None,
                filled_volume=position.volume if position else ZERO,
                fill_price=position.price if position else None,
            ),
            refs,
        )
        economic, pnl = "UNKNOWN", None
        if state == "COMPLETED" and position and not position.volume:
            pnl = position.realized
            economic = "PROFIT" if pnl > 0 else "LOSS" if pnl < 0 else "FLAT"
        elif state in {"REJECTED", "CANCELLED"} and not position:
            economic = "NOT_APPLICABLE"
        operational = (
            "UNKNOWN"
            if state == "OUTCOME_UNKNOWN"
            else "REJECTED"
            if state in {"REJECTED", "CANCELLED"}
            else "SUCCESS"
        )
        if entry.state == "OUTCOME_UNKNOWN" and state != entry.state:
            operational = "RECOVERED"
        fees = sum(
            (
                d.commission
                for d in self.broker.book.deals
                if position and d.position_id == position.position_id
            ),
            ZERO,
        )
        case = self._record(
            ExperienceCase(
                operational_result=operational,
                policy_compliance="COMPLIANT",
                economic_outcome=economic,
                net_pnl=pnl,
                outcome_known_at=self.clock.now() if state in TERMINAL else None,
                summary=reason,
            ),
            (EvidenceLink(record_id=event.record_id, relation="EXECUTION"),),
            supersedes=entry.case_id,
            costs=Cost(commission=fees),
        )
        updated = updated.model_copy(update={"case_id": case.record_id})
        self._replace(updated)
        self._save(state, (event, case))
        return updated

    def _validate_decision(self, intent: EntryIntent):
        record = self.store.repo.get(intent.decision_id)
        decision = record.body
        if (
            record.account != self.account
            or decision.kind != "decision"
            or decision.result != "VALID"
            or decision.action != "ENTER"
            or decision.decision is None
            or decision.decision.symbol != intent.symbol
            or decision.decision.side != intent.side
            or record.versions.strategy != intent.strategy
            or intent.expires_at > decision.decision.expires_at
            or record.recorded_at > self.clock.now()
            or intent.expires_at > decision.cutoff + timedelta(seconds=60)
        ):
            raise ValueError("intent must reference its exact validated entry decision")

    def submit(self, intent: EntryIntent, market: Market, *, crash_at: str | None = None) -> Entry:
        with self.lock:
            intent = EntryIntent.model_validate(intent.model_dump(mode="json"))
            market = Market.model_validate(market.model_dump(mode="json"))
            self.store.assert_owner()
            if intent.account != self.account:
                raise AccountMismatch("intent cannot redirect the account")
            existing = next(
                (e for e in self.book.entries if e.intent.intent_id == intent.intent_id), None
            )
            if existing:
                if existing.intent != intent:
                    raise RecordConflict("intent identity already has different content")
                return existing
            self._validate_decision(intent)
            self.reconcile(market)
            entry = Entry(intent=intent, state="CREATED")
            self.book = self.book.model_copy(update={"entries": self.book.entries + (entry,)})
            entry = self._transition(entry, "CREATED", "entry intention recorded")
            entry = self._transition(entry, "VALIDATED", "decision reference and account validated")
            reservation, reason = (None, f"account state {self.book.state} blocks entry")
            if self.book.state == "RUNNING" and not self.book.administrative_pause:
                reservation, reason = size(
                    intent,
                    self.broker.snapshot(),
                    self.book.entries,
                    market,
                    self.book.policy,
                    self.book.losses,
                    self.clock.now(),
                )
            audit = self._record(
                RiskEvaluation(
                    approved=reservation is not None,
                    reasons=(reason,),
                    evaluation_mode="DETERMINISTIC",
                    checked_limits=(
                        "trade",
                        "aggregate",
                        "daily",
                        "currency",
                        "gross",
                        "margin",
                        "slots",
                    ),
                    proposed_volume=reservation.volume if reservation else ZERO,
                    planned_loss=reservation.volume * reservation.risk_per_lot
                    if reservation
                    else ZERO,
                    reservation_id=intent.intent_id if reservation else None,
                ),
                (EvidenceLink(record_id=intent.decision_id, relation="DECISION"),),
            )
            self._save("RISK_EVALUATED", (audit,))
            if reservation is None:
                return self._transition(entry, "REJECTED", reason)
            request = BrokerRequest(
                request_id=intent.intent_id,
                entry_id=intent.intent_id,
                account=self.account,
                action="ENTER",
                symbol=intent.symbol,
                side=intent.side,
                volume=reservation.volume,
                stop=intent.stop,
                target=intent.target,
                initial_stop=self.book.policy.protection_mode == "INITIAL_STOP",
            )
            entry = self._transition(
                entry, "RESERVED", reason, reservation=reservation, request=request
            )
            if crash_at == "after_reserve":
                raise SimulatedCrash(crash_at)
            # Last clock/health/account checks occur inside the one writer boundary.
            now = self.clock.now()
            if intent.expires_at <= now or health_reason(market, now, self.book.policy):
                return self._transition(
                    entry,
                    "REJECTED",
                    "expired or stale before send",
                    reservation=reservation.model_copy(update={"volume": ZERO}),
                )
            entry = self._transition(
                entry, "SUBMITTING", "exact request durable before send", submitted_at=now
            )
            if crash_at == "before_send":
                raise SimulatedCrash(crash_at)
            try:
                self.broker.mutate(request, market)
            except UncertainOutcome as error:
                entry = self._transition(entry, "OUTCOME_UNKNOWN", str(error))
                self.book = self.book.model_copy(update={"state": "OUTCOME_UNKNOWN"})
                self._save("OUTCOME_UNKNOWN")
                return entry
            if crash_at in {"after_send", "after_fill", "after_partial"}:
                raise SimulatedCrash(crash_at)
            self.reconcile(market)
            return self.entry(intent.intent_id)

    def _sync_operations(self):
        for operation in self.book.operations:
            if operation.state not in {"SUBMITTING", "OUTCOME_UNKNOWN"}:
                continue
            try:
                observed = self.broker.lookup(operation.request.request_id)
            except UncertainOutcome:
                observed = None
            state = (
                "REJECTED"
                if observed and observed.state == "REJECTED"
                else "COMPLETED"
                if observed and observed.state == "FILLED"
                else "OUTCOME_UNKNOWN"
            )
            if state != operation.state:
                self._operation_result(operation, state, "reconciled management result")

    def _operation_result(self, operation: Operation, state: str, reason: str):
        updated = operation.model_copy(update={"state": state, "reason": reason})
        self.book = self.book.model_copy(
            update={
                "operations": tuple(
                    updated if o.request.request_id == operation.request.request_id else o
                    for o in self.book.operations
                )
            }
        )
        event = self._record(
            ExecutionEvent(
                request_id=operation.request.request_id,
                state=state,
                evidence=reason,
                position_id=str(operation.request.position_id)
                if operation.request.position_id
                else None,
            )
        )
        self._save("MANAGEMENT_" + state, (event,))
        return updated

    def manage(self, request: BrokerRequest, market: Market) -> Operation:
        with self.lock:
            request = BrokerRequest.model_validate(request.model_dump(mode="json"))
            market = Market.model_validate(market.model_dump(mode="json"))
            self.store.assert_owner()
            if request.account != self.account or request.action == "ENTER":
                raise AccountMismatch("management requires bound, non-entry request")
            existing = next(
                (o for o in self.book.operations if o.request.request_id == request.request_id),
                None,
            )
            if existing:
                if existing.request != request:
                    raise RecordConflict("management request identity changed")
                return existing
            if self._pending(request.entry_id):
                raise ValueError("unresolved management request; reconcile before another mutation")
            if not 0 <= (
                self.clock.now() - market.at
            ).total_seconds() <= self.book.policy.quote_age_seconds or any(
                not 0
                <= (self.clock.now() - q.at).total_seconds()
                <= self.book.policy.quote_age_seconds
                for q in market.quotes
            ):
                raise ValueError("fresh prices required for protective mutation")
            operation = Operation(request=request, state="SUBMITTING")
            self.book = self.book.model_copy(
                update={"operations": self.book.operations + (operation,)}
            )
            self._save("MANAGEMENT_SUBMITTING")  # Commit before the only mutation path.
            try:
                result = self.broker.mutate(request, market)
                state = "REJECTED" if result.state == "REJECTED" else "COMPLETED"
                return self._operation_result(operation, state, result.reason or "broker confirmed")
            except UncertainOutcome as error:
                return self._operation_result(operation, "OUTCOME_UNKNOWN", str(error))

    def _pending(self, entry_id):
        return any(
            o.request.entry_id == entry_id and o.state in {"SUBMITTING", "OUTCOME_UNKNOWN"}
            for o in self.book.operations
        )

    def _sync_entries(self):
        for entry in tuple(self.book.entries):
            if entry.state in TERMINAL:
                continue
            if entry.state in {"CREATED", "VALIDATED", "RESERVED"}:
                state = "CANCELLED" if entry.state == "RESERVED" else "REJECTED"
                self._transition(
                    entry,
                    state,
                    "restart before submission; no broker request sent",
                    reservation=None,
                )
                continue
            try:
                observed = self.broker.lookup(entry.intent.intent_id)
            except UncertainOutcome:
                self._history_unavailable = True
                observed = None
            if observed is None:
                if entry.state in {"SUBMITTING", "ACKNOWLEDGED", "OUTCOME_UNKNOWN"}:
                    if entry.state != "OUTCOME_UNKNOWN":
                        self._transition(
                            entry, "OUTCOME_UNKNOWN", "absence is not proof of non-execution"
                        )
                continue
            remaining = entry.reservation.model_copy(update={"volume": observed.remaining})
            p = next(
                (p for p in self.broker.book.positions if p.entry_id == entry.intent.intent_id),
                None,
            )
            if observed.state in {"REJECTED", "CANCELLED"} and not p:
                self._transition(
                    entry,
                    observed.state,
                    observed.reason or "broker confirmed no fill",
                    reservation=remaining,
                )
                continue
            if not p and observed.state == "ACKNOWLEDGED":
                if entry.state != "ACKNOWLEDGED":
                    self._transition(
                        entry, "ACKNOWLEDGED", "acceptance is not a fill", reservation=remaining
                    )
                continue
            if not p:
                self.book = self.book.model_copy(update={"integrity_halt": True})
                continue
            if entry.state in {"SUBMITTING", "OUTCOME_UNKNOWN", "ACKNOWLEDGED"}:
                state = "PARTIALLY_FILLED" if observed.remaining else "FILLED"
                entry = self._transition(
                    entry, state, "broker fill reconciled", reservation=remaining
                )
            elif entry.reservation != remaining:
                entry = self._transition(
                    entry, entry.state, "remaining exposure reconciled", reservation=remaining
                )
            target = (
                "COMPLETED"
                if not p.volume and not observed.remaining
                else ("PROTECTED" if p.stop else "PROTECTION_PENDING")
            )
            if entry.state != target:
                self._transition(entry, target, "position volume and protective stop verified")

    def _cancel(self, entry: Entry, market: Market):
        if (
            entry.reservation
            and entry.reservation.volume
            and not self._pending(entry.intent.intent_id)
        ):
            failures = sum(
                o.request.entry_id == entry.intent.intent_id
                and o.request.action == "CANCEL"
                and o.state == "REJECTED"
                for o in self.book.operations
            )
            if failures >= 3:
                self.book = self.book.model_copy(update={"integrity_halt": True})
                return
            request = BrokerRequest(
                request_id=uuid5(entry.intent.intent_id, f"cancel/{failures}"),
                account=self.account,
                action="CANCEL",
                entry_id=entry.intent.intent_id,
                symbol=entry.intent.symbol,
            )
            self.manage(request, market)

    def _exit_request_id(self, entry_id, version):
        failures = sum(
            o.request.entry_id == entry_id
            and o.request.action == "CLOSE"
            and o.request.expected_version == version
            and o.state == "REJECTED"
            for o in self.book.operations
        )
        if failures >= 3:
            self.book = self.book.model_copy(update={"integrity_halt": True})
            return None
        return uuid5(entry_id, f"exit/{version}/{failures}")

    def _protect_and_exit(self, market: Market):
        now = self.clock.now()
        fresh = 0 <= (
            now - market.at
        ).total_seconds() <= self.book.policy.quote_age_seconds and all(
            0 <= (now - q.at).total_seconds() <= self.book.policy.quote_age_seconds
            for q in market.quotes
        )
        if not fresh:
            return
        for entry in tuple(self.book.entries):
            if entry.state in TERMINAL:
                continue
            if self._pending(entry.intent.intent_id):
                continue
            if entry.reservation and entry.reservation.volume and now >= entry.intent.expires_at:
                # A known partial fill may retain a live remainder after the entry
                # window. Cancel only that remainder; do not replay the entry.
                self._cancel(entry, market)
                if self._pending(entry.intent.intent_id):
                    continue
            p = next(
                (p for p in self.broker.book.positions if p.entry_id == entry.intent.intent_id),
                None,
            )
            must_exit = (
                self.book.losses.hard_halt
                or self.book.losses.loss_pause_day == now.date()
                or self.book.integrity_halt
                or now >= entry.intent.exit_at
                or not market.session_open
            )
            if p and p.volume:
                q, spec = market.quote_for(p.symbol), market.spec_for(p.symbol)
                price = q.bid if p.side == "BUY" else q.ask
                triggered = (
                    p.stop is not None and (price <= p.stop if p.side == "BUY" else price >= p.stop)
                ) or (
                    p.target is not None
                    and (price >= p.target if p.side == "BUY" else price <= p.target)
                )
                actual_loss = (
                    (
                        abs(p.price - entry.intent.stop)
                        * spec.contract_size
                        * market.conversion[spec.quote]
                    )
                    + 2 * spec.commission_per_lot
                    + spec.slippage_per_lot
                    + spec.financing_per_lot
                ) * p.volume
                if (
                    actual_loss
                    > min(equity(self.broker.book, market), self.book.policy.capital)
                    * self.book.policy.trade_fraction
                ):
                    self.book = self.book.model_copy(update={"integrity_halt": True})
                    must_exit = True
                must_exit = must_exit or triggered
                if p.stop is None:
                    self._cancel(entry, market)
                    if self._pending(entry.intent.intent_id):
                        continue
                    overdue = now >= entry.submitted_at + timedelta(
                        seconds=self.book.policy.protection_seconds
                    )
                    if not must_exit and not overdue:
                        request = BrokerRequest(
                            request_id=uuid5(entry.intent.intent_id, f"protect/{p.version}"),
                            account=self.account,
                            action="TIGHTEN_STOP",
                            entry_id=entry.intent.intent_id,
                            symbol=p.symbol,
                            position_id=p.position_id,
                            expected_version=p.version,
                            stop=entry.intent.stop,
                        )
                        result = self.manage(request, market)
                        if result.state == "OUTCOME_UNKNOWN":
                            continue
                        must_exit = result.state == "REJECTED"
                    else:
                        must_exit = True
                if must_exit:
                    self._cancel(entry, market)
                    if self._pending(entry.intent.intent_id):
                        continue
                    current = next(
                        x for x in self.broker.book.positions if x.position_id == p.position_id
                    )
                    request_id = self._exit_request_id(entry.intent.intent_id, current.version)
                    if request_id is None:
                        continue
                    request = BrokerRequest(
                        request_id=request_id,
                        account=self.account,
                        action="CLOSE",
                        entry_id=entry.intent.intent_id,
                        symbol=p.symbol,
                        position_id=p.position_id,
                        expected_version=current.version,
                        volume=current.volume,
                    )
                    self.manage(request, market)
            elif must_exit or (entry.state == "ACKNOWLEDGED" and now >= entry.intent.expires_at):
                self._cancel(entry, market)

    def reconcile(self, market: Market) -> GatewayBook:
        with self.lock:
            market = Market.model_validate(market.model_dump(mode="json"))
            self.store.assert_owner()
            self._history_unavailable = False
            try:
                book = self.broker.snapshot()
            except UncertainOutcome:
                self.book = self.book.model_copy(
                    update={"state": "DEGRADED_PROTECT", "healthy_count": 0}
                )
                self._save("BROKER_UNAVAILABLE")
                return self.book
            now = self.clock.now()
            if not 0 <= (
                now - market.at
            ).total_seconds() <= self.book.policy.quote_age_seconds or any(
                not 0 <= (now - q.at).total_seconds() <= self.book.policy.quote_age_seconds
                for q in market.quotes
            ):
                # Do not reset a UTC-day baseline or value exposure from stale prices.
                self._sync_operations()
                self._sync_entries()
                self.book = self.book.model_copy(
                    update={"state": "DEGRADED_PROTECT", "healthy_count": 0}
                )
                self._save("PRICES_UNAVAILABLE")
                return self.book
            known = {e.intent.intent_id for e in self.book.entries}
            external = any(
                p.volume and (not p.owned or p.entry_id not in known) for p in book.positions
            )
            external = external or any(
                o.request.action == "ENTER" and o.request.entry_id not in known for o in book.orders
            )
            self.book = self.book.model_copy(
                update={
                    "integrity_halt": self.book.integrity_halt or external,
                    "losses": losses(
                        self.book.losses, book, market, self.book.policy, self.clock.now()
                    ),
                }
            )
            self._sync_operations()
            self._sync_entries()
            used = exposure(self.broker.book, self.book.entries, market)
            uncertain = any(e.state == "OUTCOME_UNKNOWN" for e in self.book.entries)
            if used is not None and not uncertain:
                risk, gross, margin, currencies, _ = used
                eligible = min(equity(self.broker.book, market), self.book.policy.capital)
                policy = self.book.policy
                if (
                    risk > eligible * policy.aggregate_fraction
                    or gross > eligible * policy.gross_multiple
                    or margin > eligible * policy.margin_fraction
                    or any(
                        abs(v) > eligible * policy.currency_multiple for v in currencies.values()
                    )
                ):
                    self.book = self.book.model_copy(update={"integrity_halt": True})
            self._protect_and_exit(market)
            self._sync_operations()
            self._sync_entries()
            ledger = losses(
                self.book.losses, self.broker.book, market, self.book.policy, self.clock.now()
            )
            reason = health_reason(market, self.clock.now(), self.book.policy)
            if self._history_unavailable:
                reason = "broker history unavailable"
            if any(not f.classified for f in self.broker.book.cash_flows):
                reason = "unclassified cash movement"
            count = self.book.healthy_count
            if reason:
                count = 0
            elif self.book.health_at is None or market.at > self.book.health_at:
                count = min(count + 1, self.book.policy.healthy_samples)
            unknown = any(e.state == "OUTCOME_UNKNOWN" for e in self.book.entries) or any(
                o.state in {"SUBMITTING", "OUTCOME_UNKNOWN"} for o in self.book.operations
            )
            unprotected = any(
                p.owned and p.volume and p.stop is None for p in self.broker.book.positions
            )
            state = (
                "HARD_HALT"
                if ledger.hard_halt or self.book.integrity_halt
                else "LOSS_PAUSE"
                if ledger.loss_pause_day == self.clock.now().date()
                else "OUTCOME_UNKNOWN"
                if unknown
                else "PROTECTION_PENDING"
                if unprotected
                else "DEGRADED_PROTECT"
                if reason or count < self.book.policy.healthy_samples
                else "RUNNING"
            )
            self.book = self.book.model_copy(
                update={
                    "state": state,
                    "losses": ledger,
                    "healthy_count": count,
                    "health_at": market.at,
                }
            )
            self._save("RECONCILED_" + state)
            return self.book
