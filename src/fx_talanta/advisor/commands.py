"""Pure administrative-command simulation. No broker, model, auth or dispatch API.

The trusted harness supplies scope and state. These transitions are NOT gateway
state changes and cannot constitute confirmed broker execution.
"""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, model_validator

from fx_talanta.domain.models import AccountIdentity, FrozenModel, Identifier, Timestamp, utc

Action = Literal[
    "PAUSE_ENTRIES", "RESUME_ENTRIES", "CLOSE_OWNED_POSITION", "FLATTEN_OWNED_AND_HALT"
]
Version = Annotated[int, Field(strict=True, ge=0)]


class SimulatedScope(FrozenModel):
    actor_id: Identifier
    account: AccountIdentity
    expires_at: Timestamp
    allowed_actions: tuple[Action, ...]


class SimulatedState(FrozenModel):
    account: AccountIdentity
    version: Version
    observed_at: Timestamp
    administrative_pause: bool = True
    loss_pause: bool = False
    integrity_halt: bool = False
    hard_halt: bool = False
    unresolved_orders: bool = False
    inputs_qualified: bool = False
    healthy: bool = False
    quote_at: Timestamp | None = None
    owned_positions: tuple[UUID, ...] = ()

    @model_validator(mode="after")
    def distinct_positions(self):
        if len(set(self.owned_positions)) != len(self.owned_positions):
            raise ValueError("duplicate simulated position")
        return self


class CommandInput(FrozenModel):
    request_id: UUID
    conversation_id: UUID
    account: AccountIdentity
    text: Annotated[str, Field(min_length=1, max_length=512)]
    language: Literal["en", "zh"]
    expires_at: Timestamp
    expected_state_version: Version


class CommandEvaluation(FrozenModel):
    request_id: UUID
    interpretation: Literal["EXPLICIT_COMMAND", "AMBIGUOUS", "UNAUTHORIZED"]
    action: Action | None = None
    position_id: UUID | None = None
    status: Literal["REJECTED", "SIMULATED_APPLIED", "SIMULATED_OUTCOME_UNKNOWN"]
    reason: str
    before: SimulatedState
    after: SimulatedState
    simulation_only: Literal[True] = True
    execution_enabled: Literal[False] = False


def command_text(account: AccountIdentity, action: Action, language: str, position=None) -> str:
    """Exact supported grammar; full account identity, never a dashboard selection."""
    import json

    target = json.dumps(account.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    en = {
        "PAUSE_ENTRIES": f"Pause entries for {target}",
        "RESUME_ENTRIES": f"Resume entries for {target}",
        "CLOSE_OWNED_POSITION": f"Close position {position} for {target}",
        "FLATTEN_OWNED_AND_HALT": f"Flatten owned positions and halt {target}",
    }
    zh = {
        "PAUSE_ENTRIES": f"暂停开仓 {target}",
        "RESUME_ENTRIES": f"恢复开仓 {target}",
        "CLOSE_OWNED_POSITION": f"平仓 {position} 账户 {target}",
        "FLATTEN_OWNED_AND_HALT": f"平掉自有仓位并停止 {target}",
    }
    if language not in ("en", "zh"):
        raise ValueError("unsupported language")
    return (en if language == "en" else zh)[action]


def evaluate(
    scope: SimulatedScope,
    request: CommandInput,
    state: SimulatedState,
    *,
    now: datetime,
    close_confirmed: bool = False,
) -> CommandEvaluation:
    """Fail-closed exact grammar and pure state transition for a test harness.

    close_confirmed is explicitly injected simulated execution evidence, never
    inferred from intent or an ACK. False preserves positions and marks unknown.
    """
    scope = SimulatedScope.model_validate(scope.model_dump(mode="json"))
    request = CommandInput.model_validate(request.model_dump(mode="json"))
    state = SimulatedState.model_validate(state.model_dump(mode="json"))
    now = utc(now)
    if type(close_confirmed) is not bool:
        raise ValueError("simulated confirmation must be boolean")

    def result(
        reason, *, action=None, position=None, after=None, unknown=False, unauthorized=False
    ):
        return CommandEvaluation(
            request_id=request.request_id,
            interpretation="UNAUTHORIZED"
            if unauthorized
            else "EXPLICIT_COMMAND"
            if action
            else "AMBIGUOUS",
            action=action,
            position_id=position,
            before=state,
            after=after or state,
            status="SIMULATED_OUTCOME_UNKNOWN"
            if unknown
            else "SIMULATED_APPLIED"
            if after
            else "REJECTED",
            reason=reason,
        )

    if (
        scope.account != request.account
        or scope.account != state.account
        or state.account.venue != "SIMULATOR"
        or state.account.environment != "PAPER"
        or now >= scope.expires_at
    ):
        return result("SCOPE_DENIED", unauthorized=True)
    if request.expires_at > scope.expires_at or now >= request.expires_at:
        return result("EXPIRED")
    if state.observed_at > now or (now - state.observed_at).total_seconds() > 2:
        return result("STALE_STATE")
    if request.expected_state_version != state.version:
        return result("STATE_VERSION_CONFLICT")
    matches = []
    for action in ("PAUSE_ENTRIES", "RESUME_ENTRIES", "FLATTEN_OWNED_AND_HALT"):
        if request.text == command_text(state.account, action, request.language):
            matches.append((action, None))
    # Closing any other identity, including a non-owned position, cannot resolve.
    for position in state.owned_positions:
        if request.text == command_text(
            state.account, "CLOSE_OWNED_POSITION", request.language, position
        ):
            matches.append(("CLOSE_OWNED_POSITION", position))
    if len(matches) != 1:
        return result("UNSUPPORTED_OR_AMBIGUOUS")
    action, position = matches[0]
    if action not in scope.allowed_actions:
        return result("ACTION_DENIED", action=action, position=position, unauthorized=True)
    changes = {"version": state.version + 1, "observed_at": now}
    if action == "PAUSE_ENTRIES":
        changes["administrative_pause"] = True
    elif action == "RESUME_ENTRIES":
        if (
            state.loss_pause
            or state.integrity_halt
            or state.hard_halt
            or state.unresolved_orders
            or not state.inputs_qualified
            or not state.healthy
            or state.quote_at is None
            or not 0 <= (now - state.quote_at).total_seconds() <= 2
        ):
            return result("RESUME_GATES_FAILED", action=action)
        changes["administrative_pause"] = False
    else:
        if action == "FLATTEN_OWNED_AND_HALT":
            changes.update(administrative_pause=True, hard_halt=True)
        if state.unresolved_orders or not close_confirmed:
            changes["unresolved_orders"] = True
            return result(
                "NO_CONFIRMED_CLOSE",
                action=action,
                position=position,
                after=state.model_copy(update=changes),
                unknown=True,
            )
        changes["owned_positions"] = (
            () if position is None else tuple(p for p in state.owned_positions if p != position)
        )
    return result(
        "SIMULATION_ONLY", action=action, position=position, after=state.model_copy(update=changes)
    )


def evaluate_and_record(repository, scope, request, state, *, now, close_confirmed=False):
    """Append a simulation request/result pair once; never execute its proposed state.

    This is an evaluation journal, not the gateway's authoritative state store.
    Restart replay returns the original result, including unknown outcomes.
    """
    import json
    from uuid import uuid5

    import psycopg

    from fx_talanta.domain.models import ConversationMessage, EvidenceLink, Record, Versions
    from fx_talanta.storage.repository import RecordConflict

    scope = SimulatedScope.model_validate(scope.model_dump(mode="json"))
    request = CommandInput.model_validate(request.model_dump(mode="json"))
    now = utc(now)
    if (
        repository.account != scope.account
        or scope.account != request.account
        or scope.account.venue != "SIMULATOR"
        or scope.account.environment != "PAPER"
        or now >= scope.expires_at
    ):
        raise PermissionError("simulator journal scope denied")
    identity = json.dumps(
        {
            "request": request.model_dump(mode="json"),
            "actor": scope.actor_id,
            "actions": sorted(scope.allowed_actions),
        },
        sort_keys=True,
    )
    request_id = uuid5(request.request_id, "command-simulation/request/1")
    result_id = uuid5(request.request_id, "command-simulation/result/1")
    with psycopg.connect(repository._dsn) as conn:
        conn.execute("SELECT pg_advisory_xact_lock(%s)", (640042,))
        repository._check_binding(conn)
        rows = conn.execute(
            "SELECT payload FROM fx.records WHERE record_id IN (%s,%s)", (request_id, result_id)
        ).fetchall()
        if rows:
            saved = {r.record_id: r for r in (Record.model_validate(row[0]) for row in rows)}
            if (
                set(saved) != {request_id, result_id}
                or saved[request_id].body.kind != "message"
                or saved[result_id].body.kind != "message"
                or saved[request_id].body.text != identity
                or any(
                    r.account != repository.account or r.recorded_at > now for r in saved.values()
                )
            ):
                raise RecordConflict("simulation request identity conflict")
            return CommandEvaluation.model_validate_json(saved[result_id].body.text)
        outcome = evaluate(scope, request, state, now=now, close_confirmed=close_confirmed)

        def message(rid, role, text, refs=()):
            return Record(
                record_id=rid,
                account=repository.account,
                recorded_at=now,
                correlation_id=request.conversation_id,
                provenance="OFFLINE_SIMULATION",
                versions=Versions(component="m4-command-simulation/1", model="none", prompt="none"),
                references=refs,
                body=ConversationMessage(
                    conversation_id=request.conversation_id,
                    message_id=rid,
                    actor_id=scope.actor_id,
                    authenticated=False,
                    role=role,
                    language=request.language,
                    text=text,
                    interpretation="READ_ONLY",
                ),
            )

        repository.append_in(
            conn,
            (
                message(request_id, "USER", identity),
                message(
                    result_id,
                    "ADVISOR",
                    outcome.model_dump_json(),
                    (EvidenceLink(record_id=request_id, relation="MESSAGE"),),
                ),
            ),
        )
    return outcome
