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
