"""Append-only shadow journals, separate from execution/reservation state."""

import json
import sqlite3
from contextlib import contextmanager

import psycopg

from fx_talanta.shadow.wire import digest
from fx_talanta.shadow.work import scope_for


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


class Events:
    def __init__(self, rows, insert):
        self.records = []
        self.tip = "0" * 64
        self.insert = insert
        for seq, body, prior, hashed in rows:
            if (
                seq != len(self.records) + 1
                or prior != self.tip
                or digest(f"{seq}\n{prior}\n{body}") != hashed
            ):
                raise ValueError("JOURNAL_INTEGRITY")
            self.records.append(json.loads(body))
            self.tip = hashed

    def append(self, value):
        if len(self.records) >= 10000:
            raise ValueError("JOURNAL_CAPACITY")
        seq, body = len(self.records) + 1, canonical(value)
        hashed = digest(f"{seq}\n{self.tip}\n{body}")
        self.insert(seq, body, self.tip, hashed)
        self.records.append(value)
        self.tip = hashed


class SQLiteStore:
    """Local tests/EA reference only; never silently create a lost journal."""

    def __init__(self, path, *, bootstrap=False):
        if bootstrap and path.exists():
            raise ValueError("JOURNAL_ALREADY_EXISTS")
        if not path.exists() and not bootstrap:
            raise ValueError("MISSING_JOURNAL")
        self.path = path
        if bootstrap:
            with sqlite3.connect(path) as db:
                db.execute(
                    "CREATE TABLE events (seq INTEGER PRIMARY KEY, body TEXT NOT NULL, "
                    "prior TEXT NOT NULL, hash TEXT NOT NULL)"
                )
                for action in ("UPDATE", "DELETE"):
                    db.execute(
                        f"CREATE TRIGGER immutable_{action} BEFORE {action} ON events "
                        "BEGIN SELECT RAISE(ABORT,'immutable'); END"
                    )

    @contextmanager
    def transaction(self):
        if not self.path.exists():
            raise ValueError("MISSING_JOURNAL")
        db = sqlite3.connect(f"file:{self.path.as_posix()}?mode=rw", uri=True, timeout=2)
        try:
            db.execute("PRAGMA synchronous=FULL")
            db.execute("BEGIN IMMEDIATE")
            events = Events(
                db.execute("SELECT * FROM events ORDER BY seq"),
                lambda *r: db.execute("INSERT INTO events VALUES (?,?,?,?)", r),
            )
            yield events
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()


class PostgresStore:
    """One disabled PAPER database; explicit experiment stream, bounded transactions."""

    def __init__(self, dsn, account, stream):
        if account.environment.value != "PAPER":
            raise ValueError("PAPER_REQUIRED")
        self.dsn, self.account, self.stream = dsn, account, stream

    @contextmanager
    def transaction(self):
        with psycopg.connect(self.dsn, connect_timeout=2) as db:
            db.execute("SET LOCAL statement_timeout='2000ms'")
            db.execute("SET LOCAL lock_timeout='1000ms'")
            row = db.execute("SELECT identity,execution_enabled FROM fx.account_binding").fetchone()
            if row != (self.account.model_dump(mode="json"), False):
                raise ValueError("ACCOUNT_BINDING_MISMATCH")
            db.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (str(self.stream),))
            rows = db.execute(
                "SELECT seq,body,prior,hash FROM fx.shadow_events WHERE stream=%s ORDER BY seq",
                (self.stream,),
            ).fetchall()

            def insert(seq, body, prior, hashed):
                db.execute(
                    "INSERT INTO fx.shadow_events VALUES (%s,%s,%s,%s,%s,%s)",
                    (self.stream, seq, scope_for(self.account), body, prior, hashed),
                )

            yield Events(rows, insert)
