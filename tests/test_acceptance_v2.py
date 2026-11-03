import json
from contextlib import closing
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace as NS
from uuid import uuid4

import psycopg
import pytest

from fx_talanta.clock import FakeClock
from fx_talanta.domain.models import Environment, ObservationHealth, TerminalObservation
from fx_talanta.domain.offline import Policy
from fx_talanta.observer.acceptance import SeparatedEvidence
from fx_talanta.observer.contracts import Binding
from fx_talanta.observer.fixtures import FixtureReader
from fx_talanta.observer.runner import RunnerPlan, run_observer
from fx_talanta.observer.supervisor import Observer, assess
from fx_talanta.offline_fixtures import market_at
from fx_talanta.risk.governor import health_reason
from fx_talanta.storage.config import fixture_account
from fx_talanta.storage.repository import Repository

NOW = datetime(2026, 11, 2, 12, tzinfo=UTC)


@pytest.fixture
def binding():
    return Binding(
        account=fixture_account(Environment.PAPER),
        terminal_path="C:/fixture/terminal64.exe",
        data_path="C:/fixture/data",
        expected_build=123,
        max_failures=10,
    )


def sample(offset, reason="CURRENT", *, final=False):
    at = NOW + timedelta(seconds=offset)
    complete = reason in {"CURRENT", "STALE_TICKS"}
    age = 8 if reason == "STALE_TICKS" else 1
    health = ObservationHealth(
        collection_started_at=at,
        integrity="VALID" if complete else "UNVERIFIED",
        transport="READ_OK" if complete else "READ_FAILED",
        complete_read=complete,
        transport_failures=0 if complete else 1,
        completeness_failures=0,
        quote_ages_seconds={"EURUSD": age},
        quote_quality={"EURUSD": "STALE" if age > 5 else "FRESH"},
        final_verification=final,
    )
    return NS(
        record_id=uuid4(),
        recorded_at=at,
        body=NS(
            health=health, state="HEALTHY" if reason == "CURRENT" else "DEGRADED", reason=reason
        ),
    )


def campaign(reason="CURRENT"):
    evidence = SeparatedEvidence()
    for offset in range(0, 86400, 30):
        evidence.add(sample(offset, reason))
    return evidence


def verdict(evidence, seconds=86400):
    return evidence.summary(
        NOW, NOW + timedelta(seconds=seconds), RunnerPlan(acceptance_version=2), "COMPLETE"
    )


def test_dual_verdict_requires_distinct_final_read():
    evidence = campaign()
    assert not verdict(evidence)["accepted"]
    evidence.add(sample(86400, final=True))
    result = verdict(evidence)
    assert result["accepted"] and result["observations"] == 2880
    assert result["final_verification_records"] == 1 and not result["entry_authorized"]
    stale = campaign("STALE_TICKS")
    stale.add(sample(86400, "STALE_TICKS", final=True))
    result = verdict(stale)
    assert result["collector_accepted"] and not result["quote_readiness_accepted"]
    assert not result["accepted"] and result["healthy_fraction"] == 0


@pytest.mark.parametrize("reason", ["TIMEOUT", "STALE_TICKS"])
def test_failing_final_verification_cannot_borrow_last_scheduled_quote(reason):
    evidence = campaign()
    evidence.add(sample(86400, reason, final=True))
    assert not verdict(evidence)["accepted"]


def test_fixed_slots_missing_reads_bursts_and_final_budget():
    evidence = SeparatedEvidence()
    for offset in range(0, 86400, 30):
        if offset % 300 == 0:
            continue
        record = sample(offset)
        evidence.add(record)
        evidence.add(record)
        evidence.add(sample(offset + 1))
    evidence.add(sample(86400, final=True))
    result = verdict(evidence)
    assert result["coverage_fraction"] == 0.9
    assert result["healthy_fraction"] == 0.9
    assert result["legacy_fresh_per_committed_fraction"] == 1
    assert not result["accepted"]
    late = campaign()
    late.add(sample(86431, final=True))
    assert not verdict(late, 86431)["accepted"]
    double = campaign()
    double.add(sample(86400, "STALE_TICKS", final=True))
    double.add(sample(86401, final=True))
    assert not verdict(double, 86401)["accepted"]


def test_failed_reads_do_not_count_as_complete_and_symbol_freshness_is_joint():
    evidence = campaign("TIMEOUT")
    evidence.add(sample(86400, final=True))
    result = verdict(evidence)
    assert result["coverage_fraction"] == 1 and result["complete_reads"] == 0
    assert not result["collector_accepted"]
    record = sample(0, "STALE_TICKS")
    record.body.health = record.body.health.model_copy(
        update={
            "quote_ages_seconds": {"EURUSD": 8, "USDJPY": 1},
            "quote_quality": {"EURUSD": "STALE", "USDJPY": "FRESH"},
        }
    )
    evidence = SeparatedEvidence()
    evidence.add(record)
    result = verdict(evidence, 1)
    assert result["per_symbol_fresh_fraction"] == {"EURUSD": 0, "USDJPY": 1}
    assert result["healthy_fraction"] == 0


def test_legacy_wire_and_plan_remain_byte_compatible(binding):
    body = TerminalObservation(
        binding_hash=binding.fingerprint(),
        state="HEALTHY",
        reason="CURRENT",
        failures=0,
        last_success_at=NOW,
        snapshot=FixtureReader()(binding, NOW),
    )
    wire = body.model_dump_json()
    assert '"health"' not in wire
    assert TerminalObservation.model_validate_json(wire).model_dump_json() == wire
    assert RunnerPlan().model_dump() == dict(
        duration_seconds=86400,
        interval_seconds=30,
        max_database_failures=12,
        database_retry_seconds=5,
        minimum_healthy_fraction=0.95,
        minimum_coverage_fraction=0.95,
        max_gap_seconds=180,
    )
    assert RunnerPlan(acceptance_version=2).model_dump()["final_verification_seconds"] == 30
    with pytest.raises(ValueError, match="v2 observations"):
        SeparatedEvidence().add(NS(body=body))


@pytest.mark.parametrize(
    "age,observer_current,entry_current",
    [
        (2, True, True),
        (2.000001, True, False),
        (5, True, False),
        (5.000001, False, False),
        (-0.000001, False, False),
    ],
)
def test_two_and_five_second_boundaries_unchanged(binding, age, observer_current, entry_current):
    at = NOW - timedelta(seconds=age)
    snapshot = FixtureReader()(binding, NOW)
    snapshot = snapshot.model_copy(
        update={"ticks": tuple(t.model_copy(update={"at": at}) for t in snapshot.ticks)}
    )
    assert (assess(snapshot, binding, NOW) == "CURRENT") == observer_current
    assert (health_reason(market_at(at), NOW, Policy()) is None) == entry_current
    with pytest.raises(ValueError):
        Policy(quote_age_seconds=5)


@pytest.mark.integration
def test_stale_reads_reset_transport_without_becoming_fresh(settings, binding, monkeypatch):
    clock, faults = FakeClock(NOW), []

    def collect(reader, pinned, now):
        fault = faults.pop(0) if faults else "STALE"
        if fault == "TIMEOUT":
            return None, "TIMEOUT"
        snapshot = FixtureReader(fault)(pinned, now)
        return snapshot.model_copy(
            update={
                "ticks": tuple(
                    t.model_copy(update={"at": NOW - timedelta(seconds=10)}) for t in snapshot.ticks
                )
            }
        ), None

    monkeypatch.setattr("fx_talanta.observer.supervisor.collect", collect)
    dsn, run = settings.runtime_dsn(Environment.PAPER), uuid4()
    with closing(Observer(dsn, binding, run, clock, policy_version=2)) as observer:
        for _ in range(20):
            record = observer.poll(FixtureReader())
            assert record.body.state == "DEGRADED" and record.body.health.complete_read
            assert record.body.health.transport_failures == 0
            assert record.body.last_success_at is None
            assert record.body.health.last_successful_read_at == clock.now()
            clock.advance(timedelta(seconds=30))
        faults[:] = ["TIMEOUT", "STALE", "TIMEOUT"]
        for reason in ("TIMEOUT", "STALE_TICKS", "TIMEOUT"):
            record = observer.poll(FixtureReader())
            assert record.body.reason == reason and record.body.state != "HALTED"
            assert record.body.health.transport_failures == (reason == "TIMEOUT")
            clock.advance(timedelta(seconds=30))
    with pytest.raises(ValueError, match="new run ID"):
        Observer(dsn, binding, run, clock)


@pytest.mark.integration
@pytest.mark.parametrize("fault", ["TIMEOUT", "READER_FAILED", "DISCONNECTED", "MISSING"])
def test_separate_exhaustion_limits_persist(settings, binding, monkeypatch, fault):
    clock = FakeClock(NOW)
    monkeypatch.setattr(
        "fx_talanta.observer.supervisor.collect",
        lambda reader, pinned, now: (
            (FixtureReader(fault)(pinned, now), None)
            if fault in {"MISSING", "DISCONNECTED"}
            else (None, fault)
        ),
    )
    dsn, run = settings.runtime_dsn(Environment.PAPER), uuid4()
    with closing(Observer(dsn, binding, run, clock, policy_version=2)) as observer:
        for index in range(10):
            record = observer.poll(FixtureReader())
            assert (record.body.state == "HALTED") == (index == 9)
            clock.advance(timedelta(seconds=301))
    with closing(Observer(dsn, binding, run, clock, policy_version=2)) as observer:
        assert observer.poll(FixtureReader()) == record


@pytest.mark.integration
@pytest.mark.parametrize("fault", ["ACCOUNT", "BUILD", "PATH", "CURRENCY", "FUTURE"])
def test_integrity_faults_still_halt_immediately(settings, binding, monkeypatch, fault):
    monkeypatch.setattr(
        "fx_talanta.observer.supervisor.collect",
        lambda reader, pinned, now: (FixtureReader(fault)(pinned, now), None),
    )
    with closing(
        Observer(
            settings.runtime_dsn(Environment.PAPER),
            binding,
            uuid4(),
            FakeClock(NOW),
            policy_version=2,
        )
    ) as observer:
        record = observer.poll(FixtureReader())
        assert record.body.state == "HALTED" and not record.body.health.complete_read


@pytest.mark.integration
@pytest.mark.parametrize("unknown_commit", [False, True])
def test_runner_final_read_and_db_recovery_no_duplicate_slot(
    settings, binding, monkeypatch, tmp_path, unknown_commit
):
    clock, calls, created = FakeClock(NOW), [], []
    dsn, run = settings.runtime_dsn(Environment.PAPER), uuid4()

    def collect(reader, pinned, now):
        calls.append(now)
        clock.advance(timedelta(milliseconds=100))
        return FixtureReader("STALE")(pinned, now), None

    monkeypatch.setattr("fx_talanta.observer.supervisor.collect", collect)

    def factory(_dsn, pinned, run_id, clock, **kwargs):
        observer = Observer(dsn, pinned, run_id, clock, **kwargs)
        created.append(observer)
        if unknown_commit and len(created) == 1:
            original = observer.poll

            def poll(reader, **kwargs):
                original(reader, **kwargs)
                raise psycopg.OperationalError("private connection detail")

            observer.poll = poll
        return observer

    args = (
        dsn,
        binding,
        run,
        tmp_path / "status.json",
        tmp_path / "stop",
        RunnerPlan(acceptance_version=2, duration_seconds=90),
    )
    kwargs = dict(
        clock=clock,
        sleep=lambda s: clock.advance(timedelta(seconds=s)),
        monotonic=lambda: (clock.now() - NOW).total_seconds(),
        observer_factory=factory,
        reader=FixtureReader(),
    )
    result = run_observer(*args, **kwargs)
    assert result["phase"] == "COMPLETE" and not result["evidence"]["accepted"]
    assert calls == [NOW + timedelta(seconds=i) for i in (0, 30, 60, 90)]
    assert result["evidence"]["observations"] == 3
    assert result["evidence"]["final_verification_records"] == 1
    assert result["database_errors"] == int(unknown_commit)
    rows = Repository(dsn, binding.account).history(correlation_id=run)
    assert len(rows) == 4 and rows[-1].body.health.final_verification
    assert run_observer(*args, **kwargs) == result and len(calls) == 4
    assert "private connection detail" not in json.dumps(result)


@pytest.mark.integration
def test_completeness_is_not_masked_by_staleness_and_clock_rollback_fails(
    settings, binding, monkeypatch
):
    clock = FakeClock(NOW)

    def collect(reader, pinned, now):
        snapshot = FixtureReader("STALE")(pinned, now)
        return snapshot.model_copy(
            update={
                "bars": tuple(
                    b.model_copy(update={"opened_at": b.opened_at - timedelta(hours=2)})
                    for b in snapshot.bars
                )
            }
        ), None

    monkeypatch.setattr("fx_talanta.observer.supervisor.collect", collect)
    with closing(
        Observer(settings.runtime_dsn(Environment.PAPER), binding, uuid4(), clock, policy_version=2)
    ) as observer:
        record = observer.poll(FixtureReader())
        assert record.body.reason == "MISSING_DATA"
        assert record.body.health.completeness_failures == 1
        clock._now -= timedelta(seconds=1)  # Inject a broken host clock deliberately.
        with pytest.raises(ValueError, match="backwards"):
            observer.poll(FixtureReader())
    with pytest.raises(ValueError, match="five seconds"):
        Observer(
            "unused",
            binding.model_copy(update={"tick_max_age_seconds": 6}),
            uuid4(),
            clock,
            policy_version=2,
        )


@pytest.mark.integration
@pytest.mark.parametrize("failure", ["TIMEOUT", "UNKNOWN_COMMIT"])
def test_failed_final_read_is_not_retried(settings, binding, monkeypatch, tmp_path, failure):
    clock, calls = FakeClock(NOW), []
    dsn, run = settings.runtime_dsn(Environment.PAPER), uuid4()

    def collect(reader, pinned, now):
        calls.append(now)
        return (
            (None, "TIMEOUT")
            if now >= NOW + timedelta(seconds=90) and failure == "TIMEOUT"
            else (FixtureReader()(pinned, now), None)
        )

    monkeypatch.setattr("fx_talanta.observer.supervisor.collect", collect)

    def factory(dsn, pinned, run, clock, **kwargs):
        observer = Observer(dsn, pinned, run, clock, **kwargs)
        original = observer.poll

        def poll(reader, **kwargs):
            result = original(reader, **kwargs)
            if kwargs.get("final_verification") and failure == "UNKNOWN_COMMIT":
                raise psycopg.OperationalError("unknown commit")
            return result

        observer.poll = poll
        return observer

    args = (
        dsn,
        binding,
        run,
        tmp_path / "status.json",
        tmp_path / "stop",
        RunnerPlan(acceptance_version=2, duration_seconds=90),
    )
    kwargs = dict(
        clock=clock,
        sleep=lambda s: clock.advance(timedelta(seconds=s)),
        monotonic=lambda: (clock.now() - NOW).total_seconds(),
        observer_factory=factory,
        reader=FixtureReader(),
    )
    result = run_observer(*args, **kwargs)
    assert not result["evidence"]["accepted"]
    assert result["final_verification_attempted"] and len(calls) == 4
    assert run_observer(*args, **kwargs) == result and len(calls) == 4
    assert result["phase"] == ("FAILED" if failure == "UNKNOWN_COMMIT" else "COMPLETE")


def test_forward_wall_clock_jump_cannot_substitute_elapsed_time(binding, tmp_path):
    clock = FakeClock(NOW)
    elapsed = [0]

    def sleep(seconds):
        elapsed[0] += seconds
        clock.advance(timedelta(seconds=seconds))

    def factory(*args, **kwargs):
        clock.advance(timedelta(hours=1))
        raise psycopg.OperationalError("offline")

    with pytest.raises(ValueError, match="diverged"):
        run_observer(
            "dbname=unused",
            binding,
            uuid4(),
            tmp_path / "status.json",
            tmp_path / "stop",
            RunnerPlan(acceptance_version=2),
            clock=clock,
            monotonic=lambda: elapsed[0],
            sleep=sleep,
            observer_factory=factory,
        )


@pytest.mark.parametrize("jump", [True, False])
def test_final_read_checks_wall_clock_against_independent_monotonic(binding, tmp_path, jump):
    clock, elapsed, records = FakeClock(NOW), [0.0], []

    def sleep(seconds):
        elapsed[0] += seconds
        clock.advance(timedelta(seconds=seconds))

    class Reader:
        last = None
        repo = NS(history=lambda **kwargs: records.copy())

        def poll(self, reader, *, final_verification=False):
            started = clock.now()
            if final_verification:
                clock.advance(timedelta(seconds=2))
                if not jump:
                    elapsed[0] += 2
            record = sample((clock.now() - NOW).total_seconds(), final=final_verification)
            record.body.health = record.body.health.model_copy(
                update={"collection_started_at": started}
            )
            self.last = record
            records.append(record)
            return record

        def close(self):
            pass

    path = tmp_path / "status.json"

    def run():
        return run_observer(
            "dbname=unused",
            binding,
            uuid4(),
            path,
            tmp_path / "stop",
            RunnerPlan(acceptance_version=2, duration_seconds=90),
            clock=clock,
            monotonic=lambda: elapsed[0],
            sleep=sleep,
            observer_factory=lambda *args, **kwargs: Reader(),
            reader=FixtureReader(),
        )

    if jump:
        with pytest.raises(ValueError, match="diverged"):
            run()
        result = json.loads(path.read_text())
        assert result["phase"] == "FAILED"
    else:
        result = run()
        assert result["phase"] == "COMPLETE"
        assert result["evidence"]["collector_gates"]["final_read"]
    assert len(records) == 4 and records[-1].body.health.final_verification
    assert result["evidence"]["final_verification_records"] == 1
    assert not result["evidence"]["accepted"]  # A 90-second fixture never qualifies.


@pytest.mark.parametrize("return_delay", [0, 30, 30.001])
def test_final_budget_includes_commit_acknowledgement(binding, tmp_path, return_delay):
    # Seed a complete synthetic day so an incorrect pass is observable, without
    # spending a day or touching an SDK/broker database.
    plan, run = RunnerPlan(acceptance_version=2), uuid4()
    clock = FakeClock(NOW + timedelta(days=1))
    records = list(campaign().records.values())
    path = tmp_path / "status.json"
    path.write_text(
        json.dumps(
            dict(
                run_id=str(run),
                binding_hash=binding.fingerprint(),
                plan=plan.model_dump(mode="json"),
                started_at=NOW.isoformat(),
                updated_at=records[-1].recorded_at.isoformat(),
                phase="RUNNING",
                database_errors=0,
                database_failure_streak=0,
                execution_enabled=False,
                last_attempt_slot=2879,
            )
        )
    )

    class Reader:
        last = records[-1]
        repo = NS(history=lambda **kwargs: records.copy())

        def poll(self, reader, *, final_verification=False):
            assert final_verification
            record = sample(86400, final=True)
            records.append(record)
            self.last = record
            # The observation timestamp precedes its transaction acknowledgement.
            clock.advance(timedelta(seconds=return_delay))
            return record

        def close(self):
            pass

    def invoke():
        return run_observer(
            "dbname=unused",
            binding,
            run,
            path,
            tmp_path / "stop",
            plan,
            clock=clock,
            monotonic=lambda: (clock.now() - NOW).total_seconds(),
            observer_factory=lambda *args, **kwargs: Reader(),
            reader=FixtureReader(),
        )

    result = invoke()
    assert result["evidence"]["accepted"] == (return_delay <= 30)
    assert result["phase"] == ("COMPLETE" if return_delay <= 30 else "FAILED")
    receipt = result["final_verification_receipt"]
    assert receipt["record_id"] == str(records[-1].record_id)
    assert datetime.fromisoformat(receipt["returned_at"]) == clock.now()
    if return_delay <= 30:
        # Simulate interruption after acknowledgement but before completion.
        result["phase"] = "STOPPED"
        path.write_text(json.dumps(result))
        assert invoke()["evidence"]["accepted"]
        result["final_verification_receipt"]["record_id"] = str(uuid4())
        path.write_text(json.dumps(result))
        mismatch = invoke()
        assert mismatch["phase"] == "FAILED"
        assert mismatch["reason"] == "FINAL_VERIFICATION_UNCONFIRMED"
        assert not mismatch["evidence"]["accepted"]
    else:
        assert result["reason"] == "FINAL_VERIFICATION_DEADLINE"
        assert invoke() == result  # A failed run remains terminal.
    assert len(records) == 2881


@pytest.mark.integration
def test_interrupted_final_commit_cannot_be_promoted_on_resume(
    settings, binding, monkeypatch, tmp_path
):
    clock, calls = FakeClock(NOW), []
    dsn, run = settings.runtime_dsn(Environment.PAPER), uuid4()

    def collect(reader, pinned, now):
        calls.append(now)
        return FixtureReader()(pinned, now), None

    monkeypatch.setattr("fx_talanta.observer.supervisor.collect", collect)

    def factory(dsn, pinned, run, clock, **kwargs):
        observer = Observer(dsn, pinned, run, clock, **kwargs)
        original = observer.poll

        def poll(reader, **kwargs):
            result = original(reader, **kwargs)
            if kwargs.get("final_verification"):
                raise KeyboardInterrupt  # Committed, but completion never acknowledged.
            return result

        observer.poll = poll
        return observer

    args = (
        dsn,
        binding,
        run,
        tmp_path / "status.json",
        tmp_path / "stop",
        RunnerPlan(acceptance_version=2, duration_seconds=90),
    )
    kwargs = dict(
        clock=clock,
        sleep=lambda s: clock.advance(timedelta(seconds=s)),
        monotonic=lambda: (clock.now() - NOW).total_seconds(),
        observer_factory=factory,
        reader=FixtureReader(),
    )
    first = run_observer(*args, **kwargs)
    assert first["phase"] == "STOPPED" and first["final_verification_attempted"]
    rows = Repository(dsn, binding.account).history(correlation_id=run)
    assert len(rows) == len(calls) == 4 and rows[-1].body.health.final_verification
    resumed = run_observer(*args, **kwargs)
    assert resumed["phase"] == "FAILED"
    assert resumed["reason"] == "FINAL_VERIFICATION_UNCONFIRMED"
    assert resumed["evidence"]["final_verification_records"] == 1
    assert not resumed["evidence"]["accepted"] and len(calls) == 4
