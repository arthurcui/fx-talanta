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
