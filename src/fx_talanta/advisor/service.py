"""Trusted-caller simulator conversation orchestration; no command or broker path."""

import hashlib
import json
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID, uuid5

from psycopg.errors import UniqueViolation

from fx_talanta.advisor.evidence import EvidenceQuery, ReadGrant, project
from fx_talanta.advisor.journal import read_and_record
from fx_talanta.advisor.provider import render_selection
from fx_talanta.advisor.provider_ledger import ProviderBudget, ProviderLedger, explain
from fx_talanta.domain.models import ConversationMessage, EvidenceLink, Record, Versions, utc
from fx_talanta.storage.repository import RecordConflict, Repository


def _save(repository, record):
    """First durable receipt wins, with exact content/scope comparison on retry."""

    def existing():
        try:
            saved = repository.get(record.record_id)
        except KeyError:
            return None
        expected = record.model_dump(mode="json")
        actual = saved.model_dump(mode="json")
        # The original timestamp is retained; callers cannot roll time backwards.
        expected["recorded_at"] = actual["recorded_at"]
        if expected != actual or saved.recorded_at > record.recorded_at:
            raise RecordConflict("advisor service request identity conflict")
        return saved

    saved = existing()
    if saved is not None:
        return saved
    try:
        repository.append_batch((record,))
    except (RecordConflict, UniqueViolation) as error:
        if isinstance(error, UniqueViolation) and error.diag.constraint_name != "message_identity":
            raise
        saved = existing()
        if saved is None:
            raise
        return saved
    return record


def answer_question(
    repository: Repository,
    grant: ReadGrant,
    query: EvidenceQuery,
    question: str,
    *,
    conversation_id: UUID,
    request_id: UUID,
    expires_at: datetime,
    budget: ProviderBudget,
    transport,
    language: Literal["en", "zh"] = "en",
    now=lambda: datetime.now(UTC),
) -> Record:
    """Return only a durable, evidence-linked answer after rechecking read access.

    An unresolved provider reservation raises rather than inventing a saved answer.
    A restarted caller uses the same identity/expiry; it must never create an ID
    automatically to retry an uncertain call. Raw questions are hashed, not journaled.
    """
    grant = ReadGrant.model_validate(grant.model_dump(mode="json"))
    query = EvidenceQuery.model_validate(query.model_dump(mode="json"))
    budget = ProviderBudget.model_validate(budget.model_dump(mode="json"))
    expires_at = utc(expires_at)
    project((), grant, query, now=now())
    if repository.account != grant.account or language not in ("en", "zh"):
        raise PermissionError("advisor service scope mismatch")
    if not isinstance(question, str) or not 1 <= len(question) <= 512:
        raise ValueError("question must contain 1 to 512 characters")
    if expires_at > grant.expires_at or expires_at <= now():
        raise PermissionError("request deadline outside current read grant")
    # There is no model-derived administrative action here, even for imperatives.
    manifest_id = uuid5(request_id, "advisor/service-request/1")
    provider_id = uuid5(request_id, "advisor/provider/1")
    result_id = uuid5(provider_id, "provider-result/1")
    evidence_id = uuid5(request_id, "advisor/answer/1")

    def message(rid, role, data, references=()):
        return Record(
            record_id=rid,
            account=grant.account,
            recorded_at=now(),
            correlation_id=conversation_id,
            provenance="OFFLINE_SIMULATION",
            versions=Versions(component="m4-advisor-service/1", model="none", prompt="none"),
            references=references,
            body=ConversationMessage(
                conversation_id=conversation_id,
                message_id=rid,
                actor_id=grant.actor_id,
                authenticated=False,
                role=role,
                language=language,
                text=json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False),
                interpretation="READ_ONLY",
            ),
        )

    _save(
        repository,
        message(
            manifest_id,
            "USER",
            {
                "version": "advisor-service-request/1",
                "query": query.model_dump(mode="json"),
                "question_sha256": hashlib.sha256(question.encode()).hexdigest(),
                "expires_at": expires_at.isoformat(),
                "budget": budget.model_dump(mode="json"),
                "provider_request_id": str(provider_id),
            },
        ),
    )
    evidence = read_and_record(
        repository,
        grant,
        query,
        conversation_id=conversation_id,
        request_id=request_id,
        language=language,
        now=now(),
    )
    result = explain(
        ProviderLedger(repository),
        evidence,
        question,
        provider_id,
        budget,
        transport,
        expires_at=expires_at,
        now=now,
    )
    # Revoke delivery if access expires during an external call. Provider evidence
    # remains durable; this exception never authorizes another provider request.
    project((), grant, query, now=now())
    try:
        stored = repository.get(result_id)
    except KeyError:
        raise RecordConflict("provider outcome unresolved; no saved answer and no resend") from None
    if stored.body.kind != "message" or json.loads(stored.body.text) != result.model_dump(
        mode="json"
    ):
        raise RecordConflict("provider receipt mismatch")
    text = render_selection(evidence, result, language)
    reply = message(
        uuid5(request_id, "advisor/service-answer/1"),
        "ADVISOR",
        {
            "version": "advisor-service-answer/1",
            "status": result.status,
            "reason": result.reason,
            "explanation_kind": "LATER_EVIDENCE_SELECTION_NOT_ORIGINAL_RATIONALE",
            "scope": evidence.scope,
            "as_of": evidence.as_of.isoformat(),
            "evidence_sha256": result.evidence_sha256,
            "text": text,
            "execution_enabled": False,
        },
        tuple(
            EvidenceLink(record_id=rid, relation="MESSAGE")
            for rid in (manifest_id, evidence_id, result_id)
        ),
    )
    return _save(repository, reply)
