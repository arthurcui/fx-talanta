"""Bounded telemetry-file inspection and durable state transitions, never a collector."""

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, model_validator

from fx_talanta.dashboard.models import Channel
from fx_talanta.domain.models import AccountIdentity, FrozenModel, Timestamp


class Telemetry(FrozenModel):
    version: Literal["dashboard-telemetry/1"] = "dashboard-telemetry/1"
    account: AccountIdentity
    run_id: UUID
    sequence: Annotated[int, Field(strict=True, ge=1)]
    generated_at: Timestamp
    provenance: Literal["SIMULATED", "RECORDED"]
    channels: Annotated[tuple[Channel, ...], Field(min_length=1, max_length=3)]
    execution_enabled: Literal[False] = False

    @model_validator(mode="after")
    def timing(self):
        if self.account.venue != "SIMULATOR":
            raise ValueError("telemetry is an offline inspection input")
        if len({c.name for c in self.channels}) != len(self.channels):
            raise ValueError("duplicate channel")
        for c in self.channels:
            if any(t and t > self.generated_at for t in (c.observed_at, c.quote_at, c.received_at)):
                raise ValueError("timestamp later than publication")
            if c.quote_at and c.received_at and c.received_at < c.quote_at:
                raise ValueError("negative latency")
        return self


class Monitor:
    def __init__(self, repository, path=None, run_id=None):
        self.repo = repository
        self.path = Path(path).resolve() if path else None
        self.run_id = run_id
        if (self.path is None) != (run_id is None):
            raise ValueError("telemetry path and exact run ID are both required")
        conn = self.repo.conn
        conn.execute("CREATE TABLE IF NOT EXISTS monitor_binding (identity TEXT NOT NULL)")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS monitor_clock (singleton INTEGER "
            "PRIMARY KEY CHECK(singleton=1), "
            "at TEXT NOT NULL)"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS telemetry (seq INTEGER PRIMARY KEY, digest TEXT NOT NULL, "
            "payload TEXT NOT NULL)"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS incidents (seq INTEGER PRIMARY KEY, kind TEXT, state TEXT, "
            "at TEXT, evidence TEXT)"
        )
        identity = json.dumps(
            dict(
                path=str(self.path) if self.path else None, run_id=str(run_id) if run_id else None
            ),
            sort_keys=True,
        )
        old = conn.execute("SELECT identity FROM monitor_binding").fetchone()
        if old and old[0] != identity:
            raise ValueError("monitor source cannot be rebound on resume")
        if not old:
            conn.execute("INSERT INTO monitor_binding VALUES (?)", (identity,))
        conn.commit()

    def read(self, now):
        with self.repo.lock, self.repo.conn:
            highwater = self.repo.conn.execute(
                "SELECT at FROM monitor_clock WHERE singleton=1"
            ).fetchone()
            if highwater and now < datetime.fromisoformat(highwater[0]):
                raise ValueError("inspection clock rollback; monitoring unavailable")
            self.repo.conn.execute(
                "INSERT INTO monitor_clock VALUES (1,?) ON CONFLICT(singleton) "
                "DO UPDATE SET at=excluded.at",
                (now.isoformat(),),
            )
            latest = self.repo.conn.execute(
                "SELECT seq,digest,payload FROM telemetry ORDER BY seq DESC LIMIT 1"
            ).fetchone()
            previous = Telemetry.model_validate_json(latest[2]) if latest else None
            if self.path is None:
                return dict(status="NOT_CONFIGURED", sequence=None, sha256=None), None
            try:
                with self.path.open("rb") as f:
                    raw = f.read(65537)
                if len(raw) > 65536:
                    raise ValueError("telemetry size limit")
                value = Telemetry.model_validate_json(raw)
                digest = hashlib.sha256(raw).hexdigest()
                if value.account != self.repo.account or value.run_id != self.run_id:
                    raise ValueError("telemetry binding mismatch")
                if value.generated_at > now:
                    raise ValueError("future publication")
                if latest:
                    if value.sequence < latest[0] or (
                        value.sequence == latest[0] and digest != latest[1]
                    ):
                        raise ValueError("rollback or conflicting revision")
                    if value.generated_at < previous.generated_at:
                        raise ValueError("publication clock regressed")
                    old_channels = {c.name: c for c in previous.channels}
                    for c in value.channels:
                        old = old_channels.get(c.name)
                        if old and any(
                            a and b and a < b
                            for a, b in (
                                (c.observed_at, old.observed_at),
                                (c.quote_at, old.quote_at),
                                (c.received_at, old.received_at),
                            )
                        ):
                            raise ValueError("channel timestamp regressed")
                if not latest or value.sequence > latest[0]:
                    self.repo.conn.execute(
                        "INSERT INTO telemetry VALUES (?,?,?)",
                        (value.sequence, digest, raw.decode()),
                    )
                age = (now - value.generated_at).total_seconds()
                return dict(
                    status="RECENT" if age <= 15 else "STALE",
                    sequence=value.sequence,
                    sha256=digest,
                    published_at=value.generated_at.isoformat(),
                    provenance=value.provenance,
                ), value.channels
            except FileNotFoundError:
                status = "MISSING"
            except (ValueError, OSError):
                status = "INVALID"
            return dict(
                status=status,
                sequence=latest[0] if latest else None,
                sha256=latest[1] if latest else None,
                retained_previous=bool(latest),
            ), (previous.channels if previous else ())

    def transitions(self, states, now, evidence):
        """Record sampled state changes only; never infer uninterrupted coverage."""
        with self.repo.lock, self.repo.conn:
            for kind, state in states.items():
                old = self.repo.conn.execute(
                    "SELECT state,at FROM incidents WHERE kind=? ORDER BY seq DESC LIMIT 1", (kind,)
                ).fetchone()
                if old and now < datetime.fromisoformat(old[1]):
                    raise ValueError("inspection clock rollback")
                if old is None or old[0] != state:
                    self.repo.conn.execute(
                        "INSERT INTO incidents(kind,state,at,evidence) VALUES (?,?,?,?)",
                        (kind, state, now.isoformat(), evidence.get(kind, evidence["default"])),
                    )
            rows = self.repo.conn.execute(
                "SELECT seq,kind,state,at,evidence FROM incidents ORDER BY seq DESC LIMIT 100"
            ).fetchall()
            count = self.repo.conn.execute("SELECT count(*) FROM incidents").fetchone()[0]
            return dict(
                total=count,
                shown=len(rows),
                events=[
                    dict(zip(("id", "kind", "state", "at", "evidence"), r, strict=True))
                    for r in rows
                ],
            )
