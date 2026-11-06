"""Local durable adapter for the existing bounded M4 provider protocol."""

import hashlib
import json
from datetime import timedelta
from decimal import Decimal
from uuid import UUID

from fx_talanta.advisor.evidence import EvidenceAnswer, EvidenceQuery, ReadGrant, project
from fx_talanta.advisor.provider import ProviderResult, render_selection
from fx_talanta.advisor.provider_ledger import ProviderBudget, explain


class LocalLedger:
    def __init__(self, repository, budget):
        self.repository = repository
        self.budget = ProviderBudget.model_validate(budget.model_dump(mode="json"))
        with repository.lock, repository.conn:
            repository.conn.execute(
                "CREATE TABLE IF NOT EXISTS model_policy (payload TEXT NOT NULL)"
            )
            repository.conn.execute(
                "CREATE TABLE IF NOT EXISTS model_calls (id TEXT PRIMARY KEY, "
                "identity TEXT NOT NULL, "
                "permitted INTEGER NOT NULL, result TEXT)"
            )
            repository.conn.execute(
                "CREATE TABLE IF NOT EXISTS model_requests (id TEXT PRIMARY KEY, "
                "fingerprint TEXT NOT NULL, "
                "evidence TEXT NOT NULL, expires TEXT NOT NULL)"
            )
            row = repository.conn.execute("SELECT payload FROM model_policy").fetchone()
            policy = self.budget.model_dump_json()
            if row and row[0] != policy:
                raise ValueError("provider budget cannot reset or change")
            if not row:
                repository.conn.execute("INSERT INTO model_policy VALUES (?)", (policy,))

    def begin(self, request_id, identity, budget, now):
        if budget != self.budget:
            raise ValueError("budget mismatch")
        encoded = json.dumps(identity, sort_keys=True)
        with self.repository.lock, self.repository.conn:
            old = self.repository.conn.execute(
                "SELECT identity,result FROM model_calls WHERE id=?", (str(request_id),)
            ).fetchone()
            if old:
                if old[0] != encoded:
                    raise ValueError("provider request conflict")
                return False, json.loads(old[1]) if old[1] else None, "OUTCOME_UNKNOWN_NO_RESEND"
            count = self.repository.conn.execute(
                "SELECT count(*) FROM model_calls WHERE permitted=1"
            ).fetchone()[0]
            allowed = (
                count < budget.max_calls
                and Decimal(count + 1) * budget.reserve_per_call_usd <= budget.total_reserved_usd
            )
            self.repository.conn.execute(
                "INSERT INTO model_calls VALUES (?,?,?,NULL)",
                (str(request_id), encoded, int(allowed)),
            )
            return allowed, None, "RESERVED" if allowed else "BUDGET_EXHAUSTED"

    def finish(self, request_id, identity, result):
        with self.repository.lock, self.repository.conn:
            row = self.repository.conn.execute(
                "SELECT identity,result FROM model_calls WHERE id=?", (str(request_id),)
            ).fetchone()
            value = result.model_dump_json()
            if not row or row[0] != json.dumps(identity, sort_keys=True):
                raise ValueError("reservation mismatch")
            if row[1] is not None and row[1] != value:
                raise ValueError("immutable provider outcome")
            if row[1] is None:
                self.repository.conn.execute(
                    "UPDATE model_calls SET result=? WHERE id=? AND result IS NULL",
                    (value, str(request_id)),
                )

    def status(self):
        with self.repository.lock:
            row = self.repository.conn.execute(
                "SELECT count(*),sum(result IS NULL) FROM model_calls WHERE permitted=1"
            ).fetchone()
            return dict(
                enabled=True,
                reserved_calls=row[0],
                unresolved_calls=row[1] or 0,
                max_calls=self.budget.max_calls,
                mode="BOUNDED_M4_EVIDENCE_SELECTION",
                execution_enabled=False,
            )


class ModelAdvisor:
    def __init__(self, app, budget, transport):
        self.app, self.transport = app, transport
        self.ledger = LocalLedger(app.repo, budget)

    def answer(self, data):
        if not isinstance(data, dict) or set(data) != {
            "request_id",
            "question",
            "record_id",
            "language",
        }:
            raise ValueError("invalid explanation request")
        rid = UUID(data["request_id"])
        if (
            data["language"] not in ("en", "zh")
            or not isinstance(data["question"], str)
            or not 1 <= len(data["question"].strip()) <= 512
        ):
            raise ValueError("invalid explanation input")
        ids = (
            (UUID(data["record_id"]),)
            if data["record_id"]
            else tuple(r.record_id for r in self.app.snapshot.records[-32:])
        )
        if not ids or any(i not in self.app.repo.sources for i in ids):
            raise ValueError("evidence unavailable")
        fingerprint = hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()
        self.app.authorize(self.app.token)
        with self.app.repo.lock:
            now = self.app.clock.now()
            self.app.monitor.read(now)
        with self.app.repo.lock, self.app.repo.conn:
            old = self.app.repo.conn.execute(
                "SELECT fingerprint,evidence,expires FROM model_requests WHERE id=?", (str(rid),)
            ).fetchone()
            if old:
                if old[0] != fingerprint:
                    raise ValueError("request conflict")
                evidence = EvidenceAnswer.model_validate_json(old[1])
                from datetime import datetime

                expires = datetime.fromisoformat(old[2])
            else:
                expires = min(now + timedelta(seconds=20), self.app.expires_at)
                evidence = project(
                    self.app.snapshot.records,
                    ReadGrant(
                        actor_id="local-viewer",
                        account=self.app.snapshot.account,
                        expires_at=self.app.expires_at,
                    ),
                    EvidenceQuery(
                        account=self.app.snapshot.account,
                        as_of=self.app.snapshot.captured_at,
                        record_ids=ids,
                    ),
                    now=now,
                )
                self.app.repo.conn.execute(
                    "INSERT INTO model_requests VALUES (?,?,?,?)",
                    (str(rid), fingerprint, evidence.model_dump_json(), expires.isoformat()),
                )
        if now < evidence.generated_at:
            raise ValueError("explanation clock rollback")
        with self.app.repo.lock:
            saved = self.app.repo.conn.execute(
                "SELECT result,identity FROM model_calls WHERE id=?", (str(rid),)
            ).fetchone()
        # Network work is outside the SQLite lock: monitoring stays responsive.
        if saved and saved[0]:
            result = ProviderResult.model_validate_json(saved[0])
        elif saved:
            identity = json.loads(saved[1])
            result = ProviderResult(
                status="HOLD",
                reason="OUTCOME_UNKNOWN_NO_RESEND",
                completed_at=now,
                request_sha256=identity["request_sha256"],
                evidence_sha256=identity["evidence_sha256"],
            )
        else:
            result = explain(
                self.ledger,
                evidence,
                data["question"],
                rid,
                self.ledger.budget,
                self.transport,
                expires_at=expires,
                now=self.app.clock.now,
            )
        self.app.authorize(self.app.token)
        answer = dict(
            mode="M4 bounded evidence selection",
            request_id=str(rid),
            answered_at=result.completed_at.isoformat(),
            text=render_selection(evidence, result, data["language"]),
            status=result.status,
            reason=result.reason,
            citations=[
                c.model_dump(mode="json")
                for c in evidence.citations
                if c.record_id in result.citation_ids
            ],
            execution_enabled=False,
        )
        if result.reason != "OUTCOME_UNKNOWN_NO_RESEND":
            with self.app.repo.lock, self.app.repo.conn:
                self.app.repo.conn.execute(
                    "INSERT INTO chats VALUES (?,?,?) ON CONFLICT(id) DO NOTHING",
                    ("model:" + str(rid), fingerprint, json.dumps(answer)),
                )
        return answer
