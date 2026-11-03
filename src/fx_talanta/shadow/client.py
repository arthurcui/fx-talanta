"""No-order reference client with a durable receipt outbox and verified HTTPS."""

import http.client
import secrets
import ssl
import time
from urllib.parse import urlsplit

from fx_talanta.shadow.wire import MAX_BODY, PATH, Frame, digest
from fx_talanta.shadow.work import assess, parse_receipt, parse_work


class HTTPS:
    def __init__(self, url, context=None):
        self.url = urlsplit(url)
        if (
            self.url.scheme != "https"
            or not self.url.hostname
            or self.url.path != PATH
            or self.url.username
            or self.url.password
            or self.url.query
            or self.url.fragment
        ):
            raise ValueError("PINNED_HTTPS_ROUTE_REQUIRED")
        self.context = context or ssl.create_default_context()
        if not self.context.check_hostname or self.context.verify_mode != ssl.CERT_REQUIRED:
            raise ValueError("VERIFIED_TLS_REQUIRED")

    def __call__(self, raw):
        connection = http.client.HTTPSConnection(
            self.url.hostname, self.url.port or 443, context=self.context, timeout=2
        )
        try:
            connection.request("POST", PATH, raw, {"Content-Type": "application/octet-stream"})
            response = connection.getresponse()
            if response.status != 200:  # No redirect, credential forwarding or HTTP fallback.
                raise ValueError("ENDPOINT_REJECTED")
            result = response.read(MAX_BODY + 1)
            if len(result) > MAX_BODY:
                raise ValueError("RESPONSE_TOO_LARGE")
            return result
        finally:
            connection.close()


class Client:
    def __init__(self, store, scope, client, release, policy, key, *, bootstrap=False):
        self.store, self.key = store, key
        self.binding = dict(
            kind="binding",
            scope=scope,
            client=client,
            release=release,
            policy=policy,
            key_hash=digest(key.hex()),
            execution_enabled=False,
        )
        with store.transaction() as events:
            if not events.records:
                if not bootstrap:
                    raise ValueError("MISSING_INBOX")
                events.append(self.binding)
            elif events.records[0] != self.binding or bootstrap:
                raise ValueError("INBOX_BINDING_CONFLICT")

    def step(self, transport, clock=None):
        """One bounded exchange; caller schedules backoff. Never an automatic retry loop."""
        clock = clock or (lambda: time.time_ns() // 1000000)
        # Hold the local writer lock through the one bounded exchange. Another
        # process cannot evaluate the same work concurrently using this journal.
        with self.store.transaction() as events:
            if not events.records or events.records[0] != self.binding:
                raise ValueError("INBOX_BINDING_CONFLICT")
            receipts = [e for e in events.records if e["kind"] == "receipt"]
            acked = {e["hash"] for e in events.records if e["kind"] == "ack"}
            pending = [e for e in receipts if digest(e["receipt"]) not in acked]
            payload = pending[0]["receipt"] if pending else ""
            now = clock()
            request = Frame(
                "C2S",
                self.binding["scope"],
                self.binding["client"],
                secrets.token_hex(32),
                now,
                now + 5000,
                "REPORT" if pending else "PULL",
                payload,
            )
            started = time.monotonic()
            raw = transport(request.encode(self.key))
            if time.monotonic() - started > 2:
                raise ValueError("EXCHANGE_TIMEOUT")
            observed = clock()
            if observed < now:
                raise ValueError("CLOCK_REGRESSION")
            response = Frame.decode(
                raw,
                self.key,
                direction="S2C",
                scope=request.scope,
                client=request.client,
                now=observed,
                nonce=request.nonce,
            )
            if pending:
                if response.operation != "ACK" or response.payload != digest(payload):
                    raise ValueError("ACK_MISMATCH")
                events.append(dict(kind="ack", hash=digest(payload), execution_enabled=False))
            elif response.operation == "WORK":
                work = response.payload
                f, _ = parse_work(work)
                if f[3:6] != [request.scope, self.binding["release"], self.binding["policy"]]:
                    raise ValueError("WORK_BINDING_CONFLICT")
                old = next((e for e in receipts if e["receipt"].split("\t")[1] == f[1]), None)
                if old:
                    if old["work"] != work:
                        raise ValueError("WORK_HASH_CONFLICT")
                    # Backend rollback/lost receipt cannot silently clear a local ACK.
                    raise ValueError("BACKEND_CHECKPOINT_CONFLICT")
                if int(f[6]) != len(receipts) + 1:
                    raise ValueError("WORK_SEQUENCE_GAP")
                receipt = assess(work, observed)
                parse_receipt(receipt, work)
                events.append(
                    dict(kind="receipt", work=work, receipt=receipt, execution_enabled=False)
                )
            elif response.operation != "EMPTY" or response.payload:
                raise ValueError("RESPONSE_MISMATCH")
            return response.operation
