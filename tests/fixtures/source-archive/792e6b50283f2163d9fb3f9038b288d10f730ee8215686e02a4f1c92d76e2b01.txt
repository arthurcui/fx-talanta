"""Shadow pull/receipt service. No path allocates risk or dispatches broker work."""

import time
from decimal import Decimal

from fx_talanta.shadow.wire import MAX_BODY, PATH, Frame, digest, hex64
from fx_talanta.shadow.work import parse_receipt, parse_work, project, scope_for


class Backend:
    def __init__(self, store, account, client, release, policy, key, *, bootstrap=False):
        if account.environment.value != "PAPER" or not all(
            hex64(v) for v in (client, release, policy)
        ):
            raise ValueError("INVALID_BINDING")
        if not 32 <= len(key) <= 64:
            raise ValueError("INVALID_KEY")
        self.store, self.account, self.key = store, account, key
        self.scope, self.client = scope_for(account), client
        self.binding = dict(
            kind="binding",
            scope=self.scope,
            client=client,
            release=release,
            policy=policy,
            key_hash=digest(key.hex()),
            execution_enabled=False,
        )
        with store.transaction() as events:
            if not events.records:
                if not bootstrap:
                    raise ValueError("MISSING_BINDING")
                events.append(self.binding)
            elif events.records[0] != self.binding or bootstrap:
                raise ValueError("BINDING_CONFLICT")

    def check(self, events):
        if not events.records or events.records[0] != self.binding:
            raise ValueError("BINDING_CONFLICT")

    def publish(self, envelope, snapshot, now):
        """Trusted backend-only API. There is deliberately no HTTP enqueue route."""
        work = project(envelope, snapshot)
        f, _ = parse_work(work)
        if (
            f[3:6] != [self.scope, self.binding["release"], self.binding["policy"]]
            or int(f[7]) > now
            or int(f[8]) <= now
        ):
            raise ValueError("WORK_BINDING_OR_TIME")
        with self.store.transaction() as events:
            self.check(events)
            works = [e["work"] for e in events.records if e["kind"] == "work"]
            for old in works:
                old_fields, _ = parse_work(old)
                if old_fields[1] == f[1]:
                    if old != work:
                        raise ValueError("WORK_ID_CONFLICT")
                    return False
            if int(f[6]) != len(works) + 1:
                raise ValueError("WORK_SEQUENCE_GAP")
            events.append(
                dict(
                    kind="work",
                    work=work,
                    envelope=envelope.model_dump(mode="json"),
                    published_at=now,
                    execution_enabled=False,
                )
            )
        return True

    def exchange(self, raw, now):
        frame = Frame.decode(
            raw, self.key, direction="C2S", scope=self.scope, client=self.client, now=now
        )
        if frame.operation not in {"PULL", "REPORT"}:
            raise ValueError("UNSUPPORTED_OPERATION")
        with self.store.transaction() as events:
            self.check(events)
            exchanges = [e for e in events.records if e["kind"] == "exchange"]
            if exchanges and now < exchanges[-1]["at"]:
                raise ValueError("CLOCK_REGRESSION")
            for old in exchanges:
                if old["nonce"] == frame.nonce:
                    if old["request_hash"] != digest(raw.decode("ascii")):
                        raise ValueError("NONCE_CONFLICT")
                    # The original signed expiry is retained, even on retry.
                    return old["response"].encode("ascii")
            works = [e["work"] for e in events.records if e["kind"] == "work"]
            receipts = {
                e["receipt"].split("\t")[1]: e["receipt"]
                for e in events.records
                if e["kind"] == "receipt"
            }
            pending = [w for w in works if w.split("\t")[1] not in receipts]
            if frame.operation == "PULL":
                if frame.payload:
                    raise ValueError("INVALID_PULL")
                operation, payload = ("WORK", pending[0]) if pending else ("EMPTY", "")
            else:
                parts = frame.payload.split("\t")
                if len(parts) != 10:
                    raise ValueError("INVALID_RECEIPT")
                work = next((w for w in works if w.split("\t")[1] == parts[1]), None)
                if work is None:
                    raise ValueError("UNKNOWN_WORK")
                parse_receipt(frame.payload, work)
                old = receipts.get(parts[1])
                if old is not None and old != frame.payload:
                    raise ValueError("RECEIPT_CONFLICT")
                if old is None:
                    if not pending or work != pending[0] or int(parts[5]) > now + 2000:
                        raise ValueError("RECEIPT_SEQUENCE_OR_TIME")
                    events.append(
                        dict(
                            kind="receipt",
                            receipt=frame.payload,
                            received_at=now,
                            execution_enabled=False,
                        )
                    )
                operation, payload = "ACK", digest(frame.payload)
            response = Frame(
                "S2C", self.scope, self.client, frame.nonce, now, now + 5000, operation, payload
            ).encode(self.key)
            events.append(
                dict(
                    kind="exchange",
                    nonce=frame.nonce,
                    at=now,
                    request_hash=digest(raw.decode("ascii")),
                    response=response.decode("ascii"),
                    execution_enabled=False,
                )
            )
            return response  # context manager commits before the caller receives bytes

    def status(self, now):
        with self.store.transaction() as events:
            self.check(events)
            last = next(
                (e["at"] for e in reversed(events.records) if e["kind"] == "exchange"), None
            )
            receipts = [e["receipt"].split("\t") for e in events.records if e["kind"] == "receipt"]
        return dict(
            execution_enabled=False,
            connected_acceptance=False,
            channels={
                "EA": dict(
                    capability="SHADOW_DELIVERY",
                    last_success_ms=last,
                    state="CONNECTING"
                    if last is None
                    else "HEALTHY"
                    if 0 <= now - last <= 15000
                    else "DISCONNECTED",
                    quote_age_ms=None,
                    delivery_latency_ms=None,
                ),
                "PYTHON_PACKAGE": dict(state="NOT_OBSERVED", quote_age_ms=None),
                "MCP": dict(state="NOT_OBSERVED", quote_age_ms=None),
            },
            shadow_results=[
                dict(
                    request_id=r[1],
                    reason=r[4],
                    measured_at_ms=int(r[5]),
                    snapshot_quote_age_upper_ms=int(r[6]),
                    proposed_volume=str(Decimal(r[7])),
                    execution_enabled=False,
                )
                for r in receipts
            ],
        )


class Application:
    """Small WSGI boundary for a separately configured private HTTPS listener.

    Never trust X-Forwarded-Proto. TLS termination/server provisioning is external.
    Tests supply a real loopback TLS listener; this module starts no service.
    """

    def __init__(self, backend, clock=None):
        self.backend = backend
        self.clock = clock or (lambda: time.time_ns() // 1000000)

    def __call__(self, environ, start_response):
        code, data = "400 Bad Request", b"INVALID_REQUEST"
        try:
            if (
                environ.get("wsgi.url_scheme") != "https"
                or environ.get("REQUEST_METHOD") != "POST"
                or environ.get("PATH_INFO") != PATH
                or environ.get("QUERY_STRING", "")
                or environ.get("HTTP_TRANSFER_ENCODING")
                or environ.get("CONTENT_TYPE") != "application/octet-stream"
            ):
                raise ValueError("INVALID_REQUEST")
            size = int(environ.get("CONTENT_LENGTH", "0"))
            if not 0 < size <= MAX_BODY:
                raise ValueError("INVALID_LENGTH")
            raw = environ["wsgi.input"].read(size)
            if len(raw) != size:
                raise ValueError("TRUNCATED_REQUEST")
            data = self.backend.exchange(raw, self.clock())
            code = "200 OK"
        except ValueError:
            code, data = "400 Bad Request", b"REQUEST_REJECTED"
        except Exception:
            code, data = "503 Service Unavailable", b"SHADOW_UNAVAILABLE"
        start_response(
            code,
            [
                ("Content-Type", "application/octet-stream"),
                ("Content-Length", str(len(data))),
                ("Cache-Control", "no-store"),
            ],
        )
        return [data]
