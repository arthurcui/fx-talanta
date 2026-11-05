"""Atomic simulator-only advisor receipts using existing append-only message records.

Trusted in-process caller only; no authentication, arbitrary text or command routing.
"""

import json
from datetime import datetime
from typing import Literal
from uuid import UUID, uuid5

from psycopg.errors import UniqueViolation

from fx_talanta.advisor.evidence import EvidenceAnswer, EvidenceQuery, ReadGrant, project
from fx_talanta.domain.models import ConversationMessage, EvidenceLink, Record, Versions, utc
from fx_talanta.storage.repository import RecordConflict, Repository


def read_and_record(
    repository: Repository,
    grant: ReadGrant,
    query: EvidenceQuery,
    *,
    conversation_id: UUID,
    request_id: UUID,
    now: datetime,
    language: Literal["en", "zh"] = "en",
) -> EvidenceAnswer:
    """Record typed query and exact receipt together; retries return the first receipt.

    Existing Text limits apply. Oversized receipts fail BEFORE any append; callers
    must request fewer records rather than silently truncating supporting evidence.
    """
    now = utc(now)
    grant = ReadGrant.model_validate(grant.model_dump(mode="json"))
    query = EvidenceQuery.model_validate(query.model_dump(mode="json"))
    project((), grant, query, now=now)  # Validate scope/time before any repository access.
    if repository.account != grant.account or language not in ("en", "zh"):
        raise PermissionError("repository scope or language mismatch")
    user_id, answer_id = uuid5(request_id, "advisor/query/1"), uuid5(request_id, "advisor/answer/1")
    request_text = json.dumps(
        {"version": "advisor-query/1", "query": query.model_dump(mode="json")},
        sort_keys=True,
        separators=(",", ":"),
    )

    def existing(*, retry_lookup=True):
        try:
            user = repository.get(user_id)
        except KeyError:
            try:
                repository.get(answer_id)
            except KeyError:
                return None
            # The atomic pair may have committed between the two get calls.
            if retry_lookup:
                return existing(retry_lookup=False)
            raise RecordConflict("orphan advisor receipt") from None
        if (
            user.account != grant.account
            or user.correlation_id != conversation_id
            or user.body.kind != "message"
            or user.body.role != "USER"
            or user.body.actor_id != grant.actor_id
            or user.body.language != language
            or user.body.text != request_text
            or user.body.interpretation != "READ_ONLY"
            or user.body.interpreted_action is not None
        ):
            raise RecordConflict("request identity already has different content")
        try:
            saved = repository.get(answer_id)
        except KeyError:
            raise RecordConflict("incomplete advisor receipt") from None
        if (
            saved.account != grant.account
            or saved.correlation_id != conversation_id
            or saved.body.kind != "message"
            or saved.body.role != "ADVISOR"
            or saved.body.actor_id != grant.actor_id
            or saved.body.language != language
            or saved.body.interpretation != "READ_ONLY"
            or saved.body.interpreted_action is not None
            or saved.references != (EvidenceLink(record_id=user_id, relation="MESSAGE"),)
        ):
            raise RecordConflict("invalid advisor receipt")
        receipt = EvidenceAnswer.model_validate_json(saved.body.text)
        if (
            receipt.account != grant.account
            or receipt.actor_id != grant.actor_id
            or receipt.as_of != query.as_of
            or receipt.generated_at != saved.recorded_at
            or receipt.generated_at > now
        ):
            raise RecordConflict("receipt scope/time mismatch")
        return receipt

    previous = existing()
    if previous is not None:
        return previous

    # Read exact immutable IDs and their dependency closure; never scan account
    # history or replace versions with later corrections. Missing IDs stay unknown.
    pending, seen, records = list(query.record_ids), set(), []
    while pending:
        rid = pending.pop()
        if rid in seen:
            continue
        seen.add(rid)
        if len(seen) > 1000:
            raise ValueError("evidence dependency limit exceeded")
        try:
            candidate = repository.get(rid)
        except KeyError:
            continue
        record = Record.model_validate(candidate.model_dump(mode="json"))
        if record.record_id != rid or record.account != grant.account:
            raise PermissionError("evidence identity mismatch")
        records.append(record)
        if record.recorded_at > query.as_of:
            continue
        pending.extend(ref.record_id for ref in record.references)
        if record.supersedes:
            pending.append(record.supersedes)
        if record.body.kind == "lesson":
            pending.extend(record.body.supporting_cases + record.body.contradicting_cases)
    answer = project(tuple(records), grant, query, now=now)
    versions = Versions(component="m4-advisor-journal/1", model="none", prompt="none")

    def message(rid, role, text, references=()):
        return Record(
            record_id=rid,
            account=grant.account,
            recorded_at=now,
            correlation_id=conversation_id,
            provenance="OFFLINE_SIMULATION",
            versions=versions,
            references=references,
            body=ConversationMessage(
                conversation_id=conversation_id,
                message_id=rid,
                actor_id=grant.actor_id,
                authenticated=False,
                role=role,
                language=language,
                text=text,
                interpretation="READ_ONLY",
            ),
        )

    # Construct both before writing so the 4096-character contract never leaves a
    # partial conversation. PostgreSQL append_batch commits or rolls back both.
    user = message(user_id, "USER", request_text)
    reply = message(
        answer_id,
        "ADVISOR",
        answer.model_dump_json(),
        (EvidenceLink(record_id=user_id, relation="MESSAGE"),),
    )
    try:
        repository.append_batch((user, reply))
    except (RecordConflict, UniqueViolation) as error:
        if isinstance(error, UniqueViolation) and error.diag.constraint_name != "message_identity":
            raise
        # Concurrent identical request may have committed with another timestamp.
        # PostgreSQL may report the separate message_identity unique index before
        # ON CONFLICT(record_id). The failed transaction is already rolled back.
        # Validate identity again; never overwrite or regenerate a winning receipt.
        winner = existing()
        if winner is None:
            raise
        return winner
    return answer
