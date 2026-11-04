"""Authenticated real-observation delivery. Every result remains a HOLD.

The trusted local publisher supplies captured facts; the wire cannot submit work,
override missing evidence, claim a lease, retire an owner or enable execution.
"""

from threading import Lock
from uuid import UUID, uuid4

from fx_talanta.connected_shadow.inputs import normalize
from fx_talanta.shadow.backend import Application
from fx_talanta.shadow.wire import Frame, digest, hex64, integer
from fx_talanta.shadow.work import scope_for

PATH = "/v1/connected-shadow"
DOMAIN = "connected/1"


def observation_fields(work):
    f = work.split("\t")
    if len(f) != 14 or f[0] != "connected-observation/1" or str(UUID(f[1])) != f[1]:
        raise ValueError("INVALID_OBSERVATION")
    if not all(hex64(f[i]) for i in (3, 4, 12)) or f[8] not in {"EURUSD", "USDJPY"}:
        raise ValueError("INVALID_OBSERVATION")
    if not f[9].startswith(f[8]) or not 6 <= len(f[9]) <= 32:
        raise ValueError("INVALID_SYMBOL")
    if any(
        c not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._-" for c in f[9]
    ):
        raise ValueError("INVALID_SYMBOL")
    for i in (2, 5, 6, 7, 10):
        integer(f[i])
    if not 0 < int(f[6]) - int(f[5]) <= 60000 or int(f[2]) < 1 or int(f[7]) > 100:
        raise ValueError("INVALID_OBSERVATION")
    if not f[11] or any(c not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ_," for c in f[11]):
        raise ValueError("MISSING_EVIDENCE_CODES_REQUIRED")
    if str(int(f[13])) != f[13] or abs(int(f[13])) > 50400000:
        raise ValueError("INVALID_CLOCK_MAPPING")
    return f


def hold_receipt(work, now, local_error, native_tick_ms):
    f = observation_fields(work)
    if type(local_error) is not int or not 0 <= local_error <= 100 or now < int(f[5]):
        raise ValueError("NATIVE_CLOCK_UNVERIFIED")
    error = max(local_error, int(f[7]))
    source_age = now - int(f[10])
    native_age = now - native_tick_ms if native_tick_ms else None
    if now + error >= int(f[6]):
        reason = "EXPIRED"
    elif native_age is None:
        reason = "NATIVE_DATA_UNAVAILABLE"
    elif (
        source_age - error < 0
        or source_age + error > 2000
        or native_age - local_error < 0
        or native_age + local_error > 2000
    ):
        reason = "QUOTE_STALE"
    else:
        reason = "REQUIRED_INPUTS"
    return "\t".join(
        map(
            str,
            (
                "connected-hold/1",
                f[1],
                f[2],
                f[4],
                now,
                local_error,
                source_age + error,
                native_tick_ms,
                native_age + local_error if native_age is not None else -1,
                reason,
                f[11],
                0,
            ),
        )
    )


def validate_receipt(receipt, work, now, server_error=0):
    r = receipt.split("\t")
    if len(r) != 12 or r[0] != "connected-hold/1":
        raise ValueError("INVALID_RECEIPT")
    at, error, native_tick = (integer(r[i]) for i in (4, 5, 7))
    if type(server_error) is not int or not 0 <= server_error <= 100:
        raise ValueError("SERVER_CLOCK_UNVERIFIED")
    if at - error > now + server_error or receipt != hold_receipt(work, at, error, native_tick):
        raise ValueError("NATIVE_RECEIPT_MISMATCH")
    return r


class Service:
    def __init__(
        self, store, authority, account, client, incarnation, epoch, key, clock, *, bootstrap=False
    ):
        if not all(hex64(v) for v in (client, incarnation)) or not 32 <= len(key) <= 64:
            raise ValueError("INVALID_CONNECTED_BINDING")
        if account.environment.value != "PAPER" or account.venue != "BROKER_DEMO":
            raise ValueError("DEMO_ONLY")
        self.store, self.authority, self.account, self.clock = store, authority, account, clock
        self.client, self.incarnation, self.epoch, self.key = client, incarnation, epoch, key
        self.scope = scope_for(account)
        self._upper_lock, self._last_upper = Lock(), 0
        if authority.scope != self.scope or getattr(store, "account", account) != account:
            raise ValueError("AUTHORITY_OR_STORE_ACCOUNT_MISMATCH")
        self.binding = dict(
            kind="binding",
            scope=self.scope,
            client=client,
            incarnation=incarnation,
            epoch=epoch,
            key_hash=digest(key.hex()),
            protocol=DOMAIN,
            execution_enabled=False,
        )
        with store.transaction() as events:
            if not events.records and bootstrap:
                events.append(self.binding)
            elif not events.records or events.records[0] != self.binding or bootstrap:
                raise ValueError("CONNECTED_BINDING_CONFLICT")

    def _check(self, events):
        if not events.records or events.records[0] != self.binding:
            raise ValueError("CONNECTED_BINDING_CONFLICT")

    def clock_upper(self):
        with self._upper_lock:
            now, error = self.clock()
            # A newly corroborated, narrower UTC interval may have a smaller
            # upper endpoint. Retaining the former endpoint is conservative
            # and avoids interpreting reduced uncertainty as a clock reversal.
            self._last_upper = max(self._last_upper, now + error)
            return self._last_upper

    def publish(self, capture, symbol, side="BUY"):
        normalized = normalize(capture, symbol=symbol, side=side)
        if capture["account_scope"] != self.scope:
            raise ValueError("CAPTURE_ACCOUNT_MISMATCH")
        now, _ = self.clock()
        if not 0 <= now - capture["measured_at_ms"] < 60000:
            raise ValueError("CAPTURE_EXPIRED")
        with self.authority.guard(self.client, self.incarnation, self.epoch, self.clock_upper):
            with self.store.transaction() as events:
                self._check(events)
                previous = [e for e in events.records if e["kind"] == "work"]
                if any(
                    e["capture_sha256"] == capture["capture_sha256"] and e["symbol"] == symbol
                    for e in previous
                ):
                    return False
                quote = capture["quotes"][symbol]
                fields = (
                    "connected-observation/1",
                    uuid4(),
                    len(previous) + 1,
                    self.scope,
                    capture["capture_sha256"],
                    capture["measured_at_ms"],
                    capture["measured_at_ms"] + 60000,
                    capture["clock_error_ms"],
                    symbol,
                    quote["broker_symbol"],
                    quote["tick_ms"],
                    ",".join(normalized.missing) or "NO_ORDER_SCOPE",
                    capture["binding_sha256"],
                    capture["sdk_time_offset_seconds"] * 1000,
                )
                work = "\t".join(map(str, fields))
                observation_fields(work)
                events.append(
                    dict(
                        kind="work",
                        work=work,
                        capture=capture,
                        symbol=symbol,
                        capture_sha256=capture["capture_sha256"],
                        observed_fields=normalized.observed_fields,
                        missing=list(normalized.missing),
                        execution_enabled=False,
                    )
                )
        return True

    def exchange(self, raw, ignored_now=None):
        now, error = self.clock()
        frame = Frame.decode(
            raw, self.key, direction="C2S", scope=self.scope, client=self.client, now=now
        )
        p = frame.payload.split("\t")
        if len(p) < 4 or p[0] != DOMAIN or p[2:4] != [self.incarnation, str(self.epoch)]:
            raise ValueError("CONNECTED_ROUTE_MISMATCH")
        if p[1] in {"SYNC", "PULL", "REPORT"}:
            report = p[1] == "REPORT"
            if frame.operation != ("REPORT" if report else "PULL") or len(p) != (
                5 if report else 4
            ):
                raise ValueError("INVALID_CONNECTED_REQUEST")
            guard = self.authority.guard if p[1] == "PULL" else self.authority.guard_receipt
            with guard(self.client, self.incarnation, self.epoch, self.clock_upper):
                with self.store.transaction() as events:
                    self._check(events)
                    old = next(
                        (
                            e
                            for e in events.records
                            if e["kind"] == "exchange" and e["nonce"] == frame.nonce
                        ),
                        None,
                    )
                    if old:
                        if old["request_hash"] != digest(raw.decode("ascii")):
                            raise ValueError("NONCE_CONFLICT")
                        if p[1] == "SYNC":
                            raise ValueError("SYNC_NONCE_REPLAY")
                        return old["response"].encode("ascii")
                    works = [e["work"] for e in events.records if e["kind"] == "work"]
                    receipts = {
                        e["receipt"].split("\t")[1]: e["receipt"]
                        for e in events.records
                        if e["kind"] == "receipt"
                    }
                    pending = [w for w in works if w.split("\t")[1] not in receipts]
                    if p[1] == "SYNC":
                        operation, payload = "WORK", f"{DOMAIN}\tCLOCK\t{now}\t{error}"
                    elif not report:
                        operation, payload = ("WORK", pending[0]) if pending else ("EMPTY", "")
                    else:
                        receipt = bytes.fromhex(p[4]).decode("ascii")
                        receipt_parts = receipt.split("\t")
                        if len(receipt_parts) != 12 or receipt_parts[0] != "connected-hold/1":
                            raise ValueError("INVALID_RECEIPT")
                        rid = receipt_parts[1]
                        work = next((w for w in works if w.split("\t")[1] == rid), None)
                        if work is None:
                            raise ValueError("UNKNOWN_OBSERVATION")
                        validate_receipt(receipt, work, now, error)
                        prior = receipts.get(rid)
                        if prior is not None and prior != receipt:
                            raise ValueError("RECEIPT_CONFLICT")
                        if prior is None:
                            if not pending or pending[0] != work:
                                raise ValueError("RECEIPT_SEQUENCE_GAP")
                            events.append(
                                dict(
                                    kind="receipt",
                                    receipt=receipt,
                                    received_at_ms=now,
                                    execution_enabled=False,
                                )
                            )
                        operation, payload = "ACK", digest(receipt)
                    response = Frame(
                        "S2C",
                        self.scope,
                        self.client,
                        frame.nonce,
                        now,
                        now + 5000,
                        operation,
                        payload,
                    ).encode(self.key)
                    events.append(
                        dict(
                            kind="exchange",
                            nonce=frame.nonce,
                            at_ms=now,
                            request_hash=digest(raw.decode("ascii")),
                            response=response.decode("ascii"),
                            execution_enabled=False,
                        )
                    )
            if p[1] == "PULL":
                self.authority.renew(self.client, self.incarnation, self.epoch, self.clock_upper())
            return response
        else:
            raise ValueError("INVALID_CONNECTED_OPERATION")

    def status(self):
        with self.store.transaction() as events:
            self._check(events)
            receipts = [e["receipt"].split("\t") for e in events.records if e["kind"] == "receipt"]
            exchanges = [e for e in events.records if e["kind"] == "exchange"]
        now, _ = self.clock()
        last = exchanges[-1]["at_ms"] if exchanges else None
        return dict(
            execution_enabled=False,
            connected_execution_accepted=False,
            last_exchange_ms=last,
            receipt_count=len(receipts),
            channel_state="HEALTHY"
            if last is not None and 0 <= now - last <= 15000
            else "DISCONNECTED",
            results=[
                dict(
                    sequence=int(r[2]),
                    at_ms=int(r[4]),
                    clock_error_ms=int(r[5]),
                    source_quote_age_upper_ms=int(r[6]),
                    native_quote_age_upper_ms=int(r[8]) if int(r[7]) else None,
                    reason=r[9],
                    missing=r[10].split(","),
                )
                for r in receipts
            ],
        )


class ConnectedApplication(Application):
    def __call__(self, environ, start_response):
        # Preserve the strict v1 HTTPS boundary, mapping only this exact private route.
        if environ.get("PATH_INFO") != PATH:
            start_response("404 Not Found", [("Content-Length", "0")])
            return [b""]
        return super().__call__({**environ, "PATH_INFO": "/v1/shadow"}, start_response)
