"""Authenticated full requests and separately labelled no-order execution receipts."""

import re
from dataclasses import replace
from decimal import Decimal

from fx_talanta.demo.projection import project
from fx_talanta.demo.wire import encode_request
from fx_talanta.domain.ea_protocol import Envelope
from fx_talanta.integration.coordinator import Coordinator
from fx_talanta.shadow.backend import Backend
from fx_talanta.shadow.wire import Frame, digest
from fx_talanta.shadow.work import parse_receipt


class DemoBackend(Backend):
    project_work = staticmethod(project)
    binding_extension = {"transport": "demo-execution/1"}

    def __init__(self, store, account, *args, **kwargs):
        if account.venue != "BROKER_DEMO":
            raise ValueError("DEMO_ACCOUNT_REQUIRED")
        super().__init__(store, account, *args, **kwargs)


class DemoCoordinator(Coordinator):
    backend_type = DemoBackend
    project_work = staticmethod(project)

    def exchange(self, raw, now):
        frame = Frame.decode(
            raw, self.backend.key, direction="C2S", scope=self.scope, client=self.client, now=now
        )
        if frame.operation == "REPORT" and frame.payload.startswith("demo-state/1\t"):
            return self._broker_state(frame, raw, now)
        with self.lock:
            with self.store.transaction() as events:
                self._check(events)
                if any(
                    e.get("nonce") == frame.nonce
                    and e["kind"] in {"demo_broker_state", "demo_broker_state_ack"}
                    for e in events.records
                ):
                    raise ValueError("NONCE_CONFLICT")
                prior = next(
                    (
                        e
                        for e in events.records
                        if e["kind"] == "demo_report" and e["nonce"] == frame.nonce
                    ),
                    None,
                )
                intent = next(
                    (
                        e
                        for e in events.records
                        if e["kind"] == "demo_report_intent" and e["nonce"] == frame.nonce
                    ),
                    None,
                )
                if intent and intent["request_hash"] != digest(raw.decode()):
                    raise ValueError("NONCE_CONFLICT")
                if prior and prior["request_hash"] != digest(raw.decode()):
                    raise ValueError("NONCE_CONFLICT")
            if prior:
                return prior["response"].encode()
            original = raw
            if frame.operation == "REPORT":
                parts = frame.payload.split("\t")
                no_order = (
                    len(parts) == 5
                    and parts[0] == "demo-receipt/1"
                    and parts[4] == "0"
                    and parts[3] in {"NOT_ADMITTED", "REJECTED", "READY", "INTERRUPTED"}
                )
                attempted = (
                    len(parts) == 5
                    and parts[0] == "demo-receipt/2"
                    and (
                        (parts[3] == "ACKNOWLEDGED" and parts[4] == "ATTEMPTED")
                        or (parts[3] in {"SUBMITTING", "OUTCOME_UNKNOWN"} and parts[4] == "UNKNOWN")
                    )
                )
                if not (no_order or attempted) or not re.fullmatch(r"[A-Z0-9_]{1,80}", parts[2]):
                    raise ValueError("DISABLED_EXECUTION_RECEIPT_REQUIRED")
                reference = bytes.fromhex(parts[1]).decode("ascii")
                if len(reference.split("\t")) != 10:
                    raise ValueError("INVALID_REFERENCE_RECEIPT")
                request_id = reference.split("\t")[1]
                with self._guard(receipt=True), self.store.transaction() as events:
                    for e in events.records:
                        if (
                            e["kind"] in {"demo_report", "demo_report_intent"}
                            and e["request_id"] == request_id
                            and e["receipt"] != frame.payload
                        ):
                            raise ValueError("EXECUTION_RECEIPT_CONFLICT")
                    work = next(
                        (
                            e["work"]
                            for e in events.records
                            if e["kind"] == "work" and e["work"].split("\t")[1] == request_id
                        ),
                        None,
                    )
                    if work is None:
                        raise ValueError("UNKNOWN_WORK")
                    parse_receipt(reference, work)
                    if not intent:
                        events.append(
                            dict(
                                kind="demo_report_intent",
                                nonce=frame.nonce,
                                request_id=request_id,
                                request_hash=digest(original.decode()),
                                receipt=frame.payload,
                                execution_enabled=False,
                            )
                        )
                self._advance()
                raw = replace(frame, payload=reference).encode(self.backend.key)
            result = super().exchange(raw, now)
            response = Frame.decode(
                result,
                self.backend.key,
                direction="S2C",
                scope=self.scope,
                client=self.client,
                now=now,
                nonce=frame.nonce,
            )
            if frame.operation == "REPORT":
                result = replace(response, payload=digest(frame.payload)).encode(self.backend.key)
                with self._guard(receipt=True), self.store.transaction() as events:
                    self._check(events)
                    ledger = self._ledger(events)
                    if attempted:
                        ledger = ledger.model_copy(update={"hard_halt": True})
                    events.append(
                        dict(
                            kind="demo_report",
                            ledger=ledger.model_dump(mode="json"),
                            nonce=frame.nonce,
                            request_hash=digest(original.decode()),
                            request_id=request_id,
                            receipt=frame.payload,
                            response=result.decode(),
                            execution_enabled=False,
                        )
                    )
                self._advance()
            elif response.operation == "WORK" and response.payload.startswith("disabled-work/1\t"):
                risk = bytes.fromhex(response.payload.split("\t")[1]).decode()
                request_id = risk.split("\t")[1]
                with self.store.transaction() as events:
                    envelope = next(
                        e["envelope"]
                        for e in events.records
                        if e["kind"] == "work" and e["work"].split("\t")[1] == request_id
                    )
                complete = encode_request(Envelope.model_validate(envelope))
                payload = (
                    "demo-execution/1\t"
                    + complete.encode().hex()
                    + "\t"
                    + response.payload.encode().hex()
                )
                result = replace(response, payload=payload).encode(self.backend.key)
            return result

    def _broker_state(self, frame, raw, now):
        from fx_talanta.demo.state import decode_state, reconcile_claim

        with self.lock, self._guard(receipt=True):
            with self.store.transaction() as events:
                self._check(events)
                for event in events.records:
                    if event.get("nonce") == frame.nonce and "request_hash" in event:
                        if event["kind"] not in {
                            "demo_broker_state",
                            "demo_broker_state_ack",
                        } or event["request_hash"] != digest(raw.decode()):
                            raise ValueError("NONCE_CONFLICT")
                        return event["response"].encode()
                fields = frame.payload.split("\t")
                if len(fields) != 14:
                    raise ValueError("INVALID_BROKER_STATE")
                request_id = fields[1]
                work = next(
                    (
                        e
                        for e in events.records
                        if e["kind"] == "work" and e["work"].split("\t")[1] == request_id
                    ),
                    None,
                )
                if work is None:
                    raise ValueError("UNKNOWN_WORK")
                prior = [
                    e
                    for e in events.records
                    if e["kind"] == "demo_broker_state" and e["request_id"] == request_id
                ]
                same = next(
                    (e for e in prior if str(e["state"]["payload"]["sequence"]) == fields[3]), None
                )
                if same and same["report"] != frame.payload:
                    raise ValueError("BROKER_STATE_REVISION_CONFLICT")
                previous = prior[-1] if prior else None
                if same:
                    state = Envelope.model_validate(same["state"])
                    remaining, error = same["remaining_volume"], same["clock_error_ms"]
                else:
                    state, remaining, error = decode_state(
                        frame.payload, Envelope.model_validate(work["envelope"]), now, previous
                    )
                response = Frame(
                    "S2C",
                    self.scope,
                    self.client,
                    frame.nonce,
                    now,
                    now + 5000,
                    "ACK",
                    digest(frame.payload),
                ).encode(self.backend.key)
                # A report is evidence, never permission. In this disabled release,
                # any claimed fill is an anomaly that adds a sticky entry veto.
                ledger = self._ledger(events)
                if (
                    state.payload.filled_volume > 0
                    or work["envelope"]["payload"]["action"] != "ENTER"
                ):
                    ledger = ledger.model_copy(update={"hard_halt": True})
                if same:
                    events.append(
                        dict(
                            kind="demo_broker_state_ack",
                            nonce=frame.nonce,
                            request_hash=digest(raw.decode()),
                            request_id=request_id,
                            response=response.decode(),
                        )
                    )
                else:
                    events.append(
                        dict(
                            kind="demo_broker_state",
                            nonce=frame.nonce,
                            request_hash=digest(raw.decode()),
                            request_id=request_id,
                            report=frame.payload,
                            state=state.model_dump(mode="json"),
                            reconciliation=reconcile_claim(state).model_dump(mode="json"),
                            remaining_volume=str(remaining),
                            observed_position_volume=str(Decimal(fields[6]) / Decimal(100000000)),
                            action=work["envelope"]["payload"]["action"],
                            clock_error_ms=error,
                            received_at_ms=now,
                            response=response.decode(),
                            ledger=ledger.model_dump(mode="json"),
                            source="EA_BROKER_RECONCILIATION",
                            independently_verified=False,
                            execution_enabled=False,
                        )
                    )
                next_tip = events.tip
            self.tip = next_tip
            return response

    def status(self, now):
        result = super().status(now)
        with self.lock, self.store.transaction() as events:
            self._check(events)
            states = {
                e["request_id"]: e for e in events.records if e["kind"] == "demo_broker_state"
            }
            result["broker_states"] = [
                dict(
                    state=e["state"],
                    remaining_volume=e["remaining_volume"],
                    action=e["action"],
                    observed_position_volume=e["observed_position_volume"],
                    observation_age_ms=now
                    - int(
                        Envelope.model_validate(e["state"]).payload.created_at.timestamp() * 1000
                    ),
                    clock_error_ms=e["clock_error_ms"],
                    source=e["source"],
                    independently_verified=False,
                )
                for e in states.values()
            ]
            unique = {e["request_id"]: e for e in events.records if e["kind"] == "demo_report"}
            result["native_execution_results"] = [
                dict(
                    request_id=e["request_id"],
                    reason=e["receipt"].split("\t")[2],
                    state=e["receipt"].split("\t")[3],
                    orders_sent=0 if e["receipt"].split("\t")[0] == "demo-receipt/1" else None,
                    mutation_attempt=e["receipt"].split("\t")[4],
                )
                for e in unique.values()
            ]
        if any(e["orders_sent"] is None for e in result["native_execution_results"]):
            result["orders_sent"] = None
        result["integration"] = "DEMO_EXECUTION_DISABLED"
        result["channels"]["EA"]["capability"] = "DEMO_EXECUTION_DISABLED"
        return result
