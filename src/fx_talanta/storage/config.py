"""Explicit local-only database settings. Never print connection strings."""

import os
import re
import secrets
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import dotenv_values
from psycopg.conninfo import make_conninfo

from fx_talanta.domain.models import AccountIdentity, Environment


def fixture_account(environment: Environment) -> AccountIdentity:
    return AccountIdentity(
        environment=environment,
        broker="fixture",
        server="offline",
        login="paper-fixture" if environment == Environment.PAPER else "live-disabled",
        venue="SIMULATOR" if environment == Environment.PAPER else "BROKER_LIVE",
    )


@dataclass(frozen=True)
class Settings:
    host: str
    port: int
    admin_user: str
    admin_password: str = field(repr=False)
    paper_password: str = field(repr=False)
    live_password: str = field(repr=False)
    namespace: str = "fx"
    profile: str = "native"

    def __post_init__(self):
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,30}", self.namespace):
            raise ValueError("database namespace must be a short lowercase SQL identifier")
        if self.profile not in {"native", "docker", "codex"}:
            raise ValueError("unknown execution profile")

    def database(self, environment: Environment) -> str:
        return f"{self.namespace}_{environment.value.lower()}"

    @classmethod
    def load(cls, path: Path = Path(".env"), *, runtime: Environment | None = None) -> "Settings":
        values = {**dotenv_values(path), **os.environ}
        required = (
            (f"FX_{runtime.value}_PASSWORD",)
            if runtime
            else ("FX_DB_ADMIN_PASSWORD", "FX_PAPER_PASSWORD", "FX_LIVE_PASSWORD")
        )
        if any(not values.get(k) for k in required):
            raise ValueError("missing local database settings; run fx-talanta init-local")
        return cls(
            host=values.get("FX_DB_HOST", "127.0.0.1"),
            port=int(values.get("FX_DB_PORT", "55432")),
            admin_user=values.get("FX_DB_ADMIN_USER", "postgres"),
            admin_password=values.get("FX_DB_ADMIN_PASSWORD", ""),
            paper_password=values.get("FX_PAPER_PASSWORD", ""),
            live_password=values.get("FX_LIVE_PASSWORD", ""),
            namespace=values.get("FX_DB_NAMESPACE", "fx"),
            profile=values.get("FX_PROFILE", "native"),
        )

    def admin_dsn(self, database: str = "postgres") -> str:
        if not self.admin_password:
            raise ValueError("administrative database credentials are not available")
        return make_conninfo(
            host=self.host,
            port=self.port,
            dbname=database,
            user=self.admin_user,
            password=self.admin_password,
            connect_timeout=5,
        )

    def runtime_dsn(self, environment: Environment) -> str:
        name = self.database(environment)
        password = self.paper_password if environment == Environment.PAPER else self.live_password
        if not password:
            raise ValueError(f"{environment.value} runtime credentials are not available")
        return make_conninfo(
            host=self.host,
            port=self.port,
            dbname=name,
            user=f"{name}_writer",
            password=password,
            connect_timeout=5,
        )


def init_local(path: Path = Path(".env")) -> None:
    # Exclusive creation preserves existing credentials and database volumes.
    content = "FX_DB_HOST=127.0.0.1\nFX_DB_PORT=55432\nFX_DB_ADMIN_USER=postgres\n"
    for name in ("FX_DB_ADMIN_PASSWORD", "FX_PAPER_PASSWORD", "FX_LIVE_PASSWORD"):
        content += f"{name}={secrets.token_urlsafe(32)}\n"
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        stream.write(content)
