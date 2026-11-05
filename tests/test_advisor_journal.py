from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4, uuid5

import pytest
from psycopg.errors import UniqueViolation
from pydantic import ValidationError

from fx_talanta.advisor.evidence import EvidenceQuery, ReadGrant
from fx_talanta.advisor.journal import read_and_record
from fx_talanta.domain.models import AccountIdentity, Record, RiskEvaluation
from fx_talanta.storage.repository import RecordConflict

NOW = datetime(2026, 11, 5, tzinfo=UTC)


class MemoryStore:
    """Test double; PostgreSQL integration below tests actual durable behavior."""

    def __init__(self, account, records=()):
        self.account = account
        self.records = {r.record_id: r for r in records}
        self.writes = 0
        self.fail = False

    def get(self, rid):
        return self.records[rid]

    def append_batch(self, records):
        if self.fail:
            raise OSError("fixture storage outage")
        self.writes += 1
        for r in records:
            if r.record_id in self.records and self.records[r.record_id] != r:
                raise RecordConflict("conflict")
        self.records.update({r.record_id: r for r in records})


def setup(account=None):
    account = account or AccountIdentity(
        environment="PAPER", broker="fixture", server="offline", login="fixture", venue="SIMULATOR"
    )
    source = Record(
        account=account,
        recorded_at=NOW,
        correlation_id=uuid4(),
        body=RiskEvaluation(
            approved=False,
            reasons=("untrusted trade instruction",),
            checked_limits=("fixture",),
            proposed_volume="0",
            planned_loss="0",
        ),
    )
    grant = ReadGrant(
        actor_id="offline-owner", account=account, expires_at=NOW + timedelta(minutes=5)
    )
    query = EvidenceQuery(account=account, as_of=NOW, record_ids=(source.record_id,))
    kwargs = dict(conversation_id=uuid4(), request_id=uuid4(), now=NOW, language="zh")
    return source, grant, query, kwargs


def test_atomic_messages_exact_receipt_and_restart_retry():
    source, grant, query, kwargs = setup()
    store = MemoryStore(source.account, (source,))
    answer = read_and_record(store, grant, query, **kwargs)
    assert len(store.records) == 3
    assert all(r.body.kind != "command" for r in store.records.values())
    assert all(not r.body.authenticated for r in store.records.values() if r.body.kind == "message")
    assert "untrusted" not in answer.model_dump_json()
    restarted = MemoryStore(source.account, store.records.values())
    retry = read_and_record(
        restarted, grant, query, **(kwargs | {"now": NOW + timedelta(seconds=1)})
    )
    assert retry == answer
    assert restarted.writes == 0
    assert store.records[source.record_id] == source


@pytest.mark.parametrize("change", ["actor", "query", "conversation", "language", "expiry"])
def test_retry_rejects_changed_identity_or_expired_access(change):
    source, grant, query, kwargs = setup()
    store = MemoryStore(source.account, (source,))
    read_and_record(store, grant, query, **kwargs)
    if change == "actor":
        grant = grant.model_copy(update={"actor_id": "other"})
    elif change == "query":
        query = query.model_copy(update={"as_of": NOW - timedelta(seconds=1)})
    elif change == "conversation":
        kwargs["conversation_id"] = uuid4()
    elif change == "language":
        kwargs["language"] = "en"
    else:
        kwargs["now"] = grant.expires_at
    with pytest.raises((RecordConflict, PermissionError)):
        read_and_record(store, grant, query, **kwargs)
    assert store.writes == 1


def test_missing_evidence_receipt_remains_original_after_later_arrival():
    source, grant, query, kwargs = setup()
    store = MemoryStore(source.account)
    original = read_and_record(store, grant, query, **kwargs)
    assert original.unavailable == (source.record_id,)
    store.records[source.record_id] = source
    assert read_and_record(store, grant, query, **kwargs) == original


def test_outage_and_oversized_receipt_do_not_write():
    source, grant, query, kwargs = setup()
    store = MemoryStore(source.account, (source,))
    store.fail = True
    with pytest.raises(OSError):
        read_and_record(store, grant, query, **kwargs)
    assert len(store.records) == 1
    store.fail = False
    records = [setup(source.account)[0] for _ in range(20)]
    store.records.update({r.record_id: r for r in records})
    query = query.model_copy(update={"record_ids": tuple(r.record_id for r in records)})
    with pytest.raises(ValidationError):
        read_and_record(store, grant, query, **kwargs)
    assert store.writes == 0


def test_partial_receipt_rejected():
    source, grant, query, kwargs = setup()
    store = MemoryStore(source.account, (source,))
    read_and_record(store, grant, query, **kwargs)
    del store.records[uuid5(kwargs["request_id"], "advisor/answer/1")]
    with pytest.raises(RecordConflict):
        read_and_record(store, grant, query, **kwargs)
    assert store.writes == 1


@pytest.mark.parametrize("constraint", ["message_identity", "unrelated_unique_index"])
def test_secondary_unique_constraint_requires_verified_winner(constraint):
    class Race(UniqueViolation):
        @property
        def diag(self):
            return SimpleNamespace(constraint_name=constraint)

    class RacingStore(MemoryStore):
        def append_batch(self, records):
            # Represents a winner committed by another caller, not a partial write.
            super().append_batch(records)
            raise Race("fixture concurrent winner")

    source, grant, query, kwargs = setup()
    store = RacingStore(source.account, (source,))
    if constraint == "message_identity":
        result = read_and_record(store, grant, query, **kwargs)
        assert len(result.citations) == 1
        assert len(store.records) == 3
    else:
        with pytest.raises(UniqueViolation):
            read_and_record(store, grant, query, **kwargs)


@pytest.mark.integration
def test_postgres_receipt_restart_and_no_execution(repo):
    source, grant, query, kwargs = setup(repo.account)
    repo.append(source)
    first = read_and_record(repo, grant, query, **kwargs)
    from fx_talanta.storage.repository import Repository

    restarted = Repository(repo._dsn, repo.account)
    second = read_and_record(
        restarted, grant, query, **(kwargs | {"now": NOW + timedelta(seconds=1)})
    )
    assert first == second
    history = repo.history(correlation_id=kwargs["conversation_id"])
    assert len(history) == 2
    assert all(r.body.kind == "message" and not r.body.authenticated for r in history)
    assert not first.execution_enabled
    assert repo.get(source.record_id) == source


@pytest.mark.integration
def test_postgres_concurrent_delivery_commits_one_pair(repo):
    from concurrent.futures import ThreadPoolExecutor

    source, grant, query, kwargs = setup(repo.account)
    repo.append(source)

    def call(offset):
        return read_and_record(
            repo, grant, query, **(kwargs | {"now": NOW + timedelta(milliseconds=offset)})
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(call, (0, 0)))
    assert results[0] == results[1]
    assert len(repo.history(correlation_id=kwargs["conversation_id"])) == 2
