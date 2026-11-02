import multiprocessing
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import psycopg
import pytest
from psycopg.types.json import Jsonb

from fx_talanta.clock import FakeClock
from fx_talanta.domain.models import Environment, Record
from fx_talanta.observer.contracts import Binding
from fx_talanta.observer.fixtures import FixtureReader
from fx_talanta.observer.supervisor import Observer, assess, collect
from fx_talanta.storage.archive import export_archive, release_restore, restore_archive
from fx_talanta.storage.bootstrap import bootstrap
from fx_talanta.storage.config import fixture_account
from fx_talanta.storage.offline import WriterBusy

NOW = datetime(2026, 1, 5, 12, tzinfo=UTC)


@pytest.fixture
def binding():
    return Binding(
        account=fixture_account(Environment.PAPER),
        terminal_path="C:/fixture/terminal64.exe",
        data_path="C:/fixture/data",
        expected_build=123,
    )


@pytest.mark.parametrize(
    "fault,reason",
    [
        ("NONE", "CURRENT"),
        ("ACCOUNT", "IDENTITY_MISMATCH"),
        ("BUILD", "BUILD_CHANGED"),
        ("PATH", "PATH_MISMATCH"),
        ("CURRENCY", "CURRENCY_MISMATCH"),
        ("DISCONNECTED", "DISCONNECTED"),
        ("STALE", "STALE_TICKS"),
        ("MISSING", "MISSING_DATA"),
        ("HISTORY", "MISSING_DATA"),
        ("FUTURE", "INVALID_DATA"),
    ],
)
def test_snapshot_assessment(binding, fault, reason):
    assert assess(FixtureReader(fault)(binding, NOW), binding, NOW) == reason


def test_reject_incomplete_bar_future_tick_and_duplicate_symbol(binding):
    snapshot = FixtureReader()(binding, NOW)
    old_bars = tuple(
        b.model_copy(update={"opened_at": b.opened_at - timedelta(hours=2)}) for b in snapshot.bars
    )
    assert assess(snapshot.model_copy(update={"bars": old_bars}), binding, NOW) == "MISSING_DATA"
    bar = snapshot.bars[0].model_copy(update={"opened_at": NOW})
    assert assess(snapshot.model_copy(update={"bars": (bar,)}), binding, NOW) == "INVALID_DATA"
    tick = snapshot.ticks[0].model_copy(update={"at": NOW + timedelta(seconds=1)})
    assert assess(snapshot.model_copy(update={"ticks": (tick,)}), binding, NOW) == "INVALID_DATA"
    assert (
        assess(snapshot.model_copy(update={"symbols": snapshot.symbols * 2}), binding, NOW)
        == "MISSING_DATA"
    )


def test_paths_case_normalized_but_relative_and_real_accounts_rejected(binding):
    snapshot = FixtureReader()(binding, NOW).model_copy(
        update={"terminal_path": "c:\\FIXTURE\\terminal64.exe"}
    )
    assert assess(snapshot, binding, NOW) == "CURRENT"
    for update in (
        {"terminal_path": "terminal64.exe"},
        {"account": binding.account.model_copy(update={"venue": "BROKER_DEMO"})},
    ):
        with pytest.raises(ValueError):
            Binding.model_validate(binding.model_copy(update=update).model_dump(mode="json"))


@pytest.mark.parametrize(
    "fault,reason",
    [("NONE", None), ("ERROR", "READER_FAILED"), ("CRASH", "READER_FAILED"), ("HANG", "TIMEOUT")],
)
def test_subprocess_deadline_and_cleanup(binding, fault, reason):
    binding = binding.model_copy(update={"call_timeout_seconds": 2})
    before = {p.pid for p in multiprocessing.active_children()}
    snapshot, actual = collect(FixtureReader(fault), binding, NOW)
    assert actual == reason
    assert (snapshot is not None) == (reason is None)
    assert {p.pid for p in multiprocessing.active_children()} == before


@pytest.mark.integration
def test_persistent_recovery_halt_and_single_observer(settings, binding):
    clock, run_id = FakeClock(NOW), uuid4()
    dsn = settings.runtime_dsn(Environment.PAPER)
    observer = Observer(dsn, binding, run_id, clock)
    try:
        with pytest.raises(WriterBusy):
            Observer(dsn, binding, uuid4(), clock)
        healthy = observer.poll(FixtureReader())
        assert healthy.body.state == "HEALTHY"
        clock.advance(timedelta(seconds=1))
        failure = observer.poll(FixtureReader("ERROR"))
        assert failure.body.state == "BACKOFF"
        assert "diagnostic" not in failure.model_dump_json()
        assert failure.body.last_success_at == NOW
    finally:
        observer.close()
    observer = Observer(dsn, binding, run_id, clock)
    try:
        assert observer.poll(FixtureReader()) == failure  # persistent backoff
        clock.advance(timedelta(seconds=2))
        recovered = observer.poll(FixtureReader())
        assert recovered.body.state == "HEALTHY" and recovered.body.failures == 0
        halted = observer.poll(FixtureReader("ACCOUNT"))
        assert halted.body.state == "HALTED" and halted.body.snapshot is None
    finally:
        observer.close()
    observer = Observer(dsn, binding, run_id, clock)
    try:
        assert observer.poll(FixtureReader()) == halted  # no implicit reset after restart
    finally:
        observer.close()
    with pytest.raises(ValueError, match="restart cannot change"):
        Observer(dsn, binding.model_copy(update={"expected_build": 124}), run_id, clock)


@pytest.mark.integration
def test_failure_limit_and_database_guards(settings, binding):
    observer = Observer(settings.runtime_dsn(Environment.PAPER), binding, uuid4(), FakeClock(NOW))
    try:
        for index in range(3):
            record = observer.poll(FixtureReader("STALE"))
            observer.clock.advance(timedelta(seconds=20))
            assert record.body.failures == index + 1
        assert record.body.state == "HALTED"
        assert len(observer.repo.history(correlation_id=observer.run_id)) == 3
        payload = record.model_dump(mode="json")
        payload["record_id"] = str(uuid4())
        payload["provenance"] = "OFFLINE_SIMULATION"
        with pytest.raises(ValueError):
            Record.model_validate(payload)
        # Runtime SQL cannot relabel observer output as executed simulation evidence.
        with pytest.raises(psycopg.errors.CheckViolation), observer.conn.transaction():
            observer.conn.execute(
                "INSERT INTO fx.records(record_id,kind,recorded_at,payload) VALUES (%s,%s,%s,%s)",
                (payload["record_id"], "observation", NOW, Jsonb(payload)),
            )
        with pytest.raises(psycopg.Error), observer.conn.transaction():
            observer.conn.execute("DELETE FROM fx.records WHERE record_id=%s", (record.record_id,))
    finally:
        observer.close()


@pytest.mark.integration
def test_archive_restores_halt_and_fences_observer(settings, binding, tmp_path):
    source = replace(settings, namespace="fx_obs_src_" + uuid4().hex[:12])
    target = replace(settings, namespace="fx_obs_dst_" + uuid4().hex[:12])
    bootstrap(source)
    bootstrap(target)
    clock, run_id = FakeClock(NOW), uuid4()
    observer = Observer(source.runtime_dsn(Environment.PAPER), binding, run_id, clock)
    path = tmp_path / "observer.fxbackup"
    try:
        halted = observer.poll(FixtureReader("BUILD"))
        with pytest.raises(WriterBusy):
            export_archive(source, path)
    finally:
        observer.close()
    export_archive(source, path)
    restore_archive(target, path)
    observer = Observer(target.runtime_dsn(Environment.PAPER), binding, run_id, clock)
    try:
        with pytest.raises(ValueError, match="restore has not been verified"):
            observer.poll(FixtureReader())
    finally:
        observer.close()
    release_restore(target, path, source_retired=True)
    observer = Observer(target.runtime_dsn(Environment.PAPER), binding, run_id, clock)
    try:
        assert observer.poll(FixtureReader()) == halted
    finally:
        observer.close()
