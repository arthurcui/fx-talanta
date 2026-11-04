"""Explicit no-order session handoff; native peer data here is SYNTHETIC.

The PostgreSQL streams, signatures, lease fencing, export and restore are actual.
The test does not restart a terminal or claim seamless cross-epoch EA continuation.
The old session is completed/retired and retained; epoch 2 starts a new stream.
"""

from dataclasses import replace
from uuid import uuid4

import psycopg
import pytest

from fx_talanta.connected_shadow.authority import (
    Authority,
    PairCheckpoint,
    PeerCheckpoint,
    PostgresAuthorityStore,
    backend_checkpoint,
)
from fx_talanta.connected_shadow.service import Service, hold_receipt
from fx_talanta.domain.models import Environment
from fx_talanta.shadow.store import PostgresStore, canonical
from fx_talanta.shadow.wire import Frame, digest
from fx_talanta.storage.archive import export_archive, release_restore, restore_archive
from fx_talanta.storage.bootstrap import bootstrap
from tests.test_connected_inputs import NOW, binding, capture

CLIENT = "c" * 64
FIRST, SECOND = "1" * 64, "2" * 64
KEY = b"synthetic-handoff-test-key-1234567"


def exchange(service, now, command, receipt="", *, key=KEY):
    nonce = digest(uuid4().hex)
    payload = f"connected/1\t{command}\t{service.incarnation}\t{service.epoch}"
    if receipt:
        payload += "\t" + receipt.encode("ascii").hex()
    frame = Frame(
        "C2S",
        service.scope,
        service.client,
        nonce,
        now,
        now + 5000,
        "REPORT" if command == "REPORT" else "PULL",
        payload,
    )
    result = service.exchange(frame.encode(key))
    return Frame.decode(
        result,
        KEY,
        direction="S2C",
        scope=service.scope,
        client=service.client,
        now=now,
        nonce=nonce,
    )


def retained(store):
    with store.transaction() as events:
        return events.tip, digest(canonical(events.records))


@pytest.mark.integration
def test_finished_session_handoff_preserves_old_stream_and_uses_new_epoch_stream(
    settings, tmp_path
):
    account = binding().account  # Explicitly synthetic demo identity, not either real broker.
    source = replace(settings, namespace="fx_hand_" + uuid4().hex[:10])
    target = replace(settings, namespace="fx_hand_" + uuid4().hex[:10])
    bootstrap(source, paper_account=account)
    bootstrap(target, paper_account=account)
    at = [NOW]

    def clock():
        return at[0], 10

    source_dsn = source.runtime_dsn(Environment.PAPER)
    authority = Authority(PostgresAuthorityStore(source_dsn, account), account, bootstrap=True)
    authority.claim(CLIENT, FIRST, NOW + 10)
    old_store = PostgresStore(source_dsn, account, uuid4())
    old_service = Service(
        old_store, authority, account, CLIENT, FIRST, 1, KEY, clock, bootstrap=True
    )
    old_service.publish(capture(), "EURUSD")
    assert exchange(old_service, NOW, "SYNC").payload == f"connected/1\tCLOCK\t{NOW}\t10"
    work = exchange(old_service, NOW, "PULL").payload
    receipt = hold_receipt(work, NOW, 40, NOW - 400)
    assert receipt.split("\t")[9] == "REQUIRED_INPUTS"
    assert exchange(old_service, NOW, "REPORT", receipt).payload == digest(receipt)
    backend = backend_checkpoint(old_store, old_service.scope)
    synthetic_native_peer = PeerCheckpoint(
        old_service.scope, digest("SYNTHETIC_NATIVE_PEER_SESSION_1"), 1, digest(receipt), True
    )
    pair = PairCheckpoint.match(backend, synthetic_native_peer)
    preserved = retained(old_store)

    # Retirement is a trusted local action after both peer checkpoints agree.
    # There is no wire route for lease takeover or acceptance of a supplied checkpoint.
    at[0] += 100
    authority.retire(
        CLIENT,
        FIRST,
        1,
        old_service.clock_upper(),
        checkpoint=pair,
        source_retired=True,
        backend_store=old_store,
    )
    authority_tip = authority.tip()
    for command in ("PULL", "SYNC"):
        with pytest.raises(ValueError, match="NOT_AUTHORITY_OWNER"):
            exchange(old_service, at[0], command)
    assert retained(old_store) == preserved

    archive = tmp_path / "finished-shadow-session.fxbackup"
    export_archive(source, archive, paper_account=account)
    restore_archive(target, archive, paper_account=account)
    target_dsn = target.runtime_dsn(Environment.PAPER)
    restored_authority = Authority(
        PostgresAuthorityStore(target_dsn, account), account, expected_tip=authority_tip
    )
    restored_old_store = PostgresStore(target_dsn, account, old_store.stream)
    assert restored_authority.verify_restore(
        pair, expected_tip=authority_tip, backend_store=restored_old_store
    )
    assert retained(restored_old_store) == preserved
    with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState):
        restored_authority.claim(CLIENT, SECOND, old_service.clock_upper(), checkpoint=pair)
    release_restore(target, archive, paper_account=account, source_retired=True)
    at[0] += 100
    lease = restored_authority.claim(CLIENT, SECOND, old_service.clock_upper(), checkpoint=pair)
    assert lease.epoch == 2

    # In-place epoch rollover is explicitly unsupported, never silently rewritten.
    with pytest.raises(ValueError, match="CONNECTED_BINDING_CONFLICT"):
        Service(restored_old_store, restored_authority, account, CLIENT, SECOND, 2, KEY, clock)
    old_restored_service = Service(
        restored_old_store, restored_authority, account, CLIENT, FIRST, 1, KEY, clock
    )
    for command in ("PULL", "SYNC", "REPORT"):
        with pytest.raises(ValueError, match="NOT_AUTHORITY_OWNER"):
            exchange(old_restored_service, at[0], command, receipt if command == "REPORT" else "")

    new_store = PostgresStore(target_dsn, account, uuid4())
    new_service = Service(
        new_store, restored_authority, account, CLIENT, SECOND, 2, KEY, clock, bootstrap=True
    )
    assert new_service.publish(capture(), "EURUSD")
    with pytest.raises(ValueError, match="AUTHENTICATION_FAILURE"):
        exchange(new_service, at[0], "SYNC", key=b"x" * 32)
    assert exchange(new_service, at[0], "SYNC").operation == "WORK"
    new_work = exchange(new_service, at[0], "PULL").payload
    assert new_work.split("\t")[2] == "1"  # New bounded session, independent native inbox.
    new_receipt = hold_receipt(new_work, at[0], 40, NOW - 400)
    assert exchange(new_service, at[0], "REPORT", new_receipt).payload == digest(new_receipt)
    assert exchange(new_service, at[0], "REPORT", new_receipt).payload == digest(new_receipt)
    assert new_service.status()["receipt_count"] == 1
    assert new_service.status()["connected_execution_accepted"] is False
    assert new_service.status()["execution_enabled"] is False
    assert retained(old_store) == retained(restored_old_store) == preserved
