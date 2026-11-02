"""Verified snapshots of explicitly expected account pairs; no SQL or credentials.

Both accounts are fenced and locked while exporting. Restore never overwrites a
nonempty destination. Cross-database commits are not atomic: durable STAGED guards
keep a partial import blocked, and repeating the same archive safely resumes it.
"""

import json
import os
import tempfile
import zipfile
from contextlib import ExitStack, contextmanager
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb
from pydantic import ValidationError

from fx_talanta.domain.models import Environment, Record
from fx_talanta.domain.offline import BrokerBook, GatewayBook
from fx_talanta.storage.config import Settings, account_set
from fx_talanta.storage.offline import WRITER_LOCK, WriterBusy

FORMAT = "fx-talanta-fixture-archive/1"
DEMO_FORMAT = "fx-talanta-demo-observer-archive/1"
MAX_BYTES = 256 * 1024 * 1024
TABLES = {
    "records": "sequence",
    "record_links": "source_id, target_id, relation",
    "offline_journal": "recorded_at, run_id, stream, revision",
}
SCHEMA_TABLES = {*TABLES, "schema_migrations", "account_binding", "restore_history"}


def encode(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def rows(conn, table, order):
    # table/order are internal constants, never archive-supplied SQL.
    return [r[0] for r in conn.execute(f"SELECT to_jsonb(r) FROM fx.{table} r ORDER BY {order}")]


def metadata(conn):
    tables = {r[0] for r in conn.execute("SELECT tablename FROM pg_tables WHERE schemaname='fx'")}
    if tables != SCHEMA_TABLES:
        raise ValueError("unrecognized schema; archive support must cover every state table")
    return {
        "binding": rows(conn, "account_binding", "singleton"),
        "migrations": [
            list(r)
            for r in conn.execute(
                "SELECT version, checksum FROM fx.schema_migrations ORDER BY version"
            )
        ],
        "sequence": list(
            conn.execute("SELECT last_value, is_called FROM fx.records_sequence_seq").fetchone()
        ),
        "source_history": rows(conn, "restore_history", "sequence"),
    }


@contextmanager
def fenced(settings: Settings):
    with ExitStack() as stack:
        conns = {}
        for environment in Environment:
            conn = stack.enter_context(
                psycopg.connect(settings.admin_dsn(settings.database(environment)), autocommit=True)
            )
            conn.execute("SET TIME ZONE 'UTC'")
            conn.execute("SET lock_timeout='5s'")
            if not conn.execute("SELECT pg_try_advisory_lock(%s)", (WRITER_LOCK,)).fetchone()[0]:
                raise WriterBusy("stop the account's gateway before exporting or restoring")
            conns[environment.value] = conn
        yield conns


def data_bytes(conn, table):
    return b"".join(encode(row) + b"\n" for row in rows(conn, table, TABLES[table]))


def export_archive(settings: Settings, destination: Path, *, paper_account=None) -> dict:
    accounts = account_set(paper_account)
    if destination.exists():
        raise FileExistsError("archive destination already exists; choose a new filename")
    manifest = {
        "format": DEMO_FORMAT if paper_account else FORMAT,
        "archive_id": str(uuid4()),
        "created_at": datetime.now(UTC).isoformat(),
        "accounts": {},
        "files": {},
    }
    descriptor, temporary = tempfile.mkstemp(prefix=".fx-export-", dir=destination.parent)
    try:
        with (
            os.fdopen(descriptor, "w+b") as output,
            fenced(settings) as conns,
            ExitStack() as stack,
        ):
            # Acquire both account locks before reading either one. Records written by
            # non-gateway clients are also excluded until the archive is complete.
            for conn in conns.values():
                stack.enter_context(conn.transaction())
                conn.execute(
                    "LOCK TABLE fx.records, fx.record_links, fx.offline_journal, "
                    "fx.restore_history IN SHARE MODE"
                )
                last = conn.execute(
                    "SELECT status FROM fx.restore_history ORDER BY sequence DESC LIMIT 1"
                ).fetchone()
                if last and last[0] != "RELEASED":
                    raise ValueError("cannot export an unverified or partial restore")
            total = 0
            with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
                for name, conn in conns.items():
                    manifest["accounts"][name] = metadata(conn)
                    if manifest["accounts"][name]["binding"] != [
                        {
                            "singleton": True,
                            "identity": accounts[Environment(name)].model_dump(mode="json"),
                            "execution_enabled": False,
                        }
                    ]:
                        raise ValueError("export account binding differs from explicit expectation")
                    for table in TABLES:
                        payload = data_bytes(conn, table)
                        total += len(payload)
                        if total > MAX_BYTES:
                            raise ValueError("fixture archive exceeds supported size")
                        path = f"{name}/{table}.jsonl"
                        manifest["files"][path] = {
                            "sha256": sha256(payload).hexdigest(),
                            "rows": payload.count(b"\n"),
                            "bytes": len(payload),
                        }
                        archive.writestr(path, payload)
                manifest_bytes = encode(manifest)
                if total + len(manifest_bytes) > MAX_BYTES:
                    raise ValueError("fixture archive exceeds supported size")
                archive.writestr("manifest.json", manifest_bytes)
            output.flush()
            os.fsync(output.fileno())
        # Hard-link publication is atomic and refuses to replace an existing file.
        os.link(temporary, destination)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return {
        "archive_id": manifest["archive_id"],
        "files": manifest["files"],
        "execution_enabled": False,
    }


def read_archive(path: Path, *, paper_account=None):
    accounts = account_set(paper_account)
    expected = {f"{e.value}/{table}.jsonl" for e in Environment for table in TABLES}
    try:
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            if len(names) != len(expected) + 1 or set(names) != expected | {"manifest.json"}:
                raise ValueError("archive has missing, duplicate, or unexpected members")
            if sum(info.file_size for info in archive.infolist()) > MAX_BYTES:
                raise ValueError("archive exceeds supported size")
            manifest = json.loads(archive.read("manifest.json"))
            if (
                manifest["format"] != (DEMO_FORMAT if paper_account else FORMAT)
                or set(manifest["accounts"]) != {"PAPER", "LIVE"}
                or set(manifest["files"]) != expected
            ):
                raise ValueError("unsupported or incomplete fixture archive")
            UUID(manifest["archive_id"])
            data = {}
            for name in expected:
                payload = archive.read(name)
                wanted = manifest["files"][name]
                if (
                    sha256(payload).hexdigest() != wanted["sha256"]
                    or len(payload) != wanted["bytes"]
                    or payload.count(b"\n") != wanted["rows"]
                ):
                    raise ValueError("archive content checksum or count mismatch")
                data[name] = [json.loads(line) for line in payload.splitlines()]
            for environment in Environment:
                name = environment.value
                account = accounts[environment]
                if manifest["accounts"][name]["binding"] != [
                    {
                        "singleton": True,
                        "identity": account.model_dump(mode="json"),
                        "execution_enabled": False,
                    }
                ]:
                    raise ValueError("archive account binding or execution policy mismatch")
                for row in data[f"{name}/records.jsonl"]:
                    if Record.model_validate(row["payload"]).account != account:
                        raise ValueError("record belongs to the wrong account")
                for row in data[f"{name}/offline_journal.jsonl"]:
                    if (
                        row["stream"] not in {"gateway", "broker"}
                        or environment != Environment.PAPER
                        or account.venue != "SIMULATOR"
                    ):
                        raise ValueError("invalid offline journal scope")
                    model = GatewayBook if row["stream"] == "gateway" else BrokerBook
                    if model.model_validate(row["payload"]).account != account:
                        raise ValueError("journal belongs to the wrong account")
            return manifest, data
    except (
        zipfile.BadZipFile,
        KeyError,
        TypeError,
        json.JSONDecodeError,
        ValidationError,
    ) as error:
        raise ValueError("malformed fixture archive") from error


def marker(conn):
    return conn.execute(
        "SELECT archive_id, manifest_hash, status, source_history "
        "FROM fx.restore_history ORDER BY sequence DESC LIMIT 1"
    ).fetchone()


def append_marker(conn, manifest, status, source_history=()):
    conn.execute(
        "INSERT INTO fx.restore_history(archive_id,manifest_hash,status,source_history) "
        "VALUES (%s,%s,%s,%s)",
        (
            manifest["archive_id"],
            sha256(encode(manifest)).hexdigest(),
            status,
            Jsonb(source_history),
        ),
    )


def verify_content(conn, name, manifest):
    meta = metadata(conn)
    expected = manifest["accounts"][name]
    if any(meta[key] != expected[key] for key in ("binding", "migrations")):
        raise ValueError("restored account metadata differs from archive")
    # Failed INSERTs can consume sequence values even while the restore guard
    # correctly rejects all rows. Such gaps must not prevent verification.
    if meta["sequence"][0] < expected["sequence"][0] or (
        expected["sequence"][1] and not meta["sequence"][1]
    ):
        raise ValueError("restored record sequence moved backwards")
    first = conn.execute(
        "SELECT source_history FROM fx.restore_history "
        "WHERE archive_id=%s AND status='STAGED' ORDER BY sequence LIMIT 1",
        (manifest["archive_id"],),
    ).fetchone()
    if not first or first[0] != expected["source_history"]:
        raise ValueError("restore provenance differs from archive")
    for table in TABLES:
        if (
            sha256(data_bytes(conn, table)).hexdigest()
            != manifest["files"][f"{name}/{table}.jsonl"]["sha256"]
        ):
            raise ValueError("restored account contents differ from archive")


def restore_archive(settings: Settings, source: Path, *, paper_account=None) -> dict:
    manifest, data = read_archive(source, paper_account=paper_account)
    digest = sha256(encode(manifest)).hexdigest()
    with fenced(settings) as conns:
        # Validate both destinations before staging either. No DROP, TRUNCATE,
        # UPDATE, trigger disabling, schema SQL, or password import is supported.
        for name, conn in conns.items():
            meta = metadata(conn)
            expected = manifest["accounts"][name]
            if any(meta[key] != expected[key] for key in ("binding", "migrations")):
                raise ValueError(
                    "destination binding/schema differs; use the same application version"
                )
            last = marker(conn)
            if last:
                if (
                    str(last[0]) != manifest["archive_id"]
                    or last[1] != digest
                    or last[2] == "RELEASED"
                ):
                    raise ValueError("destination belongs to another or already released restore")
            elif any(
                conn.execute(f"SELECT EXISTS(SELECT 1 FROM fx.{table})").fetchone()[0]
                for table in TABLES
            ):
                raise ValueError(
                    "restore requires empty destination accounts; existing history is preserved"
                )
        # Each stage is durable before any data import. A crash can leave a partial
        # pair, but neither imported account becomes executable.
        for conn in conns.values():
            if not marker(conn):
                with conn.transaction():
                    conn.execute("LOCK TABLE fx.records, fx.offline_journal IN EXCLUSIVE MODE")
                    if any(
                        conn.execute(f"SELECT EXISTS(SELECT 1 FROM fx.{t})").fetchone()[0]
                        for t in TABLES
                    ):
                        raise ValueError("destination changed before restore staging")
                    name = next(n for n, c in conns.items() if c is conn)
                    append_marker(
                        conn, manifest, "STAGED", manifest["accounts"][name]["source_history"]
                    )
        for name, conn in conns.items():
            if marker(conn)[2] == "RESTORED":
                verify_content(conn, name, manifest)
                continue
            with conn.transaction():
                conn.execute(
                    sql.SQL("SET LOCAL ROLE {}").format(
                        sql.Identifier(f"{settings.namespace}_{name.lower()}_owner")
                    )
                )
                for row in data[f"{name}/records.jsonl"]:
                    conn.execute(
                        "INSERT INTO fx.records"
                        "(sequence,record_id,kind,recorded_at,supersedes,payload) "
                        "OVERRIDING SYSTEM VALUE VALUES (%s,%s,%s,%s,%s,%s)",
                        (
                            row["sequence"],
                            row["record_id"],
                            row["kind"],
                            row["recorded_at"],
                            row["supersedes"],
                            Jsonb(row["payload"]),
                        ),
                    )
                for row in data[f"{name}/offline_journal.jsonl"]:
                    conn.execute(
                        "INSERT INTO fx.offline_journal VALUES (%s,%s,%s,%s,%s,%s)",
                        (
                            row["run_id"],
                            row["stream"],
                            row["revision"],
                            row["recorded_at"],
                            row["event"],
                            Jsonb(row["payload"]),
                        ),
                    )
                conn.execute(
                    "SELECT setval('fx.records_sequence_seq',%s,%s)",
                    manifest["accounts"][name]["sequence"],
                )
                verify_content(conn, name, manifest)
                append_marker(conn, manifest, "RESTORED")
    return {
        "archive_id": manifest["archive_id"],
        "status": "RESTORED",
        "execution_blocked": True,
        "accounts": ["PAPER", "LIVE"],
    }


def release_restore(
    settings: Settings, source: Path, *, source_retired: bool = False, paper_account=None
) -> dict:
    if not source_retired:
        raise ValueError("source writer retirement must be explicitly acknowledged")
    manifest, _ = read_archive(source, paper_account=paper_account)
    digest = sha256(encode(manifest)).hexdigest()
    with fenced(settings) as conns:
        for name, conn in conns.items():
            last = marker(conn)
            if (
                not last
                or str(last[0]) != manifest["archive_id"]
                or last[1] != digest
                or last[2] not in {"RESTORED", "RELEASED"}
            ):
                raise ValueError("both accounts must have completed this exact restore")
            # A previous release may have committed for one account before a
            # connection failure on the other. Its append-only RELEASED marker
            # proves verification already succeeded; subsequent legitimate history
            # must not prevent releasing the still-blocked account on retry.
            if last[2] != "RELEASED":
                verify_content(conn, name, manifest)
        for conn in conns.values():
            if marker(conn)[2] != "RELEASED":
                append_marker(conn, manifest, "RELEASED")
    # Gateway construction still forces STARTUP_RECONCILE, and loss limits,
    # unresolved requests and protection checks remain authoritative.
    return {
        "archive_id": manifest["archive_id"],
        "status": "STARTUP_RECONCILE_REQUIRED",
        "live_enabled": False,
    }
