"""Explicit local-only database settings. Never print connection strings."""

import os
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

    @classmethod
    def load(cls, path: Path = Path(".env")) -> "Settings":
        values = {**dotenv_values(path), **os.environ}
        required = ("FX_DB_ADMIN_PASSWORD", "FX_PAPER_PASSWORD", "FX_LIVE_PASSWORD")
        if any(not values.get(k) for k in required):
            raise ValueError("missing local database settings; run fx-talanta init-local")
        return cls(
            host=values.get("FX_DB_HOST", "127.0.0.1"),
            port=int(values.get("FX_DB_PORT", "55432")),
            admin_user=values.get("FX_DB_ADMIN_USER", "postgres"),
            admin_password=values[required[0]],
            paper_password=values[required[1]],
            live_password=values[required[2]],
        )

    def admin_dsn(self, database: str = "postgres") -> str:
        return make_conninfo(
            host=self.host,
            port=self.port,
            dbname=database,
            user=self.admin_user,
            password=self.admin_password,
            connect_timeout=5,
        )

    def runtime_dsn(self, environment: Environment) -> str:
        name = environment.value.lower()
        return make_conninfo(
            host=self.host,
            port=self.port,
            dbname=f"fx_{name}",
            user=f"fx_{name}_writer",
            password=self.paper_password
            if environment == Environment.PAPER
            else self.live_password,
            connect_timeout=5,
        )


def init_local(path: Path = Path(".env")) -> None:
    # Exclusive creation preserves existing credentials and database volumes.
    content = "FX_DB_HOST=127.0.0.1\nFX_DB_PORT=55432\nFX_DB_ADMIN_USER=postgres\n"
    for name in ("FX_DB_ADMIN_PASSWORD", "FX_PAPER_PASSWORD", "FX_LIVE_PASSWORD"):
        content += f"{name}={secrets.token_urlsafe(32)}\n"
    with path.open("x", encoding="utf-8") as stream:
        stream.write(content)
    if os.name != "nt":
        path.chmod(0o600)
