"""Offline evidence projection. No model, broker, network or mutation capability.

ReadGrant must come from a trusted caller; it is NOT an authentication mechanism.
Only simulator records are supported until a separately authenticated API exists.
"""

import hashlib
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field

from fx_talanta.domain.models import (
    AccountIdentity,
    FrozenModel,
    Identifier,
    Record,
    Timestamp,
    utc,
)


class ReadGrant(FrozenModel):
    actor_id: Identifier
    account: AccountIdentity
    expires_at: Timestamp


class EvidenceQuery(FrozenModel):
    account: AccountIdentity
    as_of: Timestamp
    record_ids: Annotated[tuple[UUID, ...], Field(min_length=1, max_length=32)]


class Fact(FrozenModel):
    name: Identifier
    value: str


class Citation(FrozenModel):
    record_id: UUID
    recorded_at: Timestamp
    sha256: str
    provenance: str
    kind: str
    facts: tuple[Fact, ...]
    unresolved_references: tuple[UUID, ...]
    memory_eligible: bool = False


class EvidenceAnswer(FrozenModel):
    version: Literal["advisor-evidence/1"] = "advisor-evidence/1"
    account: AccountIdentity
    actor_id: Identifier
    as_of: Timestamp
    generated_at: Timestamp
    citations: tuple[Citation, ...]
    unavailable: tuple[UUID, ...]
    scope: Literal["EXACT_REQUESTED_RECORDS_NOT_CURRENT_ACCOUNT_STATUS"] = (
        "EXACT_REQUESTED_RECORDS_NOT_CURRENT_ACCOUNT_STATUS"
    )
    execution_enabled: Literal[False] = False


# Free text, raw model responses, news excerpts and command payloads never become
# executable instructions or advisor prose here. Values are validated enums/numbers.
FIELDS = {
    "decision": ("result", "action", "cutoff"),
    "risk": ("approved", "proposed_volume", "planned_loss", "evaluation_mode"),
    "execution": ("state", "filled_volume"),
    "experience": ("operational_result", "policy_compliance", "economic_outcome", "net_pnl"),
    "lesson": ("status", "sample_size", "activated_at"),
    "news": ("revision", "published_at", "available_at"),
    "health": ("checked_at", "connection", "coverage", "required"),
    "promotion": ("result", "activation_enabled"),
}


def project(
    records: tuple[Record, ...], grant: ReadGrant, query: EvidenceQuery, *, now: datetime
) -> EvidenceAnswer:
    """Project a bounded trusted-caller snapshot, never fetch or execute anything."""
    grant = ReadGrant.model_validate(grant.model_dump(mode="json"))
    query = EvidenceQuery.model_validate(query.model_dump(mode="json"))
    now = utc(now)
    if grant.account != query.account or grant.account.venue != "SIMULATOR":
        raise PermissionError("simulator account scope mismatch")
    if now >= grant.expires_at or query.as_of > now:
        raise PermissionError("expired grant or future query")
    if len(records) > 1000 or len(set(query.record_ids)) != len(query.record_ids):
        raise ValueError("oversized snapshot or duplicate request")
    index = {}
    for candidate in records:
        record = Record.model_validate(candidate.model_dump(mode="json"))
        if record.account != grant.account:
            raise PermissionError("mixed account snapshot")
        if record.record_id in index:
            raise ValueError("duplicate record identity")
        index[record.record_id] = record

    def visible(record):
        if record is None or record.recorded_at > query.as_of:
            return False
        body = record.body
        if body.kind == "health" and body.checked_at > query.as_of:
            return False
        return True

    citations, unavailable = [], []
    for record_id in query.record_ids:
        record = index.get(record_id)
        if not visible(record) or record.body.kind not in FIELDS:
            unavailable.append(record_id)
            continue
        body = record.body
        dependencies = {r.record_id for r in record.references}
        if record.supersedes:
            dependencies.add(record.supersedes)
        if body.kind == "lesson":
            dependencies.update(body.supporting_cases + body.contradicting_cases)
        unresolved = tuple(
            sorted((rid for rid in dependencies if not visible(index.get(rid))), key=str)
        )
        memory = False
        if body.kind == "lesson":
            cases = body.supporting_cases + body.contradicting_cases
            memory = bool(
                body.status == "QUALIFIED"
                and body.activated_at is not None
                and body.activated_at <= query.as_of
                and body.supporting_cases
                and len(set(cases)) == len(cases)
                and not unresolved
                and all(
                    index[rid].body.kind == "experience"
                    and index[rid].body.outcome_known_at is not None
                    and index[rid].body.outcome_known_at <= query.as_of
                    for rid in cases
                )
            )
        data = body.model_dump(mode="json")
        citations.append(
            Citation(
                record_id=record_id,
                recorded_at=record.recorded_at,
                sha256=hashlib.sha256(record.model_dump_json().encode()).hexdigest(),
                provenance=record.provenance,
                kind=body.kind,
                facts=tuple(
                    Fact(name=k, value="UNKNOWN" if data[k] is None else str(data[k]))
                    for k in FIELDS[body.kind]
                ),
                unresolved_references=unresolved,
                memory_eligible=memory,
            )
        )
    return EvidenceAnswer(
        account=query.account,
        actor_id=grant.actor_id,
        as_of=query.as_of,
        generated_at=now,
        citations=tuple(citations),
        unavailable=tuple(unavailable),
    )


def render(answer: EvidenceAnswer, language: Literal["en", "zh"] = "en") -> str:
    """Fixed bilingual labels, not natural-language interpretation or AI reasoning."""
    answer = EvidenceAnswer.model_validate(answer.model_dump(mode="json"))
    if language not in ("en", "zh"):
        raise ValueError("unsupported language")
    heading, missing, disabled = (
        ("Recorded evidence as of", "Unavailable records", "Trading disabled")
        if language == "en"
        else ("截至此时的已记录证据", "不可用记录", "交易已禁用")
    )
    lines = [
        f"{heading}: {answer.as_of.isoformat()}",
        f"{answer.account.environment}/{answer.account.broker}/{answer.account.server}/"
        f"{answer.account.login}",
        disabled,
        answer.scope,
    ]
    for citation in answer.citations:
        facts = ", ".join(f"{f.name}={f.value}" for f in citation.facts)
        lines.append(
            f"[{citation.record_id}] {citation.kind}: {facts}; "
            f"provenance={citation.provenance}; memory_eligible={citation.memory_eligible}; "
            f"unresolved_references={len(citation.unresolved_references)}"
        )
    lines.append(f"{missing}: {len(answer.unavailable)}")
    return "\n".join(lines)
