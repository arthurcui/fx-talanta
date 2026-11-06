"""Single-owner inspection sessions. No broker authority or copied session secrets."""

import argparse
import getpass
import hashlib
import hmac
import secrets
import threading
import time
from datetime import timedelta
from http.cookies import SimpleCookie
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field

from fx_talanta.domain.models import FrozenModel


def verifier(password, salt):
    return hashlib.scrypt(
        password.encode(),
        salt=bytes.fromhex(salt),
        n=32768,
        r=8,
        p=1,
        maxmem=64 * 1024 * 1024,
        dklen=32,
    ).hex()


class Owner(FrozenModel):
    version: Literal["dashboard-owner/1"] = "dashboard-owner/1"
    username: Annotated[str, Field(pattern=r"^[a-zA-Z0-9_.-]{1,64}$")]
    salt: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    password_hash: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]

    @classmethod
    def create(cls, username, password):
        if not isinstance(password, str) or not 16 <= len(password) <= 256:
            raise ValueError("owner passphrase must contain 16..256 characters")
        salt = secrets.token_hex(32)
        return cls(username=username, salt=salt, password_hash=verifier(password, salt))


class Sessions:
    def __init__(self, app, owner=None, monotonic=time.monotonic):
        self.app, self.owner, self.monotonic = app, owner, monotonic
        self.lock = threading.RLock()
        self.rows = {}
        self.attempts = []

    def login(self, data, *, peer, secure):
        with self.lock:
            now = self.app.clock.now()
            self.app.authorize(self.app.token)
            tick = self.monotonic()
            self.attempts = [t for t in self.attempts if tick - t < 60]
            if len(self.attempts) >= 5:
                raise PermissionError("sign-in temporarily unavailable")
            valid = False
            if self.owner:
                if not secure:
                    raise PermissionError("HTTPS required")
                if (
                    set(data) == {"username", "password"}
                    and isinstance(data["password"], str)
                    and isinstance(data["username"], str)
                    and len(data["password"]) <= 256
                ):
                    derived = verifier(data["password"], self.owner.salt)
                    valid = hmac.compare_digest(
                        derived, self.owner.password_hash
                    ) and hmac.compare_digest(
                        data["username"].encode(), self.owner.username.encode()
                    )
            elif set(data) == {"bootstrap"} and isinstance(data["bootstrap"], str):
                valid = hmac.compare_digest(data["bootstrap"].encode(), self.app.token.encode())
            if not valid:
                self.attempts.append(tick)
                raise PermissionError("sign-in denied")
            self.rows = {
                k: v
                for k, v in self.rows.items()
                if now < v["expires"] and now - v["last"] < timedelta(minutes=30)
            }
            if len(self.rows) >= 16:
                raise PermissionError("session capacity reached")
            token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
            digest = hashlib.sha256(token.encode()).hexdigest()
            self.rows[digest] = dict(csrf=csrf, peer=peer, last=now, expires=self.app.expires_at)
            return token, dict(
                authenticated=True,
                csrf=csrf,
                expires_at=self.app.expires_at.isoformat(),
                mode="OWNER" if self.owner else "LOCAL_LAUNCH",
                execution_enabled=False,
            )

    def verify(self, token, *, peer, csrf=None, mutation=False):
        if not isinstance(token, str) or len(token) > 128:
            raise PermissionError("session denied")
        digest = hashlib.sha256(token.encode()).hexdigest()
        with self.lock:
            self.app.authorize(self.app.token)
            now = self.app.clock.now()
            row = self.rows.get(digest)
            if (
                not row
                or peer != row["peer"]
                or not row["last"] <= now < row["expires"]
                or now - row["last"] >= timedelta(minutes=30)
            ):
                self.rows.pop(digest, None)
                raise PermissionError("session denied")
            if mutation and (
                not isinstance(csrf, str)
                or not csrf.isascii()
                or not hmac.compare_digest(csrf, row["csrf"])
            ):
                raise PermissionError("session denied")
            row["last"] = now
            return dict(
                authenticated=True,
                csrf=row["csrf"],
                expires_at=row["expires"].isoformat(),
                mode="OWNER" if self.owner else "LOCAL_LAUNCH",
                execution_enabled=False,
            )

    def logout(self, token):
        with self.lock:
            self.rows.pop(hashlib.sha256(token.encode()).hexdigest(), None)


def cookie_token(header, name):
    if len(header) > 8192 or header.count(name + "=") != 1:
        return ""
    try:
        cookie = SimpleCookie()
        cookie.load(header)
        return cookie[name].value if name in cookie else ""
    except Exception:
        return ""


def cookie_header(name, token, secure, *, clear=False):
    return f"{name}={token}; Path=/; HttpOnly; SameSite=Strict; Max-Age={0 if clear else 28800}" + (
        "; Secure" if secure else ""
    )


def main():
    parser = argparse.ArgumentParser(
        description="Create a new private single-owner credential file."
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--username", default="owner")
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("owner file already exists")
    password = getpass.getpass("Owner passphrase (16+ characters): ")
    if password != getpass.getpass("Repeat passphrase: "):
        raise ValueError("passphrases differ")
    record = Owner.create(args.username, password)
    with args.output.open("x", encoding="utf-8") as stream:
        stream.write(record.model_dump_json(indent=2))
    args.output.chmod(0o600)
    print("Owner credential created. Keep this file private; restart the dashboard to load it.")


if __name__ == "__main__":
    main()
