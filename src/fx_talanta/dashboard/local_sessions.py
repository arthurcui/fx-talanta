"""Persistent single-owner authentication for explicitly loopback-only workspaces."""

import hashlib
import hmac
import re
import secrets
import sqlite3
import threading
from contextlib import closing
from datetime import datetime, timedelta

from fx_talanta.dashboard.sessions import Owner, verifier

LIFETIME = timedelta(days=30)
IDLE = timedelta(days=7)


class SetupValidationError(ValueError):
    """Public, non-secret first-owner validation message."""


class LocalSessions:
    def __init__(self, app):
        self.app = app
        self.path = app.state / "local-auth.sqlite"
        if self.path.is_symlink():
            raise ValueError("authentication store cannot be a symlink")
        self.lock = threading.RLock()
        with closing(sqlite3.connect(self.path)) as conn, conn:
            self.path.chmod(0o600)
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS owner (id INTEGER PRIMARY KEY CHECK(id=1), data TEXT);
                CREATE TABLE IF NOT EXISTS sessions
                (hash TEXT PRIMARY KEY, csrf TEXT, peer TEXT, last TEXT, expires TEXT);
                CREATE TABLE IF NOT EXISTS failures (at TEXT);
            """)

    def mode(self):
        with self.lock, closing(sqlite3.connect(self.path)) as conn:
            return (
                "LOCAL_OWNER" if conn.execute("SELECT 1 FROM owner").fetchone() else "LOCAL_SETUP"
            )

    def login(self, data, *, peer, secure):
        with self.lock, closing(sqlite3.connect(self.path)) as conn:
            now = self.app.clock.now()
            with conn:
                conn.execute(
                    "DELETE FROM failures WHERE at < ?", ((now - timedelta(minutes=1)).isoformat(),)
                )
            if conn.execute("SELECT count(*) FROM failures").fetchone()[0] >= 5:
                raise PermissionError("sign-in temporarily unavailable")
            record = conn.execute("SELECT data FROM owner WHERE id=1").fetchone()
            valid = set(data) == {"username", "password"} and all(
                isinstance(v, str) for v in data.values()
            )
            if valid and not record:
                if not re.fullmatch(r"[a-zA-Z0-9_.@+-]{1,128}", data["username"]):
                    raise SetupValidationError(
                        "Use 1–128 letters, numbers, or . _ @ + - for your username; no spaces."
                    )
                if not 16 <= len(data["password"]) <= 256:
                    raise SetupValidationError("Choose a passphrase of 16–256 characters.")
                owner = Owner.create(data["username"], data["password"])
                with conn:
                    conn.execute("INSERT INTO owner VALUES (1,?)", (owner.model_dump_json(),))
            elif valid and record and len(data["password"]) <= 256:
                owner = Owner.model_validate_json(record[0])
                valid = hmac.compare_digest(
                    verifier(data["password"], owner.salt), owner.password_hash
                )
                valid = (
                    hmac.compare_digest(data["username"].encode(), owner.username.encode())
                    and valid
                )
            else:
                valid = False
            if not valid:
                with conn:
                    conn.execute("INSERT INTO failures VALUES (?)", (now.isoformat(),))
                raise PermissionError("sign-in denied")
            with conn:
                conn.execute(
                    "DELETE FROM sessions WHERE expires <= ? OR last <= ?",
                    (now.isoformat(), (now - IDLE).isoformat()),
                )
                if conn.execute("SELECT count(*) FROM sessions").fetchone()[0] >= 16:
                    raise PermissionError("session capacity reached; sign out another session")
                token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
                expires = now + LIFETIME
                conn.execute(
                    "INSERT INTO sessions VALUES (?,?,?,?,?)",
                    (
                        hashlib.sha256(token.encode()).hexdigest(),
                        csrf,
                        peer,
                        now.isoformat(),
                        expires.isoformat(),
                    ),
                )
            self.app.renew_owner_access()
            return token, self.result(csrf, expires)

    @staticmethod
    def result(csrf, expires):
        return dict(
            authenticated=True,
            csrf=csrf,
            expires_at=expires.isoformat(),
            mode="LOCAL_OWNER",
            execution_enabled=False,
        )

    def verify(self, token, *, peer, csrf=None, mutation=False):
        if not isinstance(token, str) or not 1 <= len(token) <= 128:
            raise PermissionError("session denied")
        key = hashlib.sha256(token.encode()).hexdigest()
        with self.lock, closing(sqlite3.connect(self.path)) as conn:
            row = conn.execute(
                "SELECT csrf,peer,last,expires FROM sessions WHERE hash=?", (key,)
            ).fetchone()
            now = self.app.clock.now()
            if (
                not row
                or peer != row[1]
                or not datetime.fromisoformat(row[2]) <= now < datetime.fromisoformat(row[3])
                or now - datetime.fromisoformat(row[2]) >= IDLE
            ):
                with conn:
                    conn.execute("DELETE FROM sessions WHERE hash=?", (key,))
                raise PermissionError("session denied")
            if mutation and (
                not isinstance(csrf, str)
                or not csrf.isascii()
                or not hmac.compare_digest(csrf, row[0])
            ):
                raise PermissionError("session denied")
            with conn:
                conn.execute("UPDATE sessions SET last=? WHERE hash=?", (now.isoformat(), key))
            self.app.renew_owner_access()
            return self.result(row[0], datetime.fromisoformat(row[3]))

    def logout(self, token):
        with self.lock, closing(sqlite3.connect(self.path)) as conn, conn:
            conn.execute(
                "DELETE FROM sessions WHERE hash=?", (hashlib.sha256(token.encode()).hexdigest(),)
            )

    def logout_all(self):
        with self.lock, closing(sqlite3.connect(self.path)) as conn, conn:
            conn.execute("DELETE FROM sessions")
