"""Local safety journal and fenced, authenticated offline delivery reference.

SQLite is a local acceptance store, not a replacement for production PostgreSQL.
One account scope per file. Authentication does not replace verified HTTPS.
"""

import hashlib
import hmac
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path


def canonical(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def seal(key: bytes, scope: str, epoch: int, sequence: int, expires_ms: int, payload: str) -> str:
    if len(key) < 32:
        raise ValueError("authentication key too short")
    digest = hashlib.sha256(payload.encode()).hexdigest()
    text = f"ea-safety/1\n{scope}\n{epoch}\n{sequence}\n{expires_ms}\n{digest}"
    return hmac.new(key, text.encode(), hashlib.sha256).hexdigest()


class SafetyJournal:
    def __init__(self, path: Path, scope: str, *, key: bytes, bootstrap: bool = False):
        if len(scope) != 64 or any(c not in "0123456789abcdef" for c in scope):
            raise ValueError("scope must be the full account identity digest")
        if not path.exists() and not bootstrap:
            raise ValueError("missing safety journal; restore/reconcile, never reset")
        if len(key) < 32:
            raise ValueError("authentication key too short")
        self.key = key
        self.db = sqlite3.connect(path, isolation_level=None, timeout=2)
        self.db.execute("PRAGMA synchronous=FULL")
        if bootstrap:
            self.db.executescript("""
                CREATE TABLE IF NOT EXISTS control (
                    id INTEGER PRIMARY KEY CHECK(id=1), scope TEXT NOT NULL,
                    epoch INTEGER NOT NULL, owner TEXT NOT NULL, expires INTEGER NOT NULL,
                    last_utc INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS events (
                    seq INTEGER PRIMARY KEY, id TEXT UNIQUE NOT NULL,
                    body TEXT NOT NULL, previous TEXT NOT NULL, hash TEXT NOT NULL);
            """)
            self.db.execute("INSERT OR IGNORE INTO control VALUES (1,?,0,'',0,0)", (scope,))
        row = self.db.execute("SELECT scope FROM control WHERE id=1").fetchone()
        if row != (scope,):
            self.db.close()
            raise ValueError("journal account mismatch")
        self.scope = scope
        self.verify()

    @contextmanager
    def transaction(self):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    def verify(self) -> list[dict]:
        previous = "0" * 64
        records = []
        for seq, event_id, body, prior, digest in self.db.execute(
            "SELECT * FROM events ORDER BY seq"
        ):
            expected = hashlib.sha256(f"{seq}\n{event_id}\n{body}\n{prior}".encode()).hexdigest()
            if seq != len(records) + 1 or prior != previous or digest != expected:
                raise ValueError("safety journal integrity failure")
            records.append(json.loads(body))
            previous = digest
        return records

    def acquire(
        self,
        owner: str,
        now_ms: int,
        ttl_ms: int,
        *,
        reconciled: bool,
        clock_error_ms: int,
        peer_checkpoint: tuple[int, str],
    ) -> int:
        if (
            not owner
            or not reconciled
            or not 0 <= clock_error_ms <= 100
            or not 100 < ttl_ms <= 5000
        ):
            raise ValueError("unverified lease request")
        with self.transaction():
            self.verify()
            if self.checkpoint() != peer_checkpoint:
                raise ValueError("replica checkpoint mismatch; restore/reconcile")
            epoch, expiry, last = self.db.execute(
                "SELECT epoch,expires,last_utc FROM control WHERE id=1"
            ).fetchone()
            if now_ms - clock_error_ms < max(expiry, last):
                raise ValueError("active writer or clock regression")
            self.db.execute(
                "UPDATE control SET epoch=?,owner=?,expires=?,last_utc=? WHERE id=1",
                (epoch + 1, owner, now_ms + ttl_ms, now_ms),
            )
            return epoch + 1

    def checkpoint(self) -> tuple[int, str]:
        """Peer supplies its independently retained event tip before writer acquisition."""
        self.verify()
        tail = self.db.execute("SELECT seq,hash FROM events ORDER BY seq DESC LIMIT 1").fetchone()
        return tail if tail else (0, "0" * 64)

    def append(
        self,
        event_id: str,
        value: dict,
        *,
        owner: str,
        epoch: int,
        sequence: int,
        now_ms: int,
        clock_error_ms: int,
        expires_ms: int,
        signature: str,
    ) -> bool:
        body = canonical(value)
        if len(body.encode()) > 65536 or not event_id or len(event_id) > 160 or "\n" in event_id:
            raise ValueError("invalid bounded event")
        # Bind event identity as well as content to prevent replay under a fresh ID.
        authenticated = canonical({"id": event_id, "body": value})
        expected = seal(self.key, self.scope, epoch, sequence, expires_ms, authenticated)
        if not hmac.compare_digest(expected, signature):
            raise ValueError("authentication failure")
        with self.transaction():
            self.verify()
            actual_epoch, actual_owner, expiry, last = self.db.execute(
                "SELECT epoch,owner,expires,last_utc FROM control WHERE id=1"
            ).fetchone()
            if (
                epoch != actual_epoch
                or owner != actual_owner
                or not 0 <= clock_error_ms <= 100
                or now_ms - clock_error_ms < last
                or now_ms + clock_error_ms >= min(expiry, expires_ms)
            ):
                raise ValueError("fenced/expired/unverified writer")
            old = self.db.execute("SELECT seq,body FROM events WHERE id=?", (event_id,)).fetchone()
            if old:
                if old != (sequence, body):
                    raise ValueError("event identity/hash conflict")
                return False
            tail = self.db.execute(
                "SELECT seq,hash FROM events ORDER BY seq DESC LIMIT 1"
            ).fetchone()
            last_sequence, previous = tail if tail else (0, "0" * 64)
            if sequence != last_sequence + 1:
                raise ValueError("event sequence gap/replay")
            digest = hashlib.sha256(
                f"{sequence}\n{event_id}\n{body}\n{previous}".encode()
            ).hexdigest()
            self.db.execute(
                "INSERT INTO events VALUES (?,?,?,?,?)",
                (sequence, event_id, body, previous, digest),
            )
            self.db.execute("UPDATE control SET last_utc=? WHERE id=1", (now_ms,))
            return True

    def close(self):
        self.db.close()
