import multiprocessing
from dataclasses import replace
from uuid import uuid4

import psycopg
import pytest
from psycopg.conninfo import make_conninfo

from fx_talanta.connected_shadow.authority import (
    Authority,
    PairCheckpoint,
    PeerCheckpoint,
    PostgresAuthorityStore,
    backend_checkpoint,
)
from fx_talanta.domain.models import AccountIdentity, Environment
from fx_talanta.shadow.backend import Backend
from fx_talanta.shadow.client import Client
from fx_talanta.shadow.store import PostgresStore, SQLiteStore
from fx_talanta.shadow.wire import digest
from fx_talanta.shadow.work import scope_for
from fx_talanta.storage.bootstrap import bootstrap
from fx_talanta.storage.config import fixture_account
from tools.fixtures.shadow_fixtures import ACCOUNT, CLIENT, KEY, NOW, POLICY, RELEASE, work

INCARNATION = "1" * 64
OTHER = "2" * 64


def paired(scope, *, acknowledged=True):
    return PairCheckpoint.match(
        PeerCheckpoint(scope, "a" * 64, 1, "c" * 64),
        PeerCheckpoint(scope, "b" * 64, 1, "c" * 64, acknowledged),
    )


@pytest.fixture
def authority(tmp_path):
    return Authority(
        SQLiteStore(tmp_path / "authority.db", bootstrap=True), ACCOUNT, bootstrap=True
    )


def test_active_owner_is_exclusive_and_survives_process_object_restart(authority):
    lease = authority.claim(CLIENT, INCARNATION, NOW)
    resumed = Authority(authority.store, ACCOUNT, expected_tip=authority.tip())
    assert resumed.check(CLIENT, INCARNATION, lease.epoch, NOW + 1) == lease
    for client, incarnation, epoch in (
        (OTHER, INCARNATION, 1),
        (CLIENT, OTHER, 1),
        (CLIENT, INCARNATION, 2),
    ):
        with pytest.raises(ValueError, match="NOT_AUTHORITY_OWNER"):
            resumed.check(client, incarnation, epoch, NOW + 2)
    with pytest.raises(ValueError, match="EXPLICIT_RETIREMENT_REQUIRED"):
        resumed.claim(CLIENT, INCARNATION, NOW + 3)
    with pytest.raises(ValueError, match="EXPLICIT_RETIREMENT_REQUIRED"):
        resumed.claim(OTHER, OTHER, NOW + 30000)
    with pytest.raises(ValueError, match="LEASE_EXPIRED"):
        resumed.renew(CLIENT, INCARNATION, 1, NOW + 30000)


def test_renewal_deadline_and_clock_regression_do_not_reset_authority(authority):
    lease = authority.claim(CLIENT, INCARNATION, NOW, lease_ms=1000)
    lease = authority.renew(CLIENT, INCARNATION, lease.epoch, NOW + 500)
    assert lease.expires_ms == NOW + 15500
    with pytest.raises(ValueError, match="CLOCK_REGRESSION"):
        authority.check(CLIENT, INCARNATION, 1, NOW + 499)
    with pytest.raises(ValueError, match="LEASE_EXPIRED"):
        authority.check(CLIENT, INCARNATION, 1, lease.expires_ms)
    with pytest.raises(ValueError, match="INVALID_LEASE_DURATION"):
        authority.renew(CLIENT, INCARNATION, 1, NOW + 501, lease_ms=86400000)


def test_guard_holds_authority_and_rejects_operation_that_crosses_deadline(authority):
    authority.claim(CLIENT, INCARNATION, NOW, lease_ms=1000)
    clock = iter((NOW + 999, NOW + 1000))
    with pytest.raises(ValueError, match="LEASE_EXPIRED"):
        with authority.guard(CLIENT, INCARNATION, 1, lambda: next(clock)):
            pass
    with authority.store.transaction() as events:
        assert [r["kind"] for r in events.records] == ["binding", "claim"]
    with authority.guard(CLIENT, INCARNATION, 1, lambda: NOW + 900):
        pass
    with pytest.raises(ValueError, match="CLOCK_REGRESSION"):
        authority.check(CLIENT, INCARNATION, 1, NOW + 899)


def test_retirement_requires_both_peers_and_preserves_unacknowledged_receipt(authority):
    authority.claim(CLIENT, INCARNATION, NOW)
    checkpoint = paired(authority.scope, acknowledged=False)
    with pytest.raises(ValueError, match="PAIRED_RETIRED_SOURCE_REQUIRED"):
        authority.retire(CLIENT, INCARNATION, 1, NOW + 1, checkpoint=checkpoint)
    with pytest.raises(ValueError, match="PEER_CHECKPOINT_MISMATCH"):
        PairCheckpoint.match(checkpoint.backend, replace(checkpoint.native, receipt_hash=OTHER))
    with pytest.raises(ValueError, match="PEER_CHECKPOINT_MISMATCH"):
        PairCheckpoint.match(checkpoint.backend, replace(checkpoint.native, sequence=2))
    with pytest.raises(ValueError, match="PEER_CHECKPOINT_MISMATCH"):
        PairCheckpoint.match(checkpoint.backend, replace(checkpoint.native, scope=OTHER))
    authority.retire(
        CLIENT, INCARNATION, 1, NOW + 20000, checkpoint=checkpoint, source_retired=True
    )
    tip = authority.tip()
    assert authority.verify_restore(checkpoint, expected_tip=tip)
    with pytest.raises(ValueError, match="AUTHORITY_CHECKPOINT_CONFLICT"):
        authority.verify_restore(checkpoint, expected_tip=OTHER)
    with pytest.raises(ValueError, match="RESTORE_CHECKPOINT_MISMATCH"):
        authority.verify_restore(paired(authority.scope), expected_tip=tip)
    with pytest.raises(ValueError, match="HANDOFF_CHECKPOINT_MISMATCH"):
        authority.claim(OTHER, OTHER, NOW + 20001)
    with pytest.raises(ValueError, match="HANDOFF_CHECKPOINT_MISMATCH"):
        authority.claim(CLIENT, INCARNATION, NOW + 20001, checkpoint=checkpoint)
    next_lease = authority.claim(OTHER, OTHER, NOW + 20001, checkpoint=checkpoint)
    assert next_lease.epoch == 2
    with authority.store.transaction() as events:
        retired = next(r for r in events.records if r["kind"] == "retire")
        assert retired["checkpoint"]["native"]["acknowledged"] is False


def test_missing_or_rolled_back_authority_cannot_bootstrap_implicitly(authority, tmp_path):
    before = authority.tip()
    authority.claim(CLIENT, INCARNATION, NOW)
    with pytest.raises(ValueError, match="AUTHORITY_CHECKPOINT_CONFLICT"):
        Authority(authority.store, ACCOUNT, expected_tip=before)
    with pytest.raises(ValueError, match="AUTHORITY_BINDING_CONFLICT"):
        Authority(authority.store, ACCOUNT.model_copy(update={"login": "different"}))
    empty = SQLiteStore(tmp_path / "empty.db", bootstrap=True)
    with pytest.raises(ValueError, match="MISSING_AUTHORITY"):
        Authority(empty, ACCOUNT)
    with pytest.raises(ValueError, match="MISSING_AUTHORITY"):
        Authority(empty, ACCOUNT, bootstrap=True, expected_tip=before)
    with pytest.raises(ValueError, match="PAPER_REQUIRED"):
        Authority(authority.store, fixture_account(Environment.LIVE))


def test_expired_owner_can_recover_stable_receipt_but_cannot_pull_or_renew(authority, tmp_path):
    backend = Backend(
        SQLiteStore(tmp_path / "backend.db", bootstrap=True),
        ACCOUNT,
        CLIENT,
        RELEASE,
        POLICY,
        KEY,
        bootstrap=True,
    )
    client = Client(
        SQLiteStore(tmp_path / "client.db", bootstrap=True),
        scope_for(ACCOUNT),
        CLIENT,
        RELEASE,
        POLICY,
        KEY,
        bootstrap=True,
    )
    authority.claim(CLIENT, INCARNATION, NOW, lease_ms=1000)
    backend.publish(*work(), NOW)

    def pull(raw):
        with authority.guard(CLIENT, INCARNATION, 1, lambda: NOW):
            return backend.exchange(raw, NOW)

    assert client.step(pull, lambda: NOW) == "WORK"
    with client.store.transaction() as events:
        receipt = next(r["receipt"] for r in events.records if r["kind"] == "receipt")

    def report(raw):
        with authority.guard_receipt(CLIENT, INCARNATION, 1, lambda: NOW + 30000):
            return backend.exchange(raw, NOW + 30000)

    assert client.step(report, lambda: NOW + 30000) == "ACK"
    with backend.store.transaction() as events:
        assert [r["receipt"] for r in events.records if r["kind"] == "receipt"] == [receipt]
    with pytest.raises(ValueError, match="LEASE_EXPIRED"):
        authority.check(CLIENT, INCARNATION, 1, NOW + 30000)
    with pytest.raises(ValueError, match="LEASE_EXPIRED"):
        authority.renew(CLIENT, INCARNATION, 1, NOW + 30000)
    checkpoint = paired(authority.scope)
    authority.retire(
        CLIENT, INCARNATION, 1, NOW + 30001, checkpoint=checkpoint, source_retired=True
    )
    authority.claim(OTHER, OTHER, NOW + 30002, checkpoint=checkpoint)
    with pytest.raises(ValueError, match="NOT_AUTHORITY_OWNER"):
        with authority.guard_receipt(CLIENT, INCARNATION, 1, lambda: NOW + 30003):
            pytest.fail("retired owner reached receipt ingestion")


def _claim_process(dsn, account_json, client, incarnation, gate, queue):
    try:
        account = AccountIdentity.model_validate(account_json)
        current = Authority(PostgresAuthorityStore(dsn, account), account)
        if not gate.wait(10):
            raise TimeoutError
        lease = current.claim(client, incarnation, NOW)
        queue.put(("CLAIMED", lease.epoch))
    except ValueError as error:
        queue.put((str(error), 0))
    except Exception as error:
        queue.put((type(error).__name__, 0))


def _guard_process(dsn, account_json, ready):
    import time

    account = AccountIdentity.model_validate(account_json)
    current = Authority(PostgresAuthorityStore(dsn, account), account)
    with current.guard(CLIENT, INCARNATION, 1, lambda: NOW + 1):
        ready.send(True)
        ready.close()
        time.sleep(20)


@pytest.mark.integration
def test_independent_processes_share_one_postgres_account_authority(settings):
    configured = replace(settings, namespace="fx_auth_" + uuid4().hex[:10])
    bootstrap(configured)
    dsn = configured.runtime_dsn(Environment.PAPER)
    store = PostgresAuthorityStore(dsn, ACCOUNT)
    authority = Authority(store, ACCOUNT, bootstrap=True)
    assert PostgresAuthorityStore(dsn, ACCOUNT).stream == store.stream
    with pytest.raises(ValueError, match="ACCOUNT_AUTHORITY_STORE_REQUIRED"):
        Authority(PostgresStore(dsn, ACCOUNT, uuid4()), ACCOUNT, bootstrap=True)
    context = multiprocessing.get_context("spawn")
    gate, queue = context.Event(), context.Queue()
    children = [
        context.Process(
            target=_claim_process,
            args=(dsn, ACCOUNT.model_dump(mode="json"), owner, incarnation, gate, queue),
        )
        for owner, incarnation in ((CLIENT, INCARNATION), (OTHER, OTHER))
    ]
    try:
        for child in children:
            child.start()
        gate.set()
        results = [queue.get(timeout=20), queue.get(timeout=20)]
        assert sorted(r[0] for r in results) == ["CLAIMED", "EXPLICIT_RETIREMENT_REQUIRED"]
        for child in children:
            child.join(timeout=10)
            assert child.exitcode == 0
    finally:
        for child in children:
            if child.is_alive():
                child.terminate()
                child.join(timeout=5)
        queue.close()
    with authority.store.transaction() as events:
        assert len([r for r in events.records if r["kind"] == "claim"]) == 1


@pytest.mark.integration
def test_actual_database_outage_denies_authority_without_takeover(settings):
    configured = replace(settings, namespace="fx_auth_" + uuid4().hex[:10])
    bootstrap(configured)
    store = PostgresAuthorityStore(configured.runtime_dsn(Environment.PAPER), ACCOUNT)
    authority = Authority(store, ACCOUNT, bootstrap=True)
    lease = authority.claim(CLIENT, INCARNATION, NOW)
    dsn = store.dsn
    store.dsn = make_conninfo(dsn, dbname="missing_auth_" + uuid4().hex)
    with pytest.raises(psycopg.OperationalError):
        authority.check(CLIENT, INCARNATION, 1, NOW + 1)
    store.dsn = dsn
    assert authority.check(CLIENT, INCARNATION, 1, NOW + 2) == lease
    with pytest.raises(ValueError, match="EXPLICIT_RETIREMENT_REQUIRED"):
        authority.claim(OTHER, OTHER, NOW + 3)


@pytest.mark.integration
def test_killed_guard_process_rolls_back_transaction_without_reassigning_owner(settings):
    configured = replace(settings, namespace="fx_auth_" + uuid4().hex[:10])
    bootstrap(configured)
    store = PostgresAuthorityStore(configured.runtime_dsn(Environment.PAPER), ACCOUNT)
    authority = Authority(store, ACCOUNT, bootstrap=True)
    lease = authority.claim(CLIENT, INCARNATION, NOW)
    before = authority.tip()
    context = multiprocessing.get_context("spawn")
    ready, writer = context.Pipe(duplex=False)
    child = context.Process(
        target=_guard_process, args=(store.dsn, ACCOUNT.model_dump(mode="json"), writer)
    )
    try:
        child.start()
        writer.close()
        assert ready.poll(10) and ready.recv() is True
        child.terminate()  # Only the fixture child created immediately above.
        child.join(timeout=10)
        assert not child.is_alive()
        assert authority.tip() == before  # Uncommitted guard heartbeat rolled back.
        assert authority.check(CLIENT, INCARNATION, 1, NOW + 2) == lease
        with pytest.raises(ValueError, match="EXPLICIT_RETIREMENT_REQUIRED"):
            authority.claim(OTHER, OTHER, NOW + 3)
    finally:
        ready.close()
        writer.close()
        if child.is_alive():
            child.terminate()
            child.join(timeout=5)


def test_checkpoint_common_receipt_hash_is_content_bound():
    checkpoint = paired(scope_for(ACCOUNT), acknowledged=False)
    changed = PairCheckpoint.match(
        checkpoint.backend, replace(checkpoint.native, acknowledged=True)
    )
    assert changed.fingerprint != checkpoint.fingerprint
    assert checkpoint.backend.receipt_hash != digest("different original receipt")


def test_connected_checkpoint_uses_actual_work_receipt_and_journal_hash(tmp_path):
    scope = scope_for(ACCOUNT)
    store = SQLiteStore(tmp_path / "connected.db", bootstrap=True)
    identifier = str(uuid4())
    work_value = "\t".join(
        [
            "connected-observation/1",
            identifier,
            "1",
            scope,
            "a" * 64,
            str(NOW),
            str(NOW + 60000),
            "1",
            "EURUSD",
            "EURUSD",
            str(NOW - 500),
            "COSTS",
            "b" * 64,
            "0",
        ]
    )
    receipt = "\t".join(
        [
            "connected-hold/1",
            identifier,
            "1",
            "a" * 64,
            str(NOW),
            "1",
            "500",
            str(NOW - 500),
            "500",
            "REQUIRED_INPUTS",
            "COSTS",
            "0",
        ]
    )
    with store.transaction() as events:
        events.append(dict(kind="binding", scope=scope, execution_enabled=False))
        events.append(dict(kind="work", work=work_value, execution_enabled=False))
        events.append(dict(kind="receipt", receipt=receipt, execution_enabled=False))
        tip = events.tip
    point = backend_checkpoint(store, scope)
    assert point == PeerCheckpoint(scope, tip, 1, digest(receipt))
    with pytest.raises(ValueError, match="BINDING"):
        backend_checkpoint(store, OTHER)
    with store.transaction() as events:
        events.append(
            dict(
                kind="receipt", receipt=receipt.replace("a" * 64, "c" * 64), execution_enabled=False
            )
        )
    with pytest.raises(ValueError, match="RECEIPT"):
        backend_checkpoint(store, scope)


@pytest.mark.integration
def test_paired_authority_and_backend_survive_guarded_database_archive(settings, tmp_path):
    from fx_talanta.storage.archive import export_archive, release_restore, restore_archive

    configured = replace(settings, namespace="fx_auth_" + uuid4().hex[:10])
    target = replace(settings, namespace="fx_auth_" + uuid4().hex[:10])
    bootstrap(configured)
    bootstrap(target)
    dsn = configured.runtime_dsn(Environment.PAPER)
    authority = Authority(PostgresAuthorityStore(dsn, ACCOUNT), ACCOUNT, bootstrap=True)
    authority.claim(CLIENT, INCARNATION, NOW)
    store = PostgresStore(dsn, ACCOUNT, uuid4())
    backend = Backend(store, ACCOUNT, CLIENT, RELEASE, POLICY, KEY, bootstrap=True)
    backend.publish(*work(), NOW)
    client = Client(
        SQLiteStore(tmp_path / "archive-peer.db", bootstrap=True),
        scope_for(ACCOUNT),
        CLIENT,
        RELEASE,
        POLICY,
        KEY,
        bootstrap=True,
    )
    client.step(lambda raw: backend.exchange(raw, NOW), lambda: NOW)
    client.step(lambda raw: backend.exchange(raw, NOW), lambda: NOW)
    backend_point = backend_checkpoint(store, authority.scope)
    with client.store.transaction() as events:
        native_point = PeerCheckpoint(authority.scope, events.tip, 1, backend_point.receipt_hash)
    checkpoint = PairCheckpoint.match(backend_point, native_point)
    with pytest.raises(ValueError, match="ACTUAL_BACKEND_CHECKPOINT_REQUIRED"):
        authority.retire(
            CLIENT, INCARNATION, 1, NOW + 1, checkpoint=checkpoint, source_retired=True
        )
    client.step(lambda raw: backend.exchange(raw, NOW + 1), lambda: NOW + 1)
    with pytest.raises(ValueError, match="BACKEND_CHECKPOINT_CHANGED"):
        authority.retire(
            CLIENT,
            INCARNATION,
            1,
            NOW + 1,
            checkpoint=checkpoint,
            source_retired=True,
            backend_store=store,
        )
    checkpoint = PairCheckpoint.match(backend_checkpoint(store, authority.scope), native_point)
    authority.retire(
        CLIENT,
        INCARNATION,
        1,
        NOW + 1,
        checkpoint=checkpoint,
        source_retired=True,
        backend_store=store,
    )
    tip = authority.tip()
    archive = tmp_path / "authority.fxbackup"
    export_archive(configured, archive)
    restore_archive(target, archive)
    restored = Authority(
        PostgresAuthorityStore(target.runtime_dsn(Environment.PAPER), ACCOUNT),
        ACCOUNT,
        expected_tip=tip,
    )
    restored_backend = PostgresStore(target.runtime_dsn(Environment.PAPER), ACCOUNT, store.stream)
    assert restored.verify_restore(checkpoint, expected_tip=tip, backend_store=restored_backend)
    with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState):
        restored.claim(OTHER, OTHER, NOW + 2, checkpoint=checkpoint)
    release_restore(target, archive, source_retired=True)
    assert restored.claim(OTHER, OTHER, NOW + 2, checkpoint=checkpoint).epoch == 2
    with pytest.raises(ValueError, match="NOT_AUTHORITY_OWNER"):
        with restored.guard_receipt(CLIENT, INCARNATION, 1, lambda: NOW + 3):
            pytest.fail("retired owner reached restored receipt ingestion")


@pytest.mark.integration
def test_reused_connections_commit_independently_and_never_reconnect_after_loss(settings):
    configured = replace(settings, namespace="fx_reuse_" + uuid4().hex[:10])
    bootstrap(configured)
    dsn = configured.runtime_dsn(Environment.PAPER)
    store = PostgresAuthorityStore(dsn, ACCOUNT, reuse_connection=True)
    try:
        authority = Authority(store, ACCOUNT, bootstrap=True)
        connection = store._connection
        lease = authority.claim(CLIENT, INCARNATION, NOW)
        assert store._connection is connection
        independent = Authority(PostgresAuthorityStore(dsn, ACCOUNT), ACCOUNT)
        assert independent.check(CLIENT, INCARNATION, 1, NOW + 1) == lease
        connection.close()
        with pytest.raises(psycopg.Error):
            authority.check(CLIENT, INCARNATION, 1, NOW + 2)
        with pytest.raises(ValueError, match="DATABASE_CONNECTION_CLOSED"):
            authority.check(CLIENT, INCARNATION, 1, NOW + 3)
        assert independent.check(CLIENT, INCARNATION, 1, NOW + 4) == lease
    finally:
        store.close()


@pytest.mark.integration
def test_reused_connection_validation_rollback_preserves_expired_owner_receipt_recovery(settings):
    configured = replace(settings, namespace="fx_rollback_" + uuid4().hex[:10])
    bootstrap(configured)
    store = PostgresAuthorityStore(
        configured.runtime_dsn(Environment.PAPER), ACCOUNT, reuse_connection=True
    )
    try:
        authority = Authority(store, ACCOUNT, bootstrap=True)
        lease = authority.claim(CLIENT, INCARNATION, NOW)
        connection = store._connection
        with pytest.raises(ValueError, match="LEASE_EXPIRED"):
            authority.check(CLIENT, INCARNATION, lease.epoch, lease.expires_ms)
        assert store._connection is connection and not connection.closed
        with authority.guard_receipt(
            CLIENT, INCARNATION, lease.epoch, lambda: lease.expires_ms + 1
        ):
            pass
        assert store._connection is connection
        with pytest.raises(ValueError, match="LEASE_EXPIRED"):
            authority.renew(CLIENT, INCARNATION, lease.epoch, lease.expires_ms + 2)
    finally:
        store.close()
