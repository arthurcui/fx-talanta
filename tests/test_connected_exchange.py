"""Actual TLS sockets and durable service, with synthetic account/time/observations."""

import http.client
import ssl
import threading

import pytest

from fx_talanta.connected_shadow.listener import listener
from fx_talanta.connected_shadow.service import ConnectedApplication, Service, hold_receipt
from fx_talanta.shadow.wire import Frame, digest
from tests.test_connected_listener import tls_material as tls_material
from tests.test_connected_service import CLIENT, INC, KEY, NOW
from tests.test_connected_service import service as service


def test_tls_lost_ack_replay_and_backend_restart_retain_one_receipt(service, tls_material):
    s, at = service
    cert, key = tls_material
    drop = [False]

    def drop_once():
        value, drop[0] = drop[0], False
        return value

    app = ConnectedApplication(s)
    server = listener(app, cert, key, drop_response=drop_once)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.02})
    thread.start()
    context = ssl.create_default_context(cafile=str(cert))

    def request(op, nonce, receipt="", path="/v1/connected-shadow"):
        payload = f"connected/1\t{op}\t{INC}\t1"
        if op == "REPORT":
            payload += "\t" + receipt.encode().hex()
        body = Frame(
            "C2S",
            s.scope,
            CLIENT,
            nonce,
            NOW,
            NOW + 5000,
            "REPORT" if op == "REPORT" else "PULL",
            payload,
        ).encode(KEY)
        connection = http.client.HTTPSConnection(*server.server_address, context=context, timeout=2)
        try:
            connection.request("POST", path, body, {"Content-Type": "application/octet-stream"})
            response = connection.getresponse()
            data = response.read()
            if response.status != 200:
                return response.status
            return Frame.decode(
                data, KEY, direction="S2C", scope=s.scope, client=CLIENT, now=NOW, nonce=nonce
            )
        finally:
            connection.close()

    try:
        assert request("SYNC", "a" * 64).payload == f"connected/1\tCLOCK\t{NOW}\t10"
        assert request("SYNC", "a" * 64) == 400  # No old sample as a new RTT measurement.
        assert request("SYNC", "f" * 64, path="/v1/shadow") == 404
        work = request("PULL", "b" * 64).payload
        receipt = hold_receipt(work, NOW, 40, NOW - 400)
        drop[0] = True
        with pytest.raises(http.client.RemoteDisconnected):
            request("REPORT", "c" * 64, receipt)
        assert s.status()["receipt_count"] == 1
        # Replace only the owned backend object, retaining its durable journals.
        app.backend = Service(s.store, s.authority, s.account, CLIENT, INC, 1, KEY, s.clock)
        assert request("REPORT", "c" * 64, receipt).payload == digest(receipt)
        assert request("REPORT", "d" * 64, receipt).payload == digest(receipt)
        assert app.backend.status()["receipt_count"] == 1
        assert request("PULL", "e" * 64).operation == "EMPTY"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
        assert not thread.is_alive()
