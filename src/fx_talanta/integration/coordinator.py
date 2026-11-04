"""One fenced, durable no-order route through operating inputs and EA receipts.

No sender, risk reservation or production execution permission exists here.
The transport and reference client keep their original authenticated protocol.
"""

from datetime import UTC, datetime
from decimal import Decimal
from threading import RLock

from fx_talanta.connected_shadow.inputs import canonical_hash
from fx_talanta.domain.ea_protocol import Envelope
from fx_talanta.safety.control import LossState, Protection, losses, protection_step
from fx_talanta.shadow.backend import Backend
from fx_talanta.shadow.wire import Frame, digest
from fx_talanta.shadow.work import parse_work, project, scope_for


class Coordinator:
    backend_type = Backend
    project_work = staticmethod(project)

    def __init__(
        self,
        store,
        authority,
        account,
        client,
        incarnation,
        epoch,
        release,
        policy,
        key,
        clock,
        *,
        initial=None,
        expected_tip=None,
        bootstrap=False,
        clock_error_ms=1000,
        clock_read=None,
        receipt_only=False,
    ):
        self.store, self.authority, self.clock = store, authority, clock
        self.client, self.incarnation, self.epoch = client, incarnation, epoch
        self.scope = scope_for(account)
        self.lock = RLock()
        self.clock_error_ms = clock_error_ms
        self.clock_read = clock_read
        self.failed = False
        self.receipt_only = receipt_only
        if getattr(authority, "scope", None) != self.scope:
            raise ValueError("AUTHORITY_ACCOUNT_MISMATCH")
        if bootstrap and (receipt_only or epoch != 1):
            raise ValueError("NEW_STREAM_CANNOT_RESET_AUTHORITY_HISTORY")
        if bootstrap:
            if not isinstance(initial, LossState) or expected_tip is not None:
                raise ValueError("EXPLICIT_INITIAL_STATE_REQUIRED")
        elif initial is not None or expected_tip is None:
            raise ValueError("RETAINED_CHECKPOINT_REQUIRED")
        with self._guard(receipt=receipt_only):
            with store.transaction() as events:
                if bootstrap and events.records:
                    raise ValueError("JOURNAL_ALREADY_EXISTS")
                if not bootstrap and events.tip != expected_tip:
                    raise ValueError("RETAINED_CHECKPOINT_CONFLICT")
            self.backend = self.backend_type(
                store, account, client, release, policy, key, bootstrap=bootstrap
            )
            with store.transaction() as events:
                if bootstrap:
                    events.append(
                        dict(
                            kind="integration",
                            schema="disabled-integration/1",
                            ledger=initial.model_dump(mode="json"),
                            execution_enabled=False,
                        )
                    )
                if (
                    len(events.records) < 2
                    or events.records[1].get("kind") != "integration"
                    or events.records[1].get("schema") != "disabled-integration/1"
                ):
                    raise ValueError("INTEGRATION_STATE_MISSING")
                self.tip = events.tip
                self._ledger(events)

    def _guard(self, receipt=False):
        method = self.authority.guard_receipt if receipt else self.authority.guard
        return method(self.client, self.incarnation, self.epoch, self.clock)

    def _check(self, events):
        if self.failed or events.tip != self.tip:
            raise ValueError("INTEGRATION_CHECKPOINT_CONFLICT")
        self.backend.check(events)

    @staticmethod
    def _ledger(events):
        return LossState.model_validate(
            next(e["ledger"] for e in reversed(events.records) if "ledger" in e)
        )

    @staticmethod
    def _flags(events, ledger):
        flags = (
            (1 if ledger.hard_halt else 0)
            | (2 if ledger.loss_pause else 0)
            | (64 if ledger.owner_pause else 0)
        )
        latest = {}
        for event in events.records:
            if event["kind"] == "protection":
                latest[event["position"]] = event["state"]
        for state in latest.values():
            if state["phase"] not in {"PROTECTED", "CLOSED"}:
                flags |= 8
            if state["phase"] in {"UNKNOWN", "EXIT_REJECTED"}:
                flags |= 4
        return flags

    def checkpoint(self):
        with self.lock, self.store.transaction() as events:
            self._check(events)
            return events.tip

    def _advance(self):
        with self.store.transaction() as events:
            self.backend.check(events)
            self.tip = events.tip

    def publish(self, envelope, snapshot, now):
        """Trusted publication only; HTTP cannot supply or override operating facts.

        Caller uses inputs.assemble before this typed, hash-bound boundary.
        Loss/owner flags may only add vetoes. Incomplete inputs are not published.
        """
        if self.receipt_only:
            raise ValueError("RECEIPT_ONLY_RECOVERY")
        envelope = Envelope.model_validate(envelope.model_dump())
        work = self.project_work(envelope, snapshot)
        _, value = parse_work(work)
        with self.lock, self._guard():
            with self.store.transaction() as events:
                self._check(events)
                ledger = self._ledger(events)
                day = datetime.fromtimestamp(now / 1000, UTC).date()
                if (
                    ledger.day != day
                    or value.day_start != ledger.start
                    or value.day_loss != ledger.daily_loss
                ):
                    raise ValueError("RECONCILED_LOSS_STATE_REQUIRED")
                flags = self._flags(events, ledger)
                if value.flags & flags != flags:
                    raise ValueError("DURABLE_SAFETY_VETO_MISSING")
            try:
                result = self.backend.publish(envelope, value, now)
                self._advance()
                return result
            except BaseException:
                # A commit/response failure must never become an implicit retry.
                self.failed = True
                raise

    def exchange(self, raw, now):
        frame = Frame.decode(
            raw, self.backend.key, direction="C2S", scope=self.scope, client=self.client, now=now
        )
        if frame.operation == "PULL" and frame.payload == "disabled-sync/1":
            return self._sync(frame, raw, now)
        if self.receipt_only and frame.operation != "REPORT":
            raise ValueError("RECEIPT_ONLY_RECOVERY")
        with self.lock, self._guard(receipt=frame.operation == "REPORT"):
            with self.store.transaction() as events:
                self._check(events)
                ledger = self._ledger(events)
                for prior in events.records:
                    if prior.get("nonce") != frame.nonce:
                        continue
                    if prior["kind"] == "integration_sync":
                        raise ValueError("NONCE_CONFLICT")
                    if prior["kind"] == "integration_delivery":
                        if prior["request_hash"] != digest(raw.decode()):
                            raise ValueError("NONCE_CONFLICT")
                        if prior["ledger"] != ledger.model_dump(mode="json"):
                            raise ValueError("WORK_INVALIDATED_BY_RECONCILIATION")
                        return prior["response"].encode()
                if frame.operation == "PULL":
                    receipts = {
                        e["receipt"].split("\t")[1]
                        for e in events.records
                        if e["kind"] == "receipt"
                    }
                    for event in events.records:
                        if event["kind"] != "work":
                            continue
                        fields, snapshot = parse_work(event["work"])
                        if fields[1] in receipts:
                            continue
                        required = self._flags(events, ledger)
                        if (
                            snapshot.day_start != ledger.start
                            or snapshot.day_loss != ledger.daily_loss
                            or snapshot.flags & required != required
                            or ledger.day != datetime.fromtimestamp(now / 1000, UTC).date()
                        ):
                            raise ValueError("WORK_INVALIDATED_BY_RECONCILIATION")
            try:
                result = self.backend.exchange(raw, now)
                response = Frame.decode(
                    result,
                    self.backend.key,
                    direction="S2C",
                    scope=self.scope,
                    client=self.client,
                    now=now,
                    nonce=frame.nonce,
                )
                if response.operation == "WORK":
                    from dataclasses import replace

                    values = [
                        ledger.day.strftime("%Y%m%d"),
                        format(ledger.start, "f"),
                        format(ledger.day_flows, "f"),
                        format(ledger.units, "f"),
                        format(ledger.high_nav, "f"),
                        format(ledger.daily_loss, "f"),
                        str(int(ledger.loss_pause)),
                        str(int(ledger.hard_halt)),
                        str(int(ledger.owner_pause)),
                    ]
                    payload = "\t".join(
                        ["disabled-work/1", response.payload.encode().hex(), *values]
                    )
                    if len(payload) > 3500:
                        raise ValueError("NATIVE_JOURNAL_RECORD_LIMIT")
                    result = replace(response, payload=payload).encode(self.backend.key)
                    with self.store.transaction() as events:
                        events.append(
                            dict(
                                kind="integration_delivery",
                                nonce=frame.nonce,
                                request_hash=digest(raw.decode()),
                                ledger=ledger.model_dump(mode="json"),
                                response=result.decode("ascii"),
                                execution_enabled=False,
                            )
                        )
                self._advance()
                return result
            except ValueError:
                # Validated input rejection rolls back; independently confirm the tip.
                with self.store.transaction() as events:
                    self._check(events)
                raise
            except BaseException:
                self.failed = True
                raise

    def _sync(self, frame, raw, now):
        from fx_talanta.shadow.wire import digest

        now, uncertainty = self.clock_read() if self.clock_read else (now, self.clock_error_ms)
        if type(uncertainty) is not int or not 0 <= uncertainty <= 100:
            raise ValueError("CLOCK_EVIDENCE_REQUIRED")
        with self.lock, self._guard(receipt=True):
            with self.store.transaction() as events:
                self._check(events)
                for prior in events.records:
                    if prior.get("nonce") == frame.nonce and "request_hash" in prior:
                        if prior["kind"] != "integration_sync" or prior["request_hash"] != digest(
                            raw.decode()
                        ):
                            raise ValueError("NONCE_CONFLICT")
                        return prior["response"].encode()
                payload = f"disabled-clock/1\t{now}\t{uncertainty}"
                response = Frame(
                    "S2C", self.scope, self.client, frame.nonce, now, now + 5000, "WORK", payload
                ).encode(self.backend.key)
                events.append(
                    dict(
                        kind="integration_sync",
                        nonce=frame.nonce,
                        request_hash=digest(raw.decode()),
                        response=response.decode(),
                        at_ms=now,
                        execution_enabled=False,
                    )
                )
            self._advance()
            return response

    def reconcile(self, event_id, *, evidence_hash, now, **observation):
        """Trusted reconciler's classified account observation, never EA/model input.

        Original source is retained by the caller. Same event ID/content is a no-op;
        conflicting duplicate or backwards observation refuses, including cash flows.
        """
        from fx_talanta.shadow.wire import hex64

        if (
            not isinstance(event_id, str)
            or not 1 <= len(event_id) <= 160
            or not hex64(evidence_hash)
        ):
            raise ValueError("RECONCILIATION_IDENTITY_REQUIRED")
        serial = {
            k: (
                str(v)
                if isinstance(v, Decimal)
                else v.isoformat()
                if hasattr(v, "isoformat")
                else v
            )
            for k, v in observation.items()
        }
        fingerprint = canonical_hash(dict(observation=serial, evidence=evidence_hash, at=now))
        with self.lock, self._guard():
            with self.store.transaction() as events:
                self._check(events)
                reconciliations = [e for e in events.records if e["kind"] == "reconciliation"]
                for prior in reconciliations:
                    if prior["id"] == event_id:
                        if prior["fingerprint"] != fingerprint:
                            raise ValueError("RECONCILIATION_CONFLICT")
                        return LossState.model_validate(prior["ledger"])
                if reconciliations and now < reconciliations[-1]["at_ms"]:
                    raise ValueError("RECONCILIATION_TIME_REGRESSION")
                if observation.get("day") != datetime.fromtimestamp(now / 1000, UTC).date():
                    raise ValueError("RECONCILIATION_DAY_CONFLICT")
                result = losses(self._ledger(events), **observation)
                events.append(
                    dict(
                        kind="reconciliation",
                        id=event_id,
                        fingerprint=fingerprint,
                        at_ms=now,
                        evidence_hash=evidence_hash,
                        observation=serial,
                        ledger=result.model_dump(mode="json"),
                        execution_enabled=False,
                    )
                )
                next_tip = events.tip
            self.tip = next_tip
        return result

    def protect(self, position_id, state, *, evidence_hash, **observation):
        """Persist an advisory transition; never pretend a repair/exit was submitted."""
        from fx_talanta.shadow.wire import hex64

        if not hex64(evidence_hash) or not isinstance(state, Protection) or not position_id:
            raise ValueError("PROTECTION_EVIDENCE_REQUIRED")
        proposed, action = protection_step(state, **observation)
        suppressed = action in {"ATTACH_STOP_ONCE", "CONTROLLED_EXIT_ONCE"}
        actual = proposed.model_copy(update={"phase": state.phase}) if suppressed else proposed
        with self.lock, self._guard():
            with self.store.transaction() as events:
                self._check(events)
                prior = next(
                    (
                        e
                        for e in reversed(events.records)
                        if e["kind"] == "protection" and e["position"] == position_id
                    ),
                    None,
                )
                if prior is not None and prior["state"] != state.model_dump(mode="json"):
                    raise ValueError("PROTECTION_STATE_CONFLICT")
                events.append(
                    dict(
                        kind="protection",
                        position=position_id,
                        evidence_hash=evidence_hash,
                        ledger=self._ledger(events)
                        .model_copy(
                            update={"hard_halt": self._ledger(events).hard_halt or actual.hard_halt}
                        )
                        .model_dump(mode="json"),
                        state=actual.model_dump(mode="json"),
                        proposed_state=proposed.model_dump(mode="json"),
                        observation=observation,
                        recommendation=action,
                        suppressed=suppressed,
                        execution_enabled=False,
                    )
                )
                next_tip = events.tip
            self.tip = next_tip
        return actual, action, suppressed

    def status(self, now):
        with self.lock, self.store.transaction() as events:
            self._check(events)
            flags = self._flags(events, self._ledger(events))
        status = self.backend.status(now)
        status.update(
            integration="DISABLED",
            orders_sent=0,
            demo_order_acceptance=False,
            current_veto_flags=flags,
        )
        return status
