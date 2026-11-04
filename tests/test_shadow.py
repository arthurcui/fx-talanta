import io
import json
import shutil
import socket
import ssl
import subprocess
import threading
from decimal import Decimal
from http.client import RemoteDisconnected
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
import pytest

from fx_talanta.domain.models import Environment
from fx_talanta.shadow.backend import Application, Backend
from fx_talanta.shadow.client import HTTPS, Client
from fx_talanta.shadow.store import PostgresStore, SQLiteStore
from fx_talanta.shadow.wire import Frame
from fx_talanta.shadow.work import FIELDS, assess, parse_receipt, project, scope_for
from fx_talanta.storage.config import fixture_account
from tools.fixtures.shadow_fixtures import ACCOUNT, CLIENT, KEY, NOW, POLICY, RELEASE, ROOT, work


def backend(store, bootstrap=True):
    return Backend(store, ACCOUNT, CLIENT, RELEASE, POLICY, KEY, bootstrap=bootstrap)


def client(store, bootstrap=True):
    return Client(store, scope_for(ACCOUNT), CLIENT, RELEASE, POLICY, KEY, bootstrap=bootstrap)


@pytest.fixture
def pair(tmp_path):
    b = backend(SQLiteStore(tmp_path / "backend.db", bootstrap=True))
    c = client(SQLiteStore(tmp_path / "client.db", bootstrap=True))
    b.publish(*work(), NOW)
    return b, c


def records(store, kind):
    with store.transaction() as events:
        return [e for e in events.records if e["kind"] == kind]


def test_durable_lost_ack_restart_duplicate_and_no_reevaluation(pair):
    b, c = pair

    def exchange(raw):
        return b.exchange(raw, NOW)

    assert c.step(exchange, lambda: NOW) == "WORK"
    original = records(c.store, "receipt")[0]["receipt"]

    def lost(raw):
        b.exchange(raw, NOW)
        raise ConnectionError("response lost after backend commit")

    with pytest.raises(ConnectionError):
        c.step(lost, lambda: NOW)
    assert len(records(b.store, "receipt")) == 1
    assert not records(c.store, "ack")
    c = client(c.store, False)
    b = backend(b.store, False)
    # The old receipt survives a restart and a long outage. New auth TTL does
    # not renew quote age or change its original verdict timestamp.
    assert c.step(lambda raw: b.exchange(raw, NOW + 90000), lambda: NOW + 90000) == "ACK"
    assert records(b.store, "receipt")[0]["receipt"] == original
    assert len(records(b.store, "receipt")) == 1
    assert c.step(lambda raw: b.exchange(raw, NOW + 90000), lambda: NOW + 90000) == "EMPTY"
    assert b.status(NOW + 90000)["execution_enabled"] is False


@pytest.mark.parametrize(
    "elapsed,reason",
    [(0, "ACCEPTED"), (1490, "ACCEPTED"), (1491, "QUOTE_STALE"), (60000, "EXPIRED")],
)
def test_unchanged_two_second_boundary_and_expiry(pair, elapsed, reason):
    b, c = pair
    c.step(lambda raw: b.exchange(raw, NOW + elapsed), lambda: NOW + elapsed)
    receipt = records(c.store, "receipt")[0]["receipt"]
    assert receipt.split("\t")[4] == reason
    c.step(lambda raw: b.exchange(raw, NOW + elapsed), lambda: NOW + elapsed)
    status = b.status(NOW + elapsed)
    assert status["channels"]["EA"]["state"] == "HEALTHY"
    assert status["channels"]["EA"]["quote_age_ms"] is None
    assert status["channels"]["MCP"]["state"] == "NOT_OBSERVED"
    assert status["channels"]["PYTHON_PACKAGE"]["state"] == "NOT_OBSERVED"
    assert status["shadow_results"][0]["reason"] == reason
    assert b.status(NOW + elapsed + 15001)["channels"]["EA"]["state"] == "DISCONNECTED"


def test_native_clock_uncertainty_is_a_veto_not_a_renewal():
    w = project(*work())
    receipt = assess(w, NOW, 1000)
    assert receipt.split("\t")[4] == "CLOCK_UNVERIFIED"
    parse_receipt(receipt, w)


@pytest.mark.parametrize(
    "mutation", ["key", "account", "client", "direction", "expired", "oversize"]
)
def test_auth_route_and_bounds_leave_journal_unchanged(pair, mutation):
    b, _ = pair
    f = Frame("C2S", b.scope, CLIENT, "d" * 64, NOW, NOW + 5000, "PULL", "")
    from dataclasses import replace

    if mutation == "account":
        f = replace(f, scope="e" * 64)
    if mutation == "client":
        f = replace(f, client="e" * 64)
    if mutation == "direction":
        f = replace(f, direction="S2C")
    raw = f.encode(b"x" * 32 if mutation == "key" else KEY)
    if mutation == "oversize":
        raw += b"x" * 32768
    with pytest.raises(ValueError):
        b.exchange(raw, NOW + 5000 if mutation == "expired" else NOW)
    assert not records(b.store, "exchange")


def test_nonce_replay_conflict_and_original_response_expiry(pair):
    b, _ = pair
    f = Frame("C2S", b.scope, CLIENT, "d" * 64, NOW, NOW + 5000, "PULL", "")
    raw = f.encode(KEY)
    first = b.exchange(raw, NOW)
    assert b.exchange(raw, NOW + 1) == first
    assert len(records(b.store, "exchange")) == 1
    other = Frame("C2S", b.scope, CLIENT, "d" * 64, NOW + 1, NOW + 5001, "PULL", "")
    with pytest.raises(ValueError, match="NONCE_CONFLICT"):
        b.exchange(other.encode(KEY), NOW + 1)


def test_work_sequence_hash_conflict_and_snapshot_binding(pair):
    b, _ = pair
    assert b.publish(*work(), NOW) is False
    with pytest.raises(ValueError, match="WORK_ID_CONFLICT"):
        b.publish(*work(quote_age_ms=501), NOW)
    with pytest.raises(ValueError, match="WORK_SEQUENCE_GAP"):
        b.publish(*work(3), NOW)
    envelope, snapshot = work()
    with pytest.raises(ValueError, match="SNAPSHOT_REQUEST_MISMATCH"):
        project(envelope, snapshot.model_copy(update={"stop": Decimal("1.097")}))


def test_reject_expanded_native_verdict_and_receipt_conflicts(pair):
    b, c = pair
    c.step(lambda raw: b.exchange(raw, NOW), lambda: NOW)
    receipt = records(c.store, "receipt")[0]["receipt"]
    parts = receipt.split("\t")
    parts[7] = "1"
    f = Frame("C2S", b.scope, CLIENT, "e" * 64, NOW, NOW + 5000, "REPORT", "\t".join(parts))
    with pytest.raises(ValueError, match="NATIVE_VERDICT_MISMATCH"):
        b.exchange(f.encode(KEY), NOW)
    assert not records(b.store, "receipt")
    c.step(lambda raw: b.exchange(raw, NOW), lambda: NOW)
    modified = assess(records(c.store, "receipt")[0]["work"], NOW + 10)
    f = Frame("C2S", b.scope, CLIENT, "f" * 64, NOW, NOW + 5000, "REPORT", modified)
    with pytest.raises(ValueError, match="RECEIPT_CONFLICT"):
        b.exchange(f.encode(KEY), NOW + 10)


def test_missing_inbox_wrong_binding_and_second_writer_fail_closed(pair, tmp_path):
    b, c = pair
    with pytest.raises(ValueError, match="MISSING_JOURNAL"):
        SQLiteStore(tmp_path / "missing")
    with pytest.raises(ValueError, match="BINDING_CONFLICT"):
        Backend(b.store, ACCOUNT, CLIENT, RELEASE, "f" * 64, KEY)
    with c.store.transaction():
        import sqlite3

        with pytest.raises(sqlite3.OperationalError, match="locked"):
            c.step(lambda raw: b.exchange(raw, NOW), lambda: NOW)


def test_backend_checkpoint_rollback_is_not_a_new_evaluation(pair, tmp_path):
    b, c = pair
    c.step(lambda raw: b.exchange(raw, NOW), lambda: NOW)
    c.step(lambda raw: b.exchange(raw, NOW), lambda: NOW)
    restored = backend(SQLiteStore(tmp_path / "restored.db", bootstrap=True))
    restored.publish(*work(), NOW)
    with pytest.raises(ValueError, match="BACKEND_CHECKPOINT_CONFLICT"):
        c.step(lambda raw: restored.exchange(raw, NOW), lambda: NOW)


def test_network_and_database_failure_keep_pending_receipt(pair):
    b, c = pair
    c.step(lambda raw: b.exchange(raw, NOW), lambda: NOW)

    def unavailable(raw):
        raise OSError("unavailable")

    with pytest.raises(OSError):
        c.step(unavailable, lambda: NOW)
    assert len(records(c.store, "receipt")) == 1 and not records(c.store, "ack")


def test_https_configuration_and_wsgi_never_allow_http_or_trusted_forward_headers(pair):
    b, _ = pair
    for url in (
        "http://localhost/v1/shadow",
        "https://user@localhost/v1/shadow",
        "https://localhost/v1/shadow?account=other",
    ):
        with pytest.raises(ValueError):
            HTTPS(url)
    with pytest.raises(ValueError):
        HTTPS("https://localhost/v1/shadow", ssl._create_unverified_context())
    app = Application(b)
    status = []
    assert app(
        {"wsgi.url_scheme": "http", "HTTP_X_FORWARDED_PROTO": "https"},
        lambda code, _: status.append(code),
    ) == [b"REQUEST_REJECTED"]
    assert status == ["400 Bad Request"]


def test_actual_tls_roundtrip_lost_response_and_untrusted_certificate(pair, tmp_path):
    b, c = pair
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
    app = Application(b, lambda: NOW)
    drop = [False]

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            status = []
            result = app(
                {
                    "wsgi.url_scheme": "https",
                    "REQUEST_METHOD": "POST",
                    "PATH_INFO": self.path,
                    "CONTENT_TYPE": self.headers.get("Content-Type"),
                    "CONTENT_LENGTH": self.headers.get("Content-Length"),
                    "wsgi.input": self.rfile,
                },
                lambda code, headers: status.append((code, headers)),
            )
            if drop[0]:
                drop[0] = False
                self.connection.shutdown(socket.SHUT_RDWR)
                self.connection.close()
                return
            self.send_response(int(status[0][0].split()[0]))
            for k, v in status[0][1]:
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(b"".join(result))

    server = HTTPServer(("127.0.0.1", 0), Handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert, key)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"https://127.0.0.1:{server.server_port}/v1/shadow"
    transport = HTTPS(url, ssl.create_default_context(cafile=str(cert)))
    try:
        assert c.step(transport, lambda: NOW) == "WORK"
        drop[0] = True
        with pytest.raises((ConnectionError, RemoteDisconnected)):
            c.step(transport, lambda: NOW)
        assert len(records(b.store, "receipt")) == 1
        assert c.step(transport, lambda: NOW) == "ACK"
        with pytest.raises(ssl.SSLCertVerificationError):
            c.step(HTTPS(url), lambda: NOW)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_native_field_order_and_no_mutation_surface():
    text = (ROOT / "mql5/shadow/Fields.mqh").read_text()
    assert '"' + "\\t".join(FIELDS) + '"' in text
    for name in ("ShadowEA.mq5", "Protocol.mqh", "Inbox.mqh"):
        source = (ROOT / "mql5/shadow" / name).read_text()
        assert "OrderSend(" not in source and "CTrade" not in source and "OrderCheck(" not in source
    assert "input bool EnableShadow=false" in (ROOT / "mql5/shadow/ShadowEA.mq5").read_text()


@pytest.mark.integration
def test_postgres_transport_restart_immutability_and_live_refusal(settings, tmp_path):
    store = PostgresStore(settings.runtime_dsn(Environment.PAPER), ACCOUNT, uuid4())
    b = backend(store)
    c = client(SQLiteStore(tmp_path / "pgclient.db", bootstrap=True))
    b.publish(*work(), NOW)
    c.step(lambda raw: b.exchange(raw, NOW), lambda: NOW)
    c.step(lambda raw: b.exchange(raw, NOW), lambda: NOW)
    assert len(backend(store, False).status(NOW)["shadow_results"]) == 1
    with psycopg.connect(settings.runtime_dsn(Environment.PAPER)) as db:
        with pytest.raises(psycopg.Error):
            db.execute("DELETE FROM fx.shadow_events WHERE stream=%s", (store.stream,))
    with pytest.raises(ValueError, match="PAPER_REQUIRED"):
        PostgresStore(
            settings.runtime_dsn(Environment.LIVE), fixture_account(Environment.LIVE), uuid4()
        )


@pytest.mark.integration
def test_postgres_concurrent_publication_and_wrong_database_binding(settings):
    from concurrent.futures import ThreadPoolExecutor

    store = PostgresStore(settings.runtime_dsn(Environment.PAPER), ACCOUNT, uuid4())
    b = backend(store)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: b.publish(*work(), NOW), range(2)))
    assert sorted(results) == [False, True]
    assert len(records(store, "work")) == 1
    wrong = ACCOUNT.model_copy(update={"login": "different-synthetic-account"})
    with pytest.raises(ValueError, match="ACCOUNT_BINDING_MISMATCH"):
        Backend(
            PostgresStore(store.dsn, wrong, uuid4()),
            wrong,
            CLIENT,
            RELEASE,
            POLICY,
            KEY,
            bootstrap=True,
        )


@pytest.mark.integration
def test_database_unavailable_returns_503_and_retains_local_receipt(settings, tmp_path):
    from psycopg.conninfo import make_conninfo

    store = PostgresStore(settings.runtime_dsn(Environment.PAPER), ACCOUNT, uuid4())
    b = backend(store)
    c = client(SQLiteStore(tmp_path / "outage.db", bootstrap=True))
    b.publish(*work(), NOW)
    c.step(lambda raw: b.exchange(raw, NOW), lambda: NOW)
    # An explicitly unresolvable database name on the same test instance causes
    # a real connection failure; do not stop the shared PostgreSQL host.
    original = store.dsn
    store.dsn = make_conninfo(original, dbname="missing_shadow_" + uuid4().hex)
    app = Application(b, lambda: NOW)

    def unavailable(raw):
        statuses = []
        result = app(
            {
                "wsgi.url_scheme": "https",
                "REQUEST_METHOD": "POST",
                "PATH_INFO": "/v1/shadow",
                "CONTENT_TYPE": "application/octet-stream",
                "CONTENT_LENGTH": str(len(raw)),
                "wsgi.input": io.BytesIO(raw),
            },
            lambda code, _: statuses.append(code),
        )
        assert statuses == ["503 Service Unavailable"]
        assert result == [b"SHADOW_UNAVAILABLE"]
        raise ConnectionError("bounded backend failure")

    with pytest.raises(ConnectionError):
        c.step(unavailable, lambda: NOW)
    assert not records(c.store, "ack")
    store.dsn = original
    assert c.step(lambda raw: b.exchange(raw, NOW), lambda: NOW) == "ACK"


def test_published_native_evidence_and_preserved_historical_artifacts(historical_source):
    report = json.loads((ROOT / "docs/evidence/m2d-shadow-20261103.json").read_text())
    import hashlib

    for path, expected in report["source_sha256"].items():
        assert hashlib.sha256(historical_source(path, expected)).hexdigest() == expected
    for path, expected in report["historical_sha256"].items():
        assert hashlib.sha256(historical_source(path, expected)).hexdigest() == expected
    assert len(report["native"]["parity"]) == 60
    assert len(report["native"]["checks"]) == 80
    assert all(x == "PASS" for x in report["native"]["checks"].values())
    assert not report["native_https_tested"] and not report["execution_enabled"]


@pytest.mark.integration
def test_shadow_archive_retains_pending_receipt_and_blocks_unreleased_writer(settings, tmp_path):
    from dataclasses import replace

    from fx_talanta.storage.archive import export_archive, release_restore, restore_archive
    from fx_talanta.storage.bootstrap import bootstrap

    source = replace(settings, namespace="fx_shsrc_" + uuid4().hex[:10])
    target = replace(settings, namespace="fx_shdst_" + uuid4().hex[:10])
    bootstrap(source)
    bootstrap(target)
    stream = uuid4()
    before = backend(PostgresStore(source.runtime_dsn(Environment.PAPER), ACCOUNT, stream))
    before.publish(*work(), NOW)
    c = client(SQLiteStore(tmp_path / "archive-client.db", bootstrap=True))
    c.step(lambda raw: before.exchange(raw, NOW), lambda: NOW)
    c.step(lambda raw: before.exchange(raw, NOW), lambda: NOW)
    path = tmp_path / "shadow.fxbackup"
    export_archive(source, path)
    restore_archive(target, path)
    restored = backend(PostgresStore(target.runtime_dsn(Environment.PAPER), ACCOUNT, stream), False)
    with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState):
        c.step(lambda raw: restored.exchange(raw, NOW), lambda: NOW)
    release_restore(target, path, source_retired=True)
    assert restored.status(NOW)["shadow_results"] == before.status(NOW)["shadow_results"]
    assert c.step(lambda raw: restored.exchange(raw, NOW), lambda: NOW) == "EMPTY"


def test_shadow_archive_validator_rejects_wrong_account_and_corruption(pair):
    from fx_talanta.storage.archive import validate_shadow_archive

    b, _ = pair
    import sqlite3

    with sqlite3.connect(b.store.path) as db:
        rows = [
            dict(stream=str(UUID(int=500)), seq=s, scope=b.scope, body=body, prior=prior, hash=h)
            for s, body, prior, h in db.execute("SELECT * FROM events ORDER BY seq")
        ]
    validate_shadow_archive(rows, ACCOUNT)
    with pytest.raises(ValueError, match="account mismatch"):
        validate_shadow_archive(rows, ACCOUNT.model_copy(update={"login": "wrong"}))
    rows[-1]["hash"] = "0" * 64
    with pytest.raises(ValueError, match="JOURNAL_INTEGRITY"):
        validate_shadow_archive(rows, ACCOUNT)


def test_legacy_archive_reading_cannot_omit_new_schema_state(tmp_path):
    import zipfile
    from hashlib import sha256

    from fx_talanta.storage import archive

    files = {
        f"{e.value}/{t}.jsonl": b""
        for e in Environment
        for t in archive.TABLES
        if t != "shadow_events"
    }
    manifest = dict(
        format="fx-talanta-fixture-archive/1",
        archive_id=str(uuid4()),
        accounts={
            e.value: dict(
                binding=[
                    dict(
                        singleton=True,
                        identity=fixture_account(e).model_dump(mode="json"),
                        execution_enabled=False,
                    )
                ],
                migrations=[[6, "historical-schema-checksum"]],
            )
            for e in Environment
        },
        files={n: dict(sha256=sha256(v).hexdigest(), rows=0, bytes=0) for n, v in files.items()},
    )
    for version in (6, 7):
        manifest["accounts"]["PAPER"]["migrations"][0][0] = version
        path = tmp_path / f"legacy-{version}.fxbackup"
        with zipfile.ZipFile(path, "w") as bundle:
            for name, value in files.items():
                bundle.writestr(name, value)
            bundle.writestr("manifest.json", archive.encode(manifest))
        if version == 6:
            assert archive.read_archive(path)[0]["format"].endswith("/1")
        else:
            with pytest.raises(ValueError, match="cannot omit"):
                archive.read_archive(path)
