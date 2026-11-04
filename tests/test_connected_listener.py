import http.client
import shutil
import socket
import ssl
import subprocess
import threading
import time
from pathlib import Path

import pytest

from fx_talanta.connected_shadow.listener import listener


@pytest.fixture
def tls_material(tmp_path):
    openssl = shutil.which("openssl")
    if openssl is None:
        candidate = Path("C:/Program Files/Git/ucrt64/bin/openssl.exe")
        openssl = str(candidate) if candidate.exists() else None
    if openssl is None:
        pytest.skip("OpenSSL required for ephemeral TLS certificate")
    cert, key = tmp_path / "cert.pem", tmp_path / "key.pem"
    subprocess.run(
        [
            openssl,
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-days",
            "1",
            "-subj",
            "/CN=localhost",
            "-addext",
            "subjectAltName=DNS:localhost,IP:127.0.0.1",
            "-keyout",
            str(key),
            "-out",
            str(cert),
        ],
        check=True,
        capture_output=True,
    )
    return cert, key


@pytest.fixture
def server(tls_material):
    calls = []

    def app(environ, respond):
        data = environ["wsgi.input"].read(int(environ["CONTENT_LENGTH"]))
        calls.append(data)
        respond("200 OK", [("Content-Length", "2")])
        return [b"OK"]

    cert, key = tls_material
    server = listener(app, cert, key, request_timeout=0.4)
    thread = threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True
    )
    thread.start()
    yield server, ssl.create_default_context(cafile=str(cert)), calls
    server.shutdown()
    server.server_close()
    thread.join(timeout=2)
    assert not thread.is_alive() and not server.deadlines


def connect(server, context):
    sock = socket.create_connection(server.server_address, timeout=2)
    return context.wrap_socket(sock, server_hostname="127.0.0.1")


@pytest.fixture
def reusable_server(tls_material):
    cert, key = tls_material
    calls = []

    def app(environ, respond):
        calls.append(environ["wsgi.input"].read(int(environ["CONTENT_LENGTH"])))
        respond("200 OK", [("Content-Length", "2")])
        return [b"OK"]

    server = listener(app, cert, key, request_timeout=0.4, keep_alive=True)
    thread = threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True
    )
    thread.start()
    yield server, ssl.create_default_context(cafile=str(cert)), calls
    server.shutdown()
    server.server_close()
    thread.join(timeout=2)
    assert not thread.is_alive() and not server.deadlines


def test_opt_in_reuse_is_limited_to_four_requests(reusable_server):
    server, context, calls = reusable_server
    c = http.client.HTTPSConnection(*server.server_address, context=context, timeout=2)
    try:
        c.connect()
        original = c.sock
        for i in range(4):
            c.request("POST", "/v1/shadow", b"x")
            response = c.getresponse()
            assert response.status == 200 and response.read() == b"OK"
            assert response.getheader("Connection") == ("keep-alive" if i < 3 else "close")
            assert c.sock is original if i < 3 else c.sock is None
        assert calls == [b"x"] * 4
    finally:
        c.close()


def test_reuse_does_not_reset_absolute_connection_deadline(reusable_server):
    server, context, _ = reusable_server
    c = http.client.HTTPSConnection(*server.server_address, context=context, timeout=2)
    try:
        c.request("POST", "/v1/shadow", b"x")
        assert c.getresponse().read() == b"OK"
        with server.deadline_lock:
            timer = next(iter(server.deadlines.values()))[1]
        time.sleep(0.12)
        c.request("POST", "/v1/shadow", b"x")
        assert c.getresponse().read() == b"OK"
        with server.deadline_lock:
            assert next(iter(server.deadlines.values()))[1] is timer
        timer.join(timeout=0.8)
        assert not timer.is_alive()
        c.sock.settimeout(0.5)
        assert c.sock.recv(1) == b""
    finally:
        c.close()


def test_reuse_closes_on_protocol_error(reusable_server):
    server, context, _ = reusable_server
    c = http.client.HTTPSConnection(*server.server_address, context=context, timeout=2)
    try:
        c.request("POST", "/v1/shadow", b"x")
        assert c.getresponse().read() == b"OK"
        c.request("GET", "/v1/shadow")
        response = c.getresponse()
        assert response.status == 501
        response.read()
        assert c.sock is None
    finally:
        c.close()


def test_repeated_native_style_requests_explicitly_close_each_response(server):
    server, context, calls = server
    connection = http.client.HTTPSConnection(*server.server_address, context=context, timeout=2)
    try:
        for payload in (b"SYNC", b"PULL", b"REPORT"):
            connection.request(
                "POST", "/v1/connected-shadow", payload, headers={"Connection": "close"}
            )
            response = connection.getresponse()
            assert response.status == 200 and response.getheader("Connection") == "close"
            assert response.read() == b"OK"
            assert connection.sock is None
        assert calls == [b"SYNC", b"PULL", b"REPORT"]
    finally:
        connection.close()


def test_clock_channel_disables_coalescing_on_the_actual_accepted_tls_socket(server):
    server, context, _ = server
    sock = connect(server, context)
    try:
        with server.deadline_lock:
            accepted = [entry[0] for entry in server.deadlines.values()]
            assert len(accepted) == 1
            assert accepted[0].getsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY) == 1
    finally:
        sock.close()


@pytest.mark.parametrize("part", ["headers", "body"])
def test_absolute_deadline_closes_slow_sender_and_releases_worker(server, part):
    server, context, _ = server
    sock = connect(server, context)
    try:
        started = time.monotonic()
        if part == "headers":
            sock.sendall(b"POST /v1/connected-shadow HTTP/1.1\r\nHost: localhost\r\nX-Slow: ")
        else:
            sock.sendall(
                b"POST /v1/connected-shadow HTTP/1.1\r\nHost: localhost\r\n"
                b"Content-Length: 4\r\n\r\n"
            )
        for piece in (b"a", b"b"):
            time.sleep(0.12)  # Below the socket idle timeout, but consumes total budget.
            sock.sendall(piece)
        sock.settimeout(0.8)
        try:
            assert sock.recv(1) == b""
        except (ssl.SSLError, ConnectionResetError, ConnectionAbortedError):
            pass
        assert time.monotonic() - started < 1.1
    finally:
        sock.close()
    connection = http.client.HTTPSConnection(*server.server_address, context=context, timeout=2)
    try:
        connection.request("POST", "/v1/connected-shadow", b"x")
        response = connection.getresponse()
        assert response.status == 200 and response.read() == b"OK"
    finally:
        connection.close()


def test_untrusted_certificate_is_rejected_and_plain_tcp_handshake_is_bounded(server):
    server, _, calls = server
    with pytest.raises(ssl.SSLCertVerificationError):
        connect(server, ssl.create_default_context())
    sock = socket.create_connection(server.server_address, timeout=2)
    try:
        started = time.monotonic()
        sock.settimeout(0.8)
        assert sock.recv(1) == b""
        assert time.monotonic() - started < 1.1
    finally:
        sock.close()
    assert calls == []


@pytest.mark.parametrize(
    "message, expected",
    [
        ("LEASE_EXPIRED", "LEASE_EXPIRED"),
        ("private-account-or-secret-value", "VALIDATION_REJECTED"),
    ],
)
def test_request_audit_records_only_allowlisted_rejection_codes(message, expected):
    import io
    from types import SimpleNamespace

    from fx_talanta.shadow.backend import Application

    def reject(*args):
        raise ValueError(message)

    audit = []
    application = Application(
        SimpleNamespace(exchange=reject), audit=lambda kind, **fields: audit.append((kind, fields))
    )
    codes = []
    result = application(
        {
            "wsgi.url_scheme": "https",
            "REQUEST_METHOD": "POST",
            "PATH_INFO": "/v1/shadow",
            "CONTENT_TYPE": "application/octet-stream",
            "CONTENT_LENGTH": "1",
            "wsgi.input": io.BytesIO(b"x"),
        },
        lambda code, headers: codes.append(code),
    )
    assert result == [b"REQUEST_REJECTED"] and codes == ["400 Bad Request"]
    assert audit == [("APPLICATION_REJECTED", {"reason": expected})]
