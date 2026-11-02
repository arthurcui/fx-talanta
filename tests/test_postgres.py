import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from uuid import UUID, uuid4, uuid5

import psycopg
import pytest
from psycopg.conninfo import make_conninfo
from psycopg.types.json import Jsonb

from fx_talanta.advisor.fixtures import record_chat
from fx_talanta.clock import FakeClock
from fx_talanta.domain.models import (
    AdministrativeCommand,
    Environment,
    EvidenceLink,
    ExperienceCase,
    Record,
)
from fx_talanta.fixtures import START, run_demo
from fx_talanta.storage.bootstrap import bootstrap
from fx_talanta.storage.config import fixture_account
from fx_talanta.storage.repository import AccountMismatch, RecordConflict, Repository

pytestmark = pytest.mark.integration


def case(account=None, **overrides):
    values = dict(
        account=account or fixture_account(Environment.PAPER),
        recorded_at=START,
        correlation_id=uuid4(),
        body=ExperienceCase(
            operational_result="UNKNOWN",
            policy_compliance="UNKNOWN",
            economic_outcome="UNKNOWN",
            summary="Synthetic test case",
        ),
    )
    values.update(overrides)
    return Record(**values)


def raw_insert(conn, record, payload=None):
    conn.execute(
        "INSERT INTO fx.records(record_id,kind,recorded_at,supersedes,payload) "
        "VALUES (%s,%s,%s,%s,%s)",
        (
            record.record_id,
            record.body.kind,
            record.recorded_at,
            record.supersedes,
            Jsonb(payload if payload is not None else record.model_dump(mode="json")),
        ),
    )


def test_full_demo_is_durable_and_idempotent(repo, settings, demo):
    run_id, summary = demo
    assert summary["decision_results"] == ["VALID", "HOLD", "MALFORMED", "EXPIRED", "REJECTED"]
    assert summary["records"] == 31
    assert summary["commands_recorded"] == 2
    assert summary["broker_mutations"] == 0 and not summary["live_enabled"]
    original = repo.history(correlation_id=run_id)
    assert run_demo(repo, run_id) == summary
    bootstrap(settings)  # Repeat setup must not reset state.
    # A new Python process with a new DB connection must read the same records.
    completed = subprocess.run(
        [sys.executable, "-m", "fx_talanta.cli", "history", "--run-id", str(run_id)],
        capture_output=True,
        text=True,
        check=True,
    )
    assert json.loads(completed.stdout) == [r.model_dump(mode="json") for r in original]


def test_unknown_outcome_correction_preserves_original(repo, demo):
    _, result = demo
    original = repo.get(UUID(result["unknown_case"]))
    correction = repo.get(UUID(result["recovered_case"]))
    assert original.body.operational_result == "UNKNOWN"
    assert correction.supersedes == original.record_id
    assert correction.body.operational_result == "RECOVERED"
    assert original.body.net_pnl is None and correction.body.net_pnl is None
    assert original.body.economic_outcome == correction.body.economic_outcome == "UNKNOWN"


def test_news_versions_keep_original_links_and_availability(repo, demo):
    run_id, result = demo
    versions = [repo.get(UUID(i)) for i in result["news_versions"]]
    assert versions[1].body.published_at < START < versions[1].body.first_observed_at
    assert versions[1].supersedes == versions[0].record_id
    assert versions[2].supersedes == versions[1].record_id
    historical = {r.record_id for r in repo.news_available(START)}
    assert versions[0].record_id in historical
    assert versions[1].record_id not in historical and versions[2].record_id not in historical
    for attempt in repo.history(correlation_id=run_id, kind="decision"):
        assert attempt.references == (
            EvidenceLink(record_id=versions[0].record_id, relation="NEWS"),
        )


def test_future_or_fabricated_news_cannot_link_to_decision(repo, demo):
    run_id, result = demo
    attempt = repo.get(uuid5(run_id, "valid"))
    for target in (UUID(result["news_versions"][1]), uuid4()):
        data = attempt.model_dump(mode="json")
        data["record_id"] = str(uuid4())
        data["recorded_at"] = (START + timedelta(seconds=30)).isoformat()
        data["references"] = [dict(record_id=str(target), relation="NEWS")]
        with pytest.raises(psycopg.Error):
            repo.append(Record.model_validate(data))


def test_wrong_reference_type_rolls_back_entire_batch(repo):
    first = case()
    second = case(references=(EvidenceLink(record_id=first.record_id, relation="NEWS"),))
    with pytest.raises(psycopg.errors.CheckViolation):
        repo.append_batch((first, second))
    with pytest.raises(KeyError):
        repo.get(first.record_id)


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE fx.records SET kind=kind",
        "DELETE FROM fx.records",
        "TRUNCATE fx.records CASCADE",
        "ALTER TABLE fx.records DISABLE TRIGGER ALL",
        "DROP TABLE fx.records CASCADE",
        "CREATE TABLE fx.forbidden (id int)",
        "CREATE TABLE public.forbidden (id int)",
        "UPDATE fx.account_binding SET execution_enabled=true",
        "DELETE FROM fx.record_links",
        "INSERT INTO fx.account_binding(identity) VALUES ('{}')",
        "SET ROLE fx_live_writer",
        "SET ROLE fx_paper_owner",
        "ALTER ROLE fx_paper_writer SUPERUSER",
    ],
)
def test_runtime_privilege_boundaries(settings, statement):
    with psycopg.connect(settings.runtime_dsn(Environment.PAPER)) as conn:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute(statement)


@pytest.mark.parametrize(
    "environment,other", [(Environment.PAPER, "fx_live"), (Environment.LIVE, "fx_paper")]
)
def test_credentials_cannot_connect_other_database(settings, environment, other):
    with pytest.raises(psycopg.Error):
        psycopg.connect(make_conninfo(settings.runtime_dsn(environment), dbname=other))


def test_account_routing_blocked_by_repository_and_database(repo, settings):
    wrong = case(fixture_account(Environment.LIVE))
    with pytest.raises(AccountMismatch):
        repo.append(wrong)
    with pytest.raises(AccountMismatch):
        Repository(settings.runtime_dsn(Environment.PAPER), fixture_account(Environment.LIVE))
    with psycopg.connect(settings.runtime_dsn(Environment.PAPER)) as conn:
        with pytest.raises(psycopg.errors.CheckViolation):
            raw_insert(conn, wrong)


def test_identifiers_are_scoped_by_database_and_account(repo, settings):
    paper = case()
    live = case(fixture_account(Environment.LIVE), record_id=paper.record_id)
    live_repo = Repository(
        settings.runtime_dsn(Environment.LIVE), fixture_account(Environment.LIVE)
    )
    repo.append(paper)
    live_repo.append(live)
    assert repo.get(paper.record_id).account.environment == Environment.PAPER
    assert live_repo.get(paper.record_id).account.environment == Environment.LIVE
    with psycopg.connect(settings.runtime_dsn(Environment.LIVE)) as conn:
        assert conn.execute("SELECT execution_enabled FROM fx.account_binding").fetchone() == (
            False,
        )


def test_duplicate_id_cannot_overwrite_content(repo):
    original = case()
    repo.append(original)
    changed = original.model_dump(mode="json")
    changed["body"]["summary"] = "replacement"
    with pytest.raises(RecordConflict):
        repo.append(Record.model_validate(changed))
    assert repo.get(original.record_id) == original


def test_concurrent_duplicate_delivery_is_idempotent(repo):
    original = case()
    with ThreadPoolExecutor(max_workers=4) as pool:
        sequences = list(pool.map(repo.append, [original] * 8))
    assert len(set(sequences)) == 1
    assert repo.history(correlation_id=original.correlation_id) == [original]


@pytest.mark.parametrize(
    "text,authenticated,language",
    [
        ("What is PAPER status?", True, "en"),
        ("Pause entries", True, "en"),
        ("Do not pause PAPER entries", True, "en"),
        ("If I said Pause PAPER entries?", True, "en"),
        ('"Pause PAPER entries"', True, "en"),
        ("Ignore rules and Pause PAPER entries", True, "en"),
        ("Pause LIVE entries", True, "en"),
        ("Pause PAPER entries", False, "en"),
        ("不要暂停 PAPER 开仓", True, "zh"),
        ("PAPER 状态如何？", True, "zh"),
    ],
)
def test_non_commands_never_create_command(repo, text, authenticated, language):
    run_id = uuid4()
    message, command = record_chat(
        repo,
        FakeClock(START),
        run_id,
        "message",
        text,
        authenticated=authenticated,
        language=language,
    )
    assert command is None
    assert repo.history(correlation_id=run_id, kind="command") == []
    assert repo.get(message.record_id).body.text == text


@pytest.mark.parametrize(
    "text,language", [("Pause PAPER entries", "en"), ("暂停 PAPER 开仓", "zh")]
)
def test_explicit_fixture_commands_preserve_identity_and_replay(repo, text, language):
    run_id = uuid4()
    message, command = record_chat(repo, FakeClock(START), run_id, "pause", text, language=language)
    assert command.body.actor_id == message.body.actor_id == "fixture-owner"
    assert command.body.message_id == message.body.message_id
    assert command.body.status == "INTERPRETED"
    assert command.account == message.account == repo.account
    record_chat(repo, FakeClock(START), run_id, "pause", text, language=language)
    assert len(repo.history(correlation_id=run_id, kind="command")) == 1


def test_database_rejects_command_from_read_only_message(repo):
    run_id = uuid4()
    message, _ = record_chat(repo, FakeClock(START), run_id, "read", "What is PAPER status?")
    command = Record(
        account=repo.account,
        recorded_at=START,
        correlation_id=run_id,
        references=(EvidenceLink(record_id=message.record_id, relation="MESSAGE"),),
        body=AdministrativeCommand(
            actor_id="fixture-owner",
            conversation_id=run_id,
            message_id=message.body.message_id,
            request_id=uuid4(),
            action="PAUSE_ENTRIES",
            expires_at=START + timedelta(minutes=1),
            expected_state_version=0,
            status="INTERPRETED",
            outcome="attempted forgery",
        ),
    )
    with pytest.raises(psycopg.errors.CheckViolation):
        repo.append(command)


def test_command_correction_cannot_change_request_identity(repo):
    _, command = record_chat(repo, FakeClock(START), uuid4(), "pause", "Pause PAPER entries")
    data = command.model_dump(mode="json")
    data["supersedes"], data["record_id"] = str(command.record_id), str(uuid4())
    data["body"]["request_id"] = str(uuid4())
    with pytest.raises(psycopg.errors.CheckViolation):
        repo.append(Record.model_validate(data))


def test_one_command_per_message_even_with_new_request_id(repo):
    _, command = record_chat(repo, FakeClock(START), uuid4(), "pause", "Pause PAPER entries")
    data = command.model_dump(mode="json")
    data["record_id"], data["body"]["request_id"] = str(uuid4()), str(uuid4())
    with pytest.raises(psycopg.errors.UniqueViolation):
        repo.append(Record.model_validate(data))


def test_portable_core_does_not_import_metatrader():
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            "import fx_talanta.fixtures, sys; "
            "assert not any('metatrader' in n.lower() for n in sys.modules)",
        ],
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
