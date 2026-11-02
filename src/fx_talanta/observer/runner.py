"""Bounded read-only soak runner with restartable local health and DB evidence.

The status file contains no credentials or snapshots. PostgreSQL remains the
authority for observations/halts. A local OS lock fences status updates even while
the database is down; the Observer separately holds the database writer fence.
"""

import json
import os
import time
from collections import Counter
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated

import psycopg
from psycopg.conninfo import make_conninfo
from pydantic import Field

from fx_talanta.clock import SystemClock
from fx_talanta.domain.models import FrozenModel
from fx_talanta.observer.mt5 import MT5Reader
from fx_talanta.observer.supervisor import Observer
from fx_talanta.storage.offline import WriterBusy


class RunnerPlan(FrozenModel):
    duration_seconds: Annotated[int, Field(ge=1, le=604800)] = 86400
    interval_seconds: Annotated[int, Field(ge=1, le=300)] = 30
    max_database_failures: Annotated[int, Field(ge=1, le=60)] = 12
    database_retry_seconds: Annotated[int, Field(ge=1, le=60)] = 5
    minimum_healthy_fraction: Annotated[float, Field(ge=0, le=1)] = 0.95
    minimum_coverage_fraction: Annotated[float, Field(ge=0, le=1)] = 0.95
    max_gap_seconds: Annotated[int, Field(ge=1, le=3600)] = 180


@contextmanager
def status_lock(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_suffix(path.suffix + ".lock").open("a+b") as stream:
        if stream.tell() == 0:
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise WriterBusy("another runner owns this status file") from None
        try:
            yield
        finally:
            if os.name == "nt":
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)


def write_status(path, status):
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(status, stream, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def read_status(path, now=None):
    status = json.loads(Path(path).read_text(encoding="utf-8"))
    now = now or datetime.now(UTC)
    age = (now - datetime.fromisoformat(status["updated_at"])).total_seconds()
    active = status["phase"] in {"STARTING", "RUNNING", "DB_BACKOFF"}
    status["heartbeat_age_seconds"] = age
    status["heartbeat_state"] = (
        "STALE"
        if active and (age < 0 or age > status["heartbeat_limit_seconds"])
        else "CURRENT"
        if active
        else "STOPPED"
    )
    return status


class Evidence:
    def __init__(self):
        self.ids = set()
        self.reasons = Counter()
        self.healthy = 0
        self.first = self.last = None
        self.max_gap = 0
        self.last_state = self.last_reason = None

    def add(self, record):
        if record.record_id in self.ids:
            return
        if self.last is not None:
            gap = (record.recorded_at - self.last).total_seconds()
            if gap < 0:
                raise ValueError("observation evidence moved backwards")
            self.max_gap = max(self.max_gap, gap)
        self.ids.add(record.record_id)
        self.first = self.first or record.recorded_at
        self.last = record.recorded_at
        self.last_state, self.last_reason = record.body.state, record.body.reason
        self.reasons[record.body.reason] += 1
        self.healthy += record.body.state == "HEALTHY"

    def summary(self, started, now, plan, phase):
        elapsed = max(0, (now - started).total_seconds())
        count = len(self.ids)
        expected = max(1, min(elapsed, plan.duration_seconds) / plan.interval_seconds)
        gap = max(
            self.max_gap,
            ((self.first or now) - started).total_seconds(),
            (now - (self.last or started)).total_seconds(),
        )
        healthy_fraction = self.healthy / count if count else 0
        coverage = min(1, count / expected)
        span = (self.last - self.first).total_seconds() if self.last else 0
        gates = {
            "duration": elapsed >= plan.duration_seconds,
            "sample_span": span >= plan.duration_seconds - 2 * plan.interval_seconds,
            "coverage": coverage >= plan.minimum_coverage_fraction,
            "healthy_fraction": healthy_fraction >= plan.minimum_healthy_fraction,
            "gaps": gap <= plan.max_gap_seconds,
            "final_health": self.last_state == "HEALTHY",
            "minimum_24_hours": plan.duration_seconds >= 86400,
        }
        return {
            "observations": count,
            "healthy": self.healthy,
            "reasons": dict(self.reasons),
            "last_state": self.last_state,
            "last_reason": self.last_reason,
            "last_observed_at": self.last.isoformat() if self.last else None,
            "elapsed_seconds": elapsed,
            "observed_span_seconds": span,
            "healthy_fraction": healthy_fraction,
            "coverage_fraction": coverage,
            "max_gap_seconds": gap,
            "acceptance_gates": gates,
            "accepted": phase == "COMPLETE" and all(gates.values()),
        }


def run_observer(
    dsn,
    binding,
    run_id,
    status_path,
    stop_path,
    plan=None,
    *,
    clock=None,
    sleep=time.sleep,
    monotonic=time.monotonic,
    observer_factory=Observer,
    reader=None,
):
    plan = plan or RunnerPlan()
    clock = clock or SystemClock()
    reader = reader or MT5Reader()
    if binding.source == "MT5":
        binding.require_permissions()
    status_path, stop_path = Path(status_path), Path(stop_path)
    if status_path.resolve() == stop_path.resolve():
        raise ValueError("status and stop files must differ")
    # Bounds database statement execution as well as connection establishment.
    dsn = make_conninfo(dsn, connect_timeout=5, options="-c statement_timeout=5000")
    with status_lock(status_path):
        return _run(
            dsn,
            binding,
            run_id,
            status_path,
            stop_path,
            plan,
            clock,
            sleep,
            monotonic,
            observer_factory,
            reader,
        )


def _run(dsn, binding, run_id, path, stop_path, plan, clock, sleep, monotonic, factory, reader):
    identity = {
        "run_id": str(run_id),
        "binding_hash": binding.fingerprint(),
        "plan": plan.model_dump(mode="json"),
    }
    existed = path.exists()
    now = clock.now()
    if existed:
        status = json.loads(path.read_text(encoding="utf-8"))
        if any(status.get(k) != v for k, v in identity.items()):
            raise ValueError("restart cannot change runner identity, binding or plan")
        if status["phase"] in {"COMPLETE", "HALTED", "FAILED"}:
            return status
        if now < datetime.fromisoformat(status["updated_at"]):
            raise ValueError("runner clock moved backwards on restart")
    else:
        status = {
            **identity,
            "started_at": now.isoformat(),
            "phase": "STARTING",
            "database_errors": 0,
            "database_failure_streak": 0,
            "execution_enabled": False,
            "reason": "STARTING",
        }
    started = datetime.fromisoformat(status["started_at"])
    deadline = started + timedelta(seconds=plan.duration_seconds)
    if binding.time_policy_until and deadline >= binding.time_policy_until:
        raise ValueError("clock qualification must cover the entire planned run")
    status["deadline"] = deadline.isoformat()
    status["heartbeat_limit_seconds"] = (
        max(60, plan.interval_seconds) + binding.call_timeout_seconds + 10
    )
    observer, evidence = None, Evidence()
    previous_wall = now

    def publish():
        status["updated_at"] = clock.now().isoformat()
        status["evidence"] = evidence.summary(started, clock.now(), plan, status["phase"])
        write_status(path, status)

    def close():
        nonlocal observer
        if observer is not None:
            try:
                observer.close()
            finally:
                observer = None

    publish()
    try:
        while True:
            tick_start = monotonic()
            now = clock.now()
            if now < previous_wall:
                raise ValueError("runner clock moved backwards")
            previous_wall = now
            if stop_path.exists():
                status.update(phase="STOPPED", reason="STOP_FILE")
                break
            delay = plan.interval_seconds
            try:
                if observer is None:
                    observer = factory(dsn, binding, run_id, clock)
                    records = observer.repo.history(correlation_id=run_id)
                    if not existed and not evidence.ids and records:
                        raise ValueError(
                            "existing observation run requires its original status file"
                        )
                    evidence = Evidence()
                    for record in records:
                        evidence.add(record)
                    existed = True
                if observer.last and observer.last.body.state == "HALTED":
                    status.update(phase="HALTED", reason=observer.last.body.reason)
                    break
                if now >= deadline:
                    status.update(phase="COMPLETE", reason="DURATION_REACHED")
                    break
                record = observer.poll(reader)
                evidence.add(record)
                status.update(database_failure_streak=0, phase="RUNNING", reason=record.body.reason)
                if record.body.state == "HALTED":
                    status["phase"] = "HALTED"
                    break
            except (psycopg.OperationalError, psycopg.InterfaceError, psycopg.errors.QueryCanceled):
                close()
                status["database_errors"] += 1
                status["database_failure_streak"] += 1
                status.update(phase="DB_BACKOFF", reason="DATABASE_UNAVAILABLE")
                if clock.now() >= deadline:
                    status.update(phase="FAILED", reason="DATABASE_UNAVAILABLE_AT_DEADLINE")
                    break
                if status["database_failure_streak"] >= plan.max_database_failures:
                    status.update(phase="FAILED", reason="DATABASE_RETRY_LIMIT")
                    break
                delay = min(
                    60,
                    plan.database_retry_seconds
                    * 2 ** min(6, status["database_failure_streak"] - 1),
                )
            publish()
            remaining = max(
                0, min(delay - (monotonic() - tick_start), (deadline - clock.now()).total_seconds())
            )
            # A stop-file request is noticed within one second between bounded polls.
            until = monotonic() + remaining
            while monotonic() < until and not stop_path.exists():
                sleep(min(1, until - monotonic()))
    except KeyboardInterrupt:
        status.update(phase="STOPPED", reason="INTERRUPTED")
    except Exception:
        # Never persist SDK/database error messages, which may contain private data.
        status.update(phase="FAILED", reason="RUNNER_ERROR")
        publish()
        raise
    finally:
        close()
    publish()
    return status
