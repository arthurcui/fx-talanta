"""Disabled simulator provider orchestration with append-only PostgreSQL reservations.

One lifetime budget per bound database. No automatic reset, refund or resend.
This is a trusted-caller service, not owner authentication or a billing attestation.
"""

import hashlib
import json
import time
import urllib.error
from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated
from uuid import NAMESPACE_URL, UUID, uuid5

import psycopg
from pydantic import Field

from fx_talanta.advisor.evidence import EvidenceAnswer
from fx_talanta.advisor.provider import (
    MODEL,
    TIMEOUT_SECONDS,
    ProviderResult,
    parse_selection,
    payload_for,
)
from fx_talanta.domain.models import (
    ConversationMessage,
    FrozenModel,
    NonNegative,
    Record,
    Versions,
    utc,
)
from fx_talanta.storage.repository import RecordConflict, Repository

BUDGET_ID = uuid5(NAMESPACE_URL, "fx-talanta/provider-budget/1")
LOCK_ID = 640041


class ProviderBudget(FrozenModel):
    max_calls: Annotated[int, Field(strict=True, ge=1, le=100)]
    reserve_per_call_usd: Annotated[NonNegative, Field(gt=0)]
    total_reserved_usd: Annotated[NonNegative, Field(gt=0)]
    basis: Annotated[str, Field(min_length=1, max_length=256)]


def encoded(data):
    return json.dumps(data, sort_keys=True, separators=(",", ":"))


class ProviderLedger:
    def __init__(self, repository: Repository):
        if repository.account.venue != "SIMULATOR":
            raise PermissionError("provider ledger requires disabled simulator")
        self.repository = repository

    def _message(self, rid, component, data, now):
        return Record(
            record_id=rid,
            account=self.repository.account,
            recorded_at=now,
            correlation_id=BUDGET_ID,
            provenance="OFFLINE_SIMULATION",
            versions=Versions(
                component=component,
                model=MODEL,
                prompt=data.get(
                    "prompt_version",
                    data.get("identity", {}).get("prompt_version", "evidence-selection/1"),
                ),
            ),
            body=ConversationMessage(
                conversation_id=BUDGET_ID,
                message_id=rid,
                actor_id="offline-provider-service",
                authenticated=False,
                role="ADVISOR",
                language="en",
                text=encoded(data),
                interpretation="READ_ONLY",
            ),
        )

    def _get(self, conn, rid, component):
        row = conn.execute("SELECT payload FROM fx.records WHERE record_id=%s", (rid,)).fetchone()
        if row is None:
            return None
        record = Record.model_validate(row[0])
        if (
            record.account != self.repository.account
            or record.body.kind != "message"
            or record.versions.component != component
            or record.correlation_id != BUDGET_ID
        ):
            raise RecordConflict("provider record identity conflict")
        return json.loads(record.body.text)

    def begin(self, request_id, identity, budget, now):
        budget = ProviderBudget.model_validate(budget.model_dump(mode="json"))
        now = utc(now)
        rid = uuid5(request_id, "provider-reservation/1")
        result_id = uuid5(request_id, "provider-result/1")
        with psycopg.connect(self.repository._dsn) as conn:
            conn.execute("SELECT pg_advisory_xact_lock(%s)", (LOCK_ID,))
            self.repository._check_binding(conn)
            policy = self._get(conn, BUDGET_ID, "provider-policy/1")
            if policy is not None and policy != budget.model_dump(mode="json"):
                raise RecordConflict("provider budget cannot be reset or changed")
            old = self._get(conn, rid, "provider-reservation/1")
            if old is not None:
                if old["identity"] != identity:
                    raise RecordConflict("request identity reused for different input")
                result = self._get(conn, result_id, "provider-result/1")
                return False, result, "OUTCOME_UNKNOWN_NO_RESEND"
            rows = conn.execute(
                "SELECT payload FROM fx.records WHERE payload->>'correlation_id'=%s "
                "AND payload#>>'{versions,component}'='provider-reservation/1'",
                (str(BUDGET_ID),),
            ).fetchall()
            reserved = [json.loads(Record.model_validate(row[0]).body.text) for row in rows]
            if reserved and policy is None:
                raise RecordConflict("missing original provider policy")
            used = [r for r in reserved if r["send_permitted"]]
            total = sum((Decimal(r["reserved_usd"]) for r in used), Decimal(0))
            allowed = (
                len(used) < budget.max_calls
                and total + budget.reserve_per_call_usd <= budget.total_reserved_usd
            )
            records = []
            if policy is None:
                records.append(
                    self._message(
                        BUDGET_ID, "provider-policy/1", budget.model_dump(mode="json"), now
                    )
                )
            records.append(
                self._message(
                    rid,
                    "provider-reservation/1",
                    {
                        "identity": identity,
                        "send_permitted": allowed,
                        "reserved_usd": str(budget.reserve_per_call_usd if allowed else Decimal(0)),
                    },
                    now,
                )
            )
            self.repository.append_in(conn, records)
        return allowed, None, "RESERVED" if allowed else "BUDGET_EXHAUSTED"

    def finish(self, request_id, identity, result):
        from fx_talanta.advisor.proposal_contracts import ProposalReceipt

        model = ProposalReceipt if isinstance(result, ProposalReceipt) else ProviderResult
        result = model.model_validate(result.model_dump(mode="json"))
        with psycopg.connect(self.repository._dsn) as conn:
            conn.execute("SELECT pg_advisory_xact_lock(%s)", (LOCK_ID,))
            self.repository._check_binding(conn)
            old = self._get(
                conn, uuid5(request_id, "provider-reservation/1"), "provider-reservation/1"
            )
            if old is None or old["identity"] != identity:
                raise RecordConflict("result has no matching reservation")
            if (
                result.request_sha256 != identity["request_sha256"]
                or result.evidence_sha256 != identity["evidence_sha256"]
            ):
                raise RecordConflict("result does not match input")
            rid = uuid5(request_id, "provider-result/1")
            previous = self._get(conn, rid, "provider-result/1")
            if previous is not None:
                if previous != result.model_dump(mode="json"):
                    raise RecordConflict("provider result is immutable")
                return
            if not old["send_permitted"] and result.status != "HOLD":
                raise RecordConflict("denied budget cannot produce explanation")
            self.repository.append_in(
                conn,
                (
                    self._message(
                        rid,
                        "provider-result/1",
                        result.model_dump(mode="json"),
                        result.completed_at,
                    ),
                ),
            )


def explain(
    ledger: ProviderLedger,
    evidence: EvidenceAnswer,
    question: str,
    request_id: UUID,
    budget: ProviderBudget,
    transport,
    *,
    expires_at: datetime,
    now=lambda: datetime.now(UTC),
    monotonic=time.monotonic,
) -> ProviderResult:
    evidence = EvidenceAnswer.model_validate(evidence.model_dump(mode="json"))
    expires_at = utc(expires_at)
    if evidence.account != ledger.repository.account:
        raise PermissionError("provider evidence account mismatch")
    payload = payload_for(evidence, question)
    identity = {
        "request_sha256": hashlib.sha256(payload).hexdigest(),
        "evidence_sha256": hashlib.sha256(evidence.model_dump_json().encode()).hexdigest(),
        "expires_at": expires_at.isoformat(),
    }

    def hold(reason, **extra):
        return ProviderResult(
            status="HOLD",
            reason=reason,
            completed_at=now(),
            request_sha256=identity["request_sha256"],
            evidence_sha256=identity["evidence_sha256"],
            **extra,
        )

    if now() >= expires_at or evidence.generated_at > now() or evidence.as_of > now():
        return hold("EXPIRED")
    allowed, previous, reason = ledger.begin(request_id, identity, budget, now())
    if previous is not None:
        return ProviderResult.model_validate(previous)
    if not allowed:
        result = hold(reason)
        # An unresolved sender may still be running. Never overwrite its outcome.
        if reason == "BUDGET_EXHAUSTED":
            ledger.finish(request_id, identity, result)
        return result
    start = monotonic()
    try:
        if now() >= expires_at:
            result = hold("EXPIRED")
        else:
            raw = transport(payload)
            latency = int((monotonic() - start) * 1000)
            if latency < 0 or latency > TIMEOUT_SECONDS * 1000 or now() >= expires_at:
                result = hold("EXPIRED", response_sha256=hashlib.sha256(raw).hexdigest())
            else:
                selection, usage = parse_selection(raw, evidence)
                result = ProviderResult(
                    status=selection.decision,
                    reason=selection.reason,
                    completed_at=now(),
                    request_sha256=identity["request_sha256"],
                    evidence_sha256=identity["evidence_sha256"],
                    response_sha256=hashlib.sha256(raw).hexdigest(),
                    returned_model=MODEL,
                    latency_ms=latency,
                    input_tokens=usage["input_tokens"],
                    output_tokens=usage["output_tokens"],
                    citation_ids=selection.citation_ids,
                )
    except urllib.error.HTTPError as error:
        result = hold(f"HTTP_{error.code}")
    except (OSError, ValueError, KeyError, TypeError):
        result = hold("PROVIDER_FAILURE_HOLD")
    # If this commit fails, return an error. The durable reservation remains spent;
    # retry returns unknown/HOLD and never repeats an external call.
    ledger.finish(request_id, identity, result)
    return result
