"""Authenticated full requests and separately labelled no-order execution receipts."""

import re
from dataclasses import replace

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
        with self.lock:
            with self.store.transaction() as events:
                self._check(events)
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
                if (
                    len(parts) != 5
                    or parts[0] != "demo-receipt/1"
                    or parts[4] != "0"
                    or not re.fullmatch(r"[A-Z0-9_]{1,80}", parts[2])
                    or parts[3] not in {"NOT_ADMITTED", "REJECTED", "READY", "INTERRUPTED"}
                ):
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
                    events.append(
                        dict(
                            kind="demo_report",
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

    def status(self, now):
        result = super().status(now)
        with self.lock, self.store.transaction() as events:
            self._check(events)
            unique = {e["request_id"]: e for e in events.records if e["kind"] == "demo_report"}
            result["native_execution_results"] = [
                dict(
                    request_id=e["request_id"],
                    reason=e["receipt"].split("\t")[2],
                    state=e["receipt"].split("\t")[3],
                    orders_sent=0,
                )
                for e in unique.values()
            ]
        result["integration"] = "DEMO_EXECUTION_DISABLED"
        result["channels"]["EA"]["capability"] = "DEMO_EXECUTION_DISABLED"
        return result
