"""Offline descriptive strategy records; no model, evaluator or execution authority."""

import hashlib
import json
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, model_validator

from fx_talanta.domain.models import Amount, FrozenModel, Hash

Description = Annotated[str, Field(min_length=10, max_length=4000)]
Percentage = Annotated[Amount, Field(gt=0, le=100)]

MILESTONES = (
    ("R0", "Foundation overview", "IN_PROGRESS"),
    ("R1", "AI Strategy V1", "DESCRIPTIVE_WORKSPACE_STARTED"),
    ("R2", "Historical validation", "EXISTING_ENGINE_NOT_BOUND_TO_CANDIDATES"),
    ("R3", "Paper readiness", "BLOCKED_BY_QUALIFICATION"),
    ("R4", "Prospective demo", "NOT_AUTHORIZED"),
    ("R5", "Capped live", "NOT_AUTHORIZED"),
    ("R6", "AI improvement", "NOT_IMPLEMENTED"),
)
GAPS = (
    "R1: AI generation and reviewed executable rule mapping are not connected here.",
    "R2: Candidate-bound datasets, preregistration, replay and verdict UI remain unfinished.",
    "R3: M1 broker/calendar/news qualification and M2 connected fault matrix remain open.",
    "R2/R3: M3 historical cost/availability gaps remain; B01 is REJECT_FOR_PROMOTION.",
    "R4/R5: No campaign or trading authority; unattended acceptance remains unqualified.",
)


class Specification(FrozenModel):
    name: Annotated[str, Field(min_length=3, max_length=100)]
    pairs: tuple[Literal["EURUSD", "USDJPY"], ...] = ("EURUSD", "USDJPY")
    hypothesis: Description
    input_policy: Description
    entry_rules: Description
    exit_rules: Description
    portfolio_policy: Description
    evaluation_plan: Description
    risk_per_trade_pct: Percentage
    total_open_risk_pct: Percentage
    daily_loss_limit_pct: Percentage
    authorship: Literal["USER", "AI_IMPORTED"] = "USER"
    provenance: Description

    @model_validator(mode="after")
    def validate_scope(self):
        if set(self.pairs) != {"EURUSD", "USDJPY"} or len(self.pairs) != 2:
            raise ValueError("initial strategy scope requires both forex pairs")
        if self.risk_per_trade_pct > self.total_open_risk_pct:
            raise ValueError("per-trade proposed risk exceeds aggregate proposed risk")
        for field in (
            self.hypothesis,
            self.input_policy,
            self.entry_rules,
            self.exit_rules,
            self.portfolio_policy,
            self.evaluation_plan,
            self.provenance,
        ):
            if len(field.strip()) < 10:
                raise ValueError("meaningful description required")
        return self


class Save(FrozenModel):
    request_id: UUID
    strategy_id: UUID
    parent: Hash | None = None
    specification: Specification


class Freeze(FrozenModel):
    sha256: Hash


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


class Strategies:
    def __init__(self, repo, clock):
        self.repo, self.clock = repo, clock
        with repo.lock, repo.conn:
            repo.conn.executescript("""
                CREATE TABLE IF NOT EXISTS strategy_drafts (
                    seq INTEGER PRIMARY KEY, request_id TEXT UNIQUE NOT NULL,
                    strategy_id TEXT NOT NULL, version INTEGER NOT NULL,
                    sha TEXT UNIQUE NOT NULL, payload TEXT NOT NULL, at TEXT NOT NULL,
                    UNIQUE(strategy_id, version));
                CREATE TABLE IF NOT EXISTS strategy_freezes (
                    sha TEXT PRIMARY KEY, at TEXT NOT NULL);
            """)
            for table in ("strategy_drafts", "strategy_freezes"):
                for action in ("UPDATE", "DELETE"):
                    repo.conn.execute(
                        f"CREATE TRIGGER IF NOT EXISTS immutable_{table}_{action} "
                        f"BEFORE {action} ON {table} "
                        "BEGIN SELECT RAISE(ABORT,'immutable strategy evidence'); END"
                    )

    def save(self, data):
        request = Save.model_validate(data)
        raw = canonical(request.model_dump(mode="json"))
        sha = hashlib.sha256(raw.encode()).hexdigest()
        with self.repo.lock, self.repo.conn:
            self.repo.conn.execute("BEGIN IMMEDIATE")
            prior = self.repo.conn.execute(
                "SELECT sha FROM strategy_drafts WHERE request_id=?", (str(request.request_id),)
            ).fetchone()
            if prior:
                if prior[0] != sha:
                    raise ValueError("request identity reused with different content")
                return self._record(sha)
            latest = self.repo.conn.execute(
                "SELECT sha,version FROM strategy_drafts WHERE strategy_id=? "
                "ORDER BY version DESC LIMIT 1",
                (str(request.strategy_id),),
            ).fetchone()
            if request.parent != (latest[0] if latest else None):
                raise ValueError("revision parent is not current; reload before saving")
            self.repo.conn.execute(
                "INSERT INTO strategy_drafts(request_id,strategy_id,version,sha,payload,at) "
                "VALUES (?,?,?,?,?,?)",
                (
                    str(request.request_id),
                    str(request.strategy_id),
                    latest[1] + 1 if latest else 1,
                    sha,
                    raw,
                    self.clock.now().isoformat(),
                ),
            )
            return self._record(sha)

    def freeze(self, data):
        sha = Freeze.model_validate(data).sha256
        with self.repo.lock, self.repo.conn:
            self.repo.conn.execute("BEGIN IMMEDIATE")
            record = self._record(sha)
            if record["state"] == "FROZEN_FOR_RESEARCH":
                return record
            latest = self.repo.conn.execute(
                "SELECT sha FROM strategy_drafts WHERE strategy_id=? ORDER BY version DESC LIMIT 1",
                (record["strategy_id"],),
            ).fetchone()
            if latest[0] != sha:
                raise ValueError("only latest draft may be frozen")
            self.repo.conn.execute(
                "INSERT INTO strategy_freezes VALUES (?,?)", (sha, self.clock.now().isoformat())
            )
            return self._record(sha)

    def _record(self, sha):
        row = self.repo.conn.execute(
            "SELECT version,payload,at FROM strategy_drafts WHERE sha=?", (sha,)
        ).fetchone()
        if not row or hashlib.sha256(row[1].encode()).hexdigest() != sha:
            raise ValueError("missing or changed strategy record")
        request = Save.model_validate_json(row[1])
        freeze = self.repo.conn.execute(
            "SELECT at FROM strategy_freezes WHERE sha=?", (sha,)
        ).fetchone()
        return dict(
            **request.model_dump(mode="json"),
            version=row[0],
            sha256=sha,
            saved_at=row[2],
            frozen_at=freeze[0] if freeze else None,
            state="FROZEN_FOR_RESEARCH" if freeze else "DRAFT",
            executable=False,
            qualified_for_paper=False,
            execution_enabled=False,
        )

    def read(self):
        with self.repo.lock:
            rows = self.repo.conn.execute(
                "SELECT sha FROM strategy_drafts ORDER BY seq DESC LIMIT 100"
            ).fetchall()
            return dict(
                mode="OFFLINE_RESEARCH",
                execution_enabled=False,
                active_strategy=None,
                milestones=[dict(id=i, title=t, status=s) for i, t, s in MILESTONES],
                gaps=list(GAPS),
                records=[self._record(row[0]) for row in rows],
                history_limit=100,
                ai_generation_enabled=False,
                backtest_enabled=False,
            )
