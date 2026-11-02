"""Bounded, deterministic DecisionSource and recording; no execution path."""

import json
from collections import deque
from collections.abc import Iterable
from typing import Protocol
from uuid import UUID, uuid5

from pydantic import ValidationError

from fx_talanta.clock import Clock
from fx_talanta.domain.models import (
    AccountIdentity,
    Decision,
    DecisionAttempt,
    EvidenceLink,
    ExperienceCase,
    ModelTrace,
    Record,
)
from fx_talanta.storage.repository import Repository


class DecisionSource(Protocol):
    def decide(self) -> str: ...


class ScriptedDecisionSource:
    def __init__(self, responses: Iterable[str]):
        self._responses = deque(responses)

    def decide(self) -> str:
        return self._responses.popleft()


def record_attempt(
    repository: Repository,
    source: DecisionSource,
    clock: Clock,
    run_id: UUID,
    label: str,
    news: tuple[UUID, ...],
) -> Record:
    now, raw = clock.now(), source.decide()
    # M0A inputs are synthetic fixture strings; production capture/redaction belongs
    # at a future provider boundary before any external response reaches this API.
    decision = None
    result, action, reason = "MALFORMED", "HOLD", "response failed the decision contract"
    try:
        decision = Decision.model_validate_json(raw)
        if decision.account != repository.account:
            result, reason = "REJECTED", "response account differs from the bound account"
        elif decision.expires_at <= now:
            result, reason = "EXPIRED", "response expired before recording"
        elif decision.action == "ENTER" and decision.candidate_id != "B01-fixture":
            result, reason = "REJECTED", "candidate is not in the supplied fixture snapshot"
        else:
            result, action = ("HOLD" if decision.action == "HOLD" else "VALID"), decision.action
            reason = decision.rationale
    except ValidationError:
        pass
    attempt = Record(
        record_id=uuid5(run_id, label),
        account=repository.account,
        recorded_at=now,
        correlation_id=run_id,
        references=tuple(EvidenceLink(record_id=n, relation="NEWS") for n in news),
        body=DecisionAttempt(
            result=result,
            action=action,
            cutoff=now,
            input_snapshot="fixture-snapshot/1",
            candidates=("B01-fixture",),
            response=raw,
            decision=decision,
            reason=reason,
            trace=ModelTrace(request_id=uuid5(run_id, label + "/model")),
        ),
    )
    operational = {
        "VALID": "SUCCESS",
        "HOLD": "HOLD",
        "MALFORMED": "INVALID",
        "EXPIRED": "EXPIRED",
        "REJECTED": "REJECTED",
    }[result]
    experience = Record(
        record_id=uuid5(run_id, label + "/case"),
        account=repository.account,
        recorded_at=now,
        correlation_id=run_id,
        references=(EvidenceLink(record_id=attempt.record_id, relation="DECISION"),),
        body=ExperienceCase(
            operational_result=operational,
            policy_compliance="COMPLIANT",
            economic_outcome="NOT_APPLICABLE",
            outcome_known_at=now,
            summary=f"Scripted {result} decision recorded; no order submitted.",
        ),
    )
    repository.append_batch((attempt, experience))
    return attempt


def response(account: AccountIdentity, expires_at, *, action="ENTER", **changes) -> str:
    data = dict(
        account=account.model_dump(mode="json"),
        action=action,
        candidate_id="B01-fixture",
        symbol="EURUSD",
        side="BUY",
        expires_at=expires_at.isoformat(),
        rationale="Scripted fixture decision",
    )
    data.update(changes)
    return json.dumps(data, sort_keys=True)
