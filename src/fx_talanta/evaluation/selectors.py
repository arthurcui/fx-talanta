"""Bounded recorded model replies for simulation; no provider transport or credentials."""

from typing import Annotated, Literal

from pydantic import Field, model_validator

from fx_talanta.advisor.proposal_contracts import Selection
from fx_talanta.domain.models import FrozenModel, Hash, Identifier, NonNegative, Timestamp
from fx_talanta.evaluation.ledger import digest


class Profile(FrozenModel):
    model: Identifier
    prompt_hash: Hash
    max_latency_ms: Annotated[int, Field(strict=True, ge=1, le=2000)] = 1500


class Reply(FrozenModel):
    request_hash: Hash
    returned_model: Identifier | None = None
    completed_at: Timestamp
    status: Literal["RESPONSE", "TIMEOUT", "ERROR"]
    response: Annotated[str, Field(max_length=4096)] | None = None
    input_tokens: Annotated[int, Field(strict=True, ge=0, le=100000)] = 0
    output_tokens: Annotated[int, Field(strict=True, ge=0, le=100000)] = 0
    reported_cost_usd: NonNegative | None = None


class Batch(FrozenModel):
    requested_at: Timestamp
    replies: dict[Literal["AI_NO_NEWS", "AI_NEWS"], Reply]

    @model_validator(mode="after")
    def paired(self):
        if set(self.replies) != {"AI_NO_NEWS", "AI_NEWS"}:
            raise ValueError("both AI arm replies required")
        if any(r.completed_at < self.requested_at for r in self.replies.values()):
            raise ValueError("model completion precedes request")
        return self


def request(profile, input_hash, arm, candidate, candidate_id, at, news):
    payload = dict(
        schema="recorded-selection-request/1",
        profile=profile.model_dump(mode="json"),
        input_hash=input_hash,
        arm=arm,
        candidate=candidate,
        candidate_id=str(candidate_id),
        requested_at=at.isoformat(),
        allowed_exits=["TIME_EXIT"] if candidate["action"] == "CANDIDATE" else [],
    )
    if arm == "AI_NEWS":
        payload["news"] = news
    return dict(payload=payload, request_hash=digest(payload))


def assess(profile, prepared, reply, requested_at, at):
    """Unusable replies are recorded HOLDs, never executable fallbacks."""
    if reply.completed_at > at:
        raise ValueError("future model reply")
    latency = int((reply.completed_at - requested_at).total_seconds() * 1000)
    reason = None
    selection = None
    if reply.request_hash != prepared["request_hash"]:
        reason = "MODEL_REQUEST_MISMATCH"
    elif reply.status != "RESPONSE":
        reason = "MODEL_" + reply.status
    elif reply.returned_model != profile.model:
        reason = "MODEL_IDENTITY_MISMATCH"
    elif (reply.completed_at - requested_at).total_seconds() * 1000 > profile.max_latency_ms:
        reason = "MODEL_LATENCY_EXCEEDED"
    else:
        try:
            selection = Selection.model_validate_json(reply.response or "")
            if selection.action == "SELECT" and (
                str(selection.candidate_id) != prepared["payload"]["candidate_id"]
                or selection.exit_option not in prepared["payload"]["allowed_exits"]
            ):
                reason = "MODEL_UNSUPPORTED_SELECTION"
            elif selection.action == "HOLD":
                reason = "MODEL_HOLD"
        except ValueError:
            reason = "MODEL_MALFORMED"
    return dict(
        allowed=reason is None,
        reason=reason or "MODEL_CANDIDATE_SELECTED",
        latency_ms=latency,
        request_hash=prepared["request_hash"],
        response_hash=digest(reply.model_dump(mode="json")),
        selection=selection.model_dump(mode="json") if selection else None,
        input_tokens=reply.input_tokens,
        output_tokens=reply.output_tokens,
        reported_cost_usd=str(reply.reported_cost_usd)
        if reply.reported_cost_usd is not None
        else None,
        external_call_verified=False,
    )
