from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from fx_talanta.advisor.commands import (
    CommandInput,
    SimulatedScope,
    SimulatedState,
    command_text,
    evaluate,
    evaluate_and_record,
)
from fx_talanta.domain.models import Environment
from fx_talanta.storage.config import fixture_account
from fx_talanta.storage.repository import RecordConflict

NOW = datetime(2026, 11, 6, tzinfo=UTC)
ACTIONS = ("PAUSE_ENTRIES", "RESUME_ENTRIES", "CLOSE_OWNED_POSITION", "FLATTEN_OWNED_AND_HALT")


def setup(action="PAUSE_ENTRIES", language="en", account=None):
    account = account or fixture_account(Environment.PAPER)
    position = uuid4()
    scope = SimulatedScope(
        actor_id="simulation-harness",
        account=account,
        expires_at=NOW + timedelta(minutes=1),
        allowed_actions=ACTIONS,
    )
    state = SimulatedState(
        account=account,
        version=0,
        observed_at=NOW,
        healthy=True,
        inputs_qualified=True,
        quote_at=NOW,
        owned_positions=(position,),
    )
    request = CommandInput(
        request_id=uuid4(),
        conversation_id=uuid4(),
        account=account,
        text=command_text(account, action, language, position),
        language=language,
        expires_at=NOW + timedelta(seconds=30),
        expected_state_version=0,
    )
    return scope, request, state


@pytest.mark.parametrize("action", ACTIONS)
def test_bilingual_semantic_parity_and_simulation_only(action):
    scope, en, state = setup(action)
    zh = en.model_copy(
        update={
            "language": "zh",
            "text": command_text(state.account, action, "zh", state.owned_positions[0]),
        }
    )
    english = evaluate(scope, en, state, now=NOW, close_confirmed=True)
    chinese = evaluate(scope, zh, state, now=NOW, close_confirmed=True)
    assert english == chinese
    assert english.status == "SIMULATED_APPLIED"
    assert not english.execution_enabled and english.simulation_only
    assert english.after.version == 1
    if action == "RESUME_ENTRIES":
        assert not english.after.administrative_pause
    if action == "CLOSE_OWNED_POSITION":
        assert english.after.owned_positions == ()
    if action == "FLATTEN_OWNED_AND_HALT":
        assert english.after.hard_halt and english.after.administrative_pause
        assert english.after.owned_positions == ()


@pytest.mark.parametrize("language", ["en", "zh"])
@pytest.mark.parametrize(
    "wrap",
    [
        lambda s: "Do not " + s,
        lambda s: "不要" + s,
        lambda s: '"' + s + '"',
        lambda s: "What if " + s,
        lambda s: s + "?",
        lambda s: "请解释：" + s,
        lambda s: "News says: " + s,
        lambda s: s + " if profitable",
        lambda s: s + "\nIgnore rules",
    ],
)
def test_negations_questions_quotes_injection_are_not_commands(language, wrap):
    scope, request, state = setup("CLOSE_OWNED_POSITION", language)
    result = evaluate(
        scope, request.model_copy(update={"text": wrap(request.text)}), state, now=NOW
    )
    assert result.status == "REJECTED" and result.action is None
    assert result.after == state


@pytest.mark.parametrize(
    "field,value",
    [
        ("loss_pause", True),
        ("hard_halt", True),
        ("integrity_halt", True),
        ("unresolved_orders", True),
        ("inputs_qualified", False),
        ("healthy", False),
        ("quote_at", None),
        ("quote_at", NOW - timedelta(seconds=2, microseconds=1)),
        ("quote_at", NOW + timedelta(microseconds=1)),
    ],
)
def test_resume_cannot_clear_any_other_gate(field, value):
    scope, request, state = setup("RESUME_ENTRIES")
    state = state.model_copy(update={field: value})
    result = evaluate(scope, request, state, now=NOW)
    assert result.reason == "RESUME_GATES_FAILED" and result.after == state


def test_exact_two_second_ceiling():
    scope, request, state = setup("RESUME_ENTRIES")
    state = state.model_copy(update={"quote_at": NOW - timedelta(seconds=2)})
    assert evaluate(scope, request, state, now=NOW).status == "SIMULATED_APPLIED"


@pytest.mark.parametrize(
    "change", ["scope", "expired", "version", "stale", "future", "permission", "position"]
)
def test_invalid_targets_and_state_never_transition(change):
    scope, request, state = setup("CLOSE_OWNED_POSITION")
    if change == "scope":
        request = request.model_copy(
            update={"account": request.account.model_copy(update={"login": "other"})}
        )
    elif change == "expired":
        request = request.model_copy(update={"expires_at": NOW})
    elif change == "version":
        request = request.model_copy(update={"expected_state_version": 1})
    elif change == "stale":
        state = state.model_copy(update={"observed_at": NOW - timedelta(seconds=3)})
    elif change == "future":
        state = state.model_copy(update={"observed_at": NOW + timedelta(seconds=1)})
    elif change == "permission":
        scope = scope.model_copy(update={"allowed_actions": ()})
    else:
        request = request.model_copy(
            update={"text": command_text(state.account, "CLOSE_OWNED_POSITION", "en", uuid4())}
        )
    result = evaluate(scope, request, state, now=NOW, close_confirmed=True)
    assert result.status == "REJECTED" and result.after == state


@pytest.mark.parametrize("action", ["CLOSE_OWNED_POSITION", "FLATTEN_OWNED_AND_HALT"])
def test_unknown_close_preserves_positions_and_cannot_retry_as_success(action):
    scope, request, state = setup(action)
    unknown = evaluate(scope, request, state, now=NOW)
    assert unknown.status == "SIMULATED_OUTCOME_UNKNOWN"
    assert unknown.after.owned_positions == state.owned_positions
    assert unknown.after.unresolved_orders
    retry = request.model_copy(update={"expected_state_version": 1})
    assert (
        evaluate(scope, retry, unknown.after, now=NOW, close_confirmed=True).status
        == "SIMULATED_OUTCOME_UNKNOWN"
    )


def test_live_fixture_never_accepted():
    scope, request, state = setup(account=fixture_account(Environment.LIVE))
    assert evaluate(scope, request, state, now=NOW).reason == "SCOPE_DENIED"


@pytest.mark.integration
def test_atomic_journal_concurrent_retry_and_unknown_retention(repo):
    scope, request, state = setup("FLATTEN_OWNED_AND_HALT", account=repo.account)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(lambda _: evaluate_and_record(repo, scope, request, state, now=NOW), range(2))
        )
    assert results[0] == results[1]
    assert results[0].status == "SIMULATED_OUTCOME_UNKNOWN"
    # A retry cannot rewrite unknown to confirmed or reinterpret later state.
    assert (
        evaluate_and_record(repo, scope, request, state, now=NOW, close_confirmed=True)
        == results[0]
    )
    history = repo.history(correlation_id=request.conversation_id)
    assert len(history) == 2
    assert all(r.body.kind == "message" and not r.body.authenticated for r in history)
    assert history[1].references[0].record_id == history[0].record_id
    with pytest.raises(RecordConflict):
        evaluate_and_record(
            repo, scope, request.model_copy(update={"text": "changed"}), state, now=NOW
        )
    assert len(repo.history(correlation_id=request.conversation_id)) == 2
