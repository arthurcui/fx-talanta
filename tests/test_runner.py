import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace as NS
from uuid import uuid4

import psycopg
import pytest

from fx_talanta.clock import FakeClock
from fx_talanta.domain.models import Environment
from fx_talanta.observer.contracts import Binding
from fx_talanta.observer.fixtures import FixtureReader
from fx_talanta.observer.runner import Evidence, RunnerPlan, read_status, run_observer, status_lock
from fx_talanta.observer.supervisor import Observer
from fx_talanta.storage.config import fixture_account
from fx_talanta.storage.offline import WriterBusy

NOW = datetime(2026, 11, 2, 12, tzinfo=UTC)


@pytest.fixture
def binding():
    return Binding(
        account=fixture_account(Environment.PAPER),
        terminal_path="C:/fixture/terminal64.exe",
        data_path="C:/fixture/data",
        expected_build=123,
    )


class Harness:
    def __init__(self, tmp_path, binding):
        self.clock = FakeClock(NOW)
        self.path = tmp_path / "status.json"
        self.stop = tmp_path / "stop"
        self.binding = binding
        self.run_id = uuid4()
        self.records = []
        self.events = []
        self.connections = self.closed = 0

    def factory(self, *args):
        self.connections += 1
        harness = self

        class Stub:
            last = harness.records[-1] if harness.records else None
            repo = NS(history=lambda **kw: harness.records.copy())

            def poll(self, reader):
                event = harness.events.pop(0) if harness.events else "HEALTHY"
                if event == "DB_ERROR":
                    raise psycopg.OperationalError("SECRET diagnostic must not leak")
                state = "HEALTHY" if event in {"COMMIT_UNKNOWN", "STOP"} else event
                reason = "CURRENT" if state == "HEALTHY" else "INVALID_DATA"
                self.last = NS(
                    record_id=uuid4(),
                    recorded_at=harness.clock.now(),
                    body=NS(state=state, reason=reason),
                )
                harness.records.append(self.last)
                if event == "COMMIT_UNKNOWN":
                    raise psycopg.OperationalError("SECRET commit outcome unknown")
                if event == "STOP":
                    harness.stop.touch()
                return self.last

            def close(self):
                harness.closed += 1

        return Stub()

    def run(self, **kwargs):
        return run_observer(
            "dbname=unused",
            self.binding,
            self.run_id,
            self.path,
            self.stop,
            kwargs.pop("plan", RunnerPlan(duration_seconds=90)),
            clock=self.clock,
            sleep=lambda seconds: self.clock.advance(timedelta(seconds=seconds)),
            monotonic=lambda: (self.clock.now() - NOW).total_seconds(),
            observer_factory=kwargs.pop("factory", self.factory),
            reader=FixtureReader(),
            **kwargs,
        )


def test_duration_report_and_single_writer(tmp_path, binding):
    h = Harness(tmp_path, binding)
    with status_lock(h.path), pytest.raises(WriterBusy):
        h.run()
    result = h.run()
    assert result["phase"] == "COMPLETE"
    assert result["evidence"]["observations"] == 3
    assert not result["evidence"]["accepted"]  # short smoke is never a 24h acceptance
    assert h.connections == h.closed == 1
    assert json.loads(h.path.read_text()) == result
    result["phase"] = "RUNNING"
    h.path.write_text(json.dumps(result))
    assert read_status(h.path, h.clock.now())["heartbeat_state"] == "CURRENT"
    assert read_status(h.path, h.clock.now() + timedelta(minutes=5))["heartbeat_state"] == "STALE"


def test_database_reconnect_and_unknown_commit_rebuild(tmp_path, binding):
    h = Harness(tmp_path, binding)
    h.events = ["DB_ERROR", "COMMIT_UNKNOWN", "HEALTHY"]
    result = h.run()
    assert result["phase"] == "COMPLETE"
    assert result["database_errors"] == 2
    assert result["evidence"]["observations"] == len(h.records)
    assert result["evidence"]["healthy"] == len(h.records)
    assert h.connections == h.closed == 3
    assert "SECRET" not in h.path.read_text()


def test_database_retry_limit_and_deadline(tmp_path, binding):
    h = Harness(tmp_path, binding)

    def unavailable(*args):
        raise psycopg.OperationalError("SECRET")

    result = h.run(
        factory=unavailable, plan=RunnerPlan(duration_seconds=90, max_database_failures=2)
    )
    assert result["phase"] == "FAILED" and result["reason"] == "DATABASE_RETRY_LIMIT"
    h = Harness(tmp_path / "other", binding)
    result = h.run(factory=unavailable, plan=RunnerPlan(duration_seconds=2))
    assert result["reason"] == "DATABASE_UNAVAILABLE_AT_DEADLINE"


def test_restart_preserves_deadline_and_halt(tmp_path, binding):
    h = Harness(tmp_path, binding)
    h.events = ["STOP"]
    first = h.run()
    assert first["phase"] == "STOPPED"
    h.stop.unlink()
    h.clock.advance(timedelta(seconds=30))
    h.events = ["HALTED"]
    second = h.run()
    assert first["deadline"] == second["deadline"]
    assert second["phase"] == "HALTED" and len(h.records) == 2
    connections = h.connections
    assert h.run() == second and h.connections == connections
    with pytest.raises(ValueError, match="restart cannot change"):
        h.run(plan=RunnerPlan(duration_seconds=91))


def test_policy_must_cover_full_soak(tmp_path, binding):
    h = Harness(
        tmp_path, binding.model_copy(update={"time_policy_until": NOW + timedelta(seconds=60)})
    )
    with pytest.raises(ValueError, match="entire planned run"):
        h.run()
    assert h.connections == 0


def test_evidence_24h_gate_detects_gaps_and_stale_samples():
    evidence = Evidence()
    plan = RunnerPlan()
    for offset in range(0, 86400, 30):
        evidence.add(
            NS(
                record_id=uuid4(),
                recorded_at=NOW + timedelta(seconds=offset),
                body=NS(state="HEALTHY", reason="CURRENT"),
            )
        )
    result = evidence.summary(NOW, NOW + timedelta(days=1), plan, "COMPLETE")
    assert result["accepted"]
    assert not evidence.summary(NOW, NOW + timedelta(days=1), plan, "RUNNING")["accepted"]
    assert not evidence.summary(NOW, NOW + timedelta(days=1, minutes=5), plan, "COMPLETE")[
        "accepted"
    ]
    evidence.healthy = 100
    assert not evidence.summary(NOW, NOW + timedelta(days=1), plan, "COMPLETE")["accepted"]


@pytest.mark.integration
def test_actual_database_session_loss_recovers_same_run(settings, binding, tmp_path):
    h = Harness(tmp_path, binding)
    attempts = []

    def factory(dsn, binding, run_id, clock):
        observer = Observer(dsn, binding, run_id, clock)
        attempts.append(observer)
        if len(attempts) == 1:
            original_poll = observer.poll

            def lose_connection(reader):
                with psycopg.connect(
                    settings.admin_dsn(settings.database(Environment.PAPER))
                ) as admin:
                    admin.execute(
                        "SELECT pg_terminate_backend(%s)", (observer.conn.info.backend_pid,)
                    )
                return original_poll(reader)

            observer.poll = lose_connection
        return observer

    result = run_observer(
        settings.runtime_dsn(Environment.PAPER),
        binding,
        h.run_id,
        h.path,
        h.stop,
        RunnerPlan(duration_seconds=10, interval_seconds=2),
        clock=h.clock,
        sleep=lambda seconds: h.clock.advance(timedelta(seconds=seconds)),
        monotonic=lambda: (h.clock.now() - NOW).total_seconds(),
        observer_factory=factory,
        reader=FixtureReader(),
    )
    assert result["phase"] == "COMPLETE" and result["database_errors"] == 1
    assert len(attempts) == 2 and result["evidence"]["healthy"] >= 1
    assert all(observer.conn.closed for observer in attempts)


@pytest.mark.integration
@pytest.mark.parametrize("fault,recover_after", [("STALE", 8), ("STALE", 10), ("MISSING", 8)])
def test_degraded_snapshots_keep_cadence_and_halt_threshold(
    settings, binding, tmp_path, monkeypatch, fault, recover_after
):
    from fx_talanta.storage.repository import Repository

    binding = binding.model_copy(update={"max_failures": 10})
    h = Harness(tmp_path, binding)
    calls = []

    def collect_fixture(reader, pinned, now):
        calls.append(now)
        snapshot = FixtureReader(fault if len(calls) <= recover_after else "NONE")(pinned, now)
        # Completion occurs after the runner's cadence origin, reproducing the
        # boundary that formerly skipped polls while waiting for retry deadlines.
        h.clock.advance(timedelta(milliseconds=100))
        return snapshot, None

    monkeypatch.setattr("fx_talanta.observer.supervisor.collect", collect_fixture)
    dsn = settings.runtime_dsn(Environment.PAPER)
    result = h.run(
        factory=lambda _dsn, pinned, run, clock: Observer(dsn, pinned, run, clock),
        plan=RunnerPlan(duration_seconds=300, interval_seconds=30),
    )
    rows = Repository(dsn, binding.account).history(correlation_id=h.run_id)
    assert calls == [NOW + timedelta(seconds=30 * i) for i in range(10)]
    assert len(rows) == 10 and result["evidence"]["max_gap_seconds"] <= 30
    assert not result["evidence"]["accepted"]  # neither short nor degraded runs qualify
    for i, row in enumerate(rows[:recover_after]):
        assert row.body.failures == i + 1
        assert row.body.reason == ("STALE_TICKS" if fault == "STALE" else "MISSING_DATA")
        assert row.body.next_retry_at == (None if i == 9 else row.recorded_at)
    if recover_after == 10:
        assert result["phase"] == "HALTED" and rows[-1].body.failures == 10
        reopened = Observer(dsn, binding, h.run_id, h.clock)
        try:
            assert reopened.poll(FixtureReader()) == rows[-1]
            assert len(calls) == 10  # restart cannot clear a persistent halt
        finally:
            reopened.close()
    else:
        assert result["phase"] == "COMPLETE" and rows[-1].body.state == "HEALTHY"
        assert rows[-1].body.failures == 0


@pytest.mark.integration
@pytest.mark.parametrize("reason", ["TIMEOUT", "READER_FAILED", "DISCONNECTED"])
def test_transport_backoff_survives_until_exact_deadline(settings, binding, monkeypatch, reason):
    clock, calls = FakeClock(NOW), []

    def collect_fixture(reader, pinned, now):
        calls.append(now)
        return (None, reason) if len(calls) == 1 else (FixtureReader()(pinned, now), None)

    monkeypatch.setattr("fx_talanta.observer.supervisor.collect", collect_fixture)
    observer = Observer(settings.runtime_dsn(Environment.PAPER), binding, uuid4(), clock)
    try:
        failed = observer.poll(FixtureReader())
        assert failed.body.state == "BACKOFF"
        clock.advance(timedelta(seconds=binding.backoff_seconds, microseconds=-1))
        assert observer.poll(FixtureReader()) == failed and len(calls) == 1
        clock.advance(timedelta(microseconds=1))
        recovered = observer.poll(FixtureReader())
        assert recovered.body.state == "HEALTHY" and recovered.body.failures == 0
        assert len(calls) == 2
    finally:
        observer.close()
