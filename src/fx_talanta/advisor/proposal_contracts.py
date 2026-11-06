"""Strict model selection over server-defined simulator candidates."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, model_validator

from fx_talanta.domain.models import AccountIdentity, FrozenModel, Identifier, Timestamp
from fx_talanta.domain.offline import Positive


class ExitOption(FrozenModel):
    name: Literal["FIXED", "TIME_EXIT"]
    target: Positive
    maximum_holding_seconds: Annotated[int, Field(strict=True, ge=1, le=86400)]


class Candidate(FrozenModel):
    candidate_id: UUID
    strategy: Identifier
    symbol: Literal["EURUSD", "USDJPY"]
    side: Literal["BUY", "SELL"]
    stop: Positive
    benchmark: Positive
    exits: Annotated[tuple[ExitOption, ...], Field(min_length=1, max_length=2)]

    @model_validator(mode="after")
    def distinct(self):
        if len({e.name for e in self.exits}) != len(self.exits):
            raise ValueError("duplicate exit option")
        return self


class ProposalInput(FrozenModel):
    account: AccountIdentity
    cutoff: Timestamp
    quote_at: Timestamp
    expires_at: Timestamp
    candidates: Annotated[tuple[Candidate, ...], Field(max_length=8)]
    evidence_ids: Annotated[tuple[UUID, ...], Field(max_length=24)] = ()

    @model_validator(mode="after")
    def coherent(self):
        if self.quote_at > self.cutoff or self.expires_at <= self.cutoff:
            raise ValueError("invalid proposal times")
        if len({c.candidate_id for c in self.candidates}) != len(self.candidates):
            raise ValueError("duplicate candidate")
        return self


class Selection(FrozenModel):
    action: Literal["SELECT", "HOLD"]
    candidate_id: UUID | None
    exit_option: Literal["FIXED", "TIME_EXIT"] | None
    reason: Literal["CANDIDATE_SELECTED", "INSUFFICIENT_EVIDENCE", "UNSAFE_INPUT"]

    @model_validator(mode="after")
    def coherent(self):
        if self.action == "SELECT":
            if (
                self.candidate_id is None
                or self.exit_option is None
                or self.reason != "CANDIDATE_SELECTED"
            ):
                raise ValueError("incomplete selection")
        elif (
            self.candidate_id is not None
            or self.exit_option is not None
            or self.reason == "CANDIDATE_SELECTED"
        ):
            raise ValueError("inconsistent hold")
        return self


class ProposalReceipt(FrozenModel):
    version: Literal["bounded-strategy-proposal/1"] = "bounded-strategy-proposal/1"
    status: Literal["SELECT", "HOLD"]
    reason: str
    selection: Selection | None = None
    prompt_version: Literal["strategy-selection/1"] = "strategy-selection/1"
    request_sha256: str
    evidence_sha256: str
    response_sha256: str | None = None
    requested_model: str
    returned_model: str | None = None
    latency_ms: Annotated[int, Field(ge=0)] = 0
    input_tokens: Annotated[int, Field(ge=0)] = 0
    output_tokens: Annotated[int, Field(ge=0)] = 0
    completed_at: Timestamp
    execution_enabled: Literal[False] = False
