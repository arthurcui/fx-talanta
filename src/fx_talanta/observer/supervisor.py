"""Bounded child-process collection with durable, account-bound outcomes.

Only trusted in-process reader implementations may be supplied; the subprocess is
a timeout boundary, not a sandbox for untrusted code. There is no order interface.
"""

import multiprocessing
from datetime import timedelta
from threading import RLock
from time import monotonic

import psycopg
from pydantic import ValidationError

from fx_talanta.domain.models import (
    ObservationDiagnostic,
    ObservationHealth,
    Record,
    TerminalObservation,
    TerminalSnapshot,
    Versions,
)
from fx_talanta.observer.contracts import Binding, DiagnosticReason, invalid, windows_path
from fx_talanta.observer.mt5 import MT5Reader, ObservationFailure
from fx_talanta.storage.offline import WRITER_LOCK, WriterBusy
from fx_talanta.storage.repository import Repository

# Share the archive/gateway ownership fence: exports must not race this writer.
OBSERVER_LOCK = WRITER_LOCK
MAX_MESSAGE = 1024 * 1024


def _collect(sender, reader, binding, now):
    try:
        result = reader(binding, now)
        payload = result.model_dump_json().encode()
        if len(payload) > MAX_MESSAGE:
            diagnostic = invalid("PAYLOAD_LIMIT", stage="READER").diagnostic
            sender.send_bytes(b"DIAGNOSTIC:" + diagnostic.model_dump_json().encode())
        else:
            sender.send_bytes(payload)
    except ObservationFailure as error:
        if isinstance(error.reason, DiagnosticReason):
            sender.send_bytes(b"DIAGNOSTIC:" + error.reason.diagnostic.model_dump_json().encode())
        else:
            sender.send_bytes(("ERROR:" + error.reason).encode())
    except BaseException:
        # Never send exception messages, credentials or arbitrary native diagnostics.
        sender.send_bytes(b"FAILED")
    finally:
        sender.close()


def collect(reader, binding, now):
    ctx = multiprocessing.get_context("spawn")
    receiver, sender = ctx.Pipe(duplex=False)
    process = ctx.Process(target=_collect, args=(sender, reader, binding, now), daemon=True)
    deadline = monotonic() + binding.call_timeout_seconds
    try:
        process.start()
        sender.close()
        if not receiver.poll(max(0, deadline - monotonic())):
            return None, "TIMEOUT"
        try:
            payload = receiver.recv_bytes(MAX_MESSAGE)
        except (EOFError, OSError):
            return None, "READER_FAILED"
        if payload == b"FAILED":
            return None, "READER_FAILED"
        if payload.startswith(b"DIAGNOSTIC:"):
            try:
                diagnostic = ObservationDiagnostic.model_validate_json(payload.split(b":", 1)[1])
                return None, DiagnosticReason(diagnostic)
            except ValueError:
                return None, invalid("SNAPSHOT_SCHEMA", stage="TRANSPORT")
        if payload.startswith(b"ERROR:"):
            return None, payload.decode().split(":", 1)[1]
        try:
            return TerminalSnapshot.model_validate_json(payload), None
        except ValidationError as error:
            return None, invalid(
                "SNAPSHOT_SCHEMA", stage="TRANSPORT", violations=error.error_count()
            )
        except ValueError:
            return None, invalid("SNAPSHOT_SCHEMA", stage="TRANSPORT")
    finally:
        receiver.close()
        sender.close()
        if process.pid is not None:
            process.join(timeout=0.1)
            if process.is_alive():
                process.terminate()
                process.join(timeout=1)
            if process.is_alive():
                process.kill()
                process.join(timeout=1)
            if process.is_alive():
                raise RuntimeError("observer child could not be stopped; refusing another poll")
            process.close()


def assess(snapshot, binding, now, *, quote_freshness=True):
    if snapshot.account_before != binding.account or snapshot.account_after != binding.account:
        return "IDENTITY_MISMATCH"
    if windows_path(snapshot.terminal_path) != windows_path(binding.terminal_path) or windows_path(
        snapshot.data_path
    ) != windows_path(binding.data_path):
        return "PATH_MISMATCH"
    if snapshot.build != binding.expected_build:
        return "BUILD_CHANGED"
    if snapshot.currency != binding.expected_currency:
        return "CURRENCY_MISMATCH"
    if binding.source == "MT5":
        if any(
            getattr(snapshot, name) != getattr(binding, name)
            for name in (
                "sdk_time_offset_seconds",
                "time_policy_from",
                "time_policy_until",
                "time_policy_evidence",
            )
        ):
            return invalid("CLOCK_POLICY_MISMATCH")
        if snapshot.company != binding.expected_company:
            return "COMPANY_MISMATCH"
        if snapshot.margin_mode != binding.expected_margin_mode:
            return "MODE_MISMATCH"
    if not snapshot.connected and quote_freshness:
        return "DISCONNECTED"
    if not snapshot.history_from <= snapshot.history_to <= snapshot.observed_at <= now:
        return invalid("SNAPSHOT_TIME_ORDER")
    if any(t.at > snapshot.observed_at for t in snapshot.ticks):
        return invalid("FUTURE_TICK")
    if any(
        b.opened_at + timedelta(seconds=b.period_seconds) > snapshot.observed_at
        for b in snapshot.bars
    ):
        return invalid("INCOMPLETE_BAR")
    for items in (snapshot.positions, snapshot.orders, snapshot.deals, snapshot.history_orders):
        if len({item.ticket for item in items}) != len(items):
            return invalid("DUPLICATE_TICKET")
    if any(
        item.at > snapshot.observed_at
        or (item.done_at is not None and item.done_at > snapshot.observed_at)
        for item in (
            *snapshot.positions,
            *snapshot.orders,
            *snapshot.deals,
            *snapshot.history_orders,
        )
    ):
        return invalid("FUTURE_ACCOUNT_ITEM")
    if not snapshot.connected:
        return "DISCONNECTED"
    expected = set(binding.symbols)
    if (
        not snapshot.history_complete
        or {s.symbol for s in snapshot.symbols} != expected
        or len(snapshot.symbols) != len(expected)
        or {t.symbol for t in snapshot.ticks} != expected
        or len(snapshot.ticks) != len(expected)
        or {(b.symbol, b.period_seconds) for b in snapshot.bars}
        != {(s, p) for s in expected for p in (900, 3600)}
    ):
        return "MISSING_DATA"
    if quote_freshness and any(
        (now - t.at).total_seconds() > binding.tick_max_age_seconds for t in snapshot.ticks
    ):
        return "STALE_TICKS"
    for symbol in expected:
        for period in (900, 3600):
            latest = max(
                b.opened_at + timedelta(seconds=period)
                for b in snapshot.bars
                if b.symbol == symbol and b.period_seconds == period
            )
            if (snapshot.observed_at - latest).total_seconds() >= period:
                return "MISSING_DATA"
    return "CURRENT"


class Observer:
    def __init__(self, dsn, binding, run_id, clock, *, policy_version=1):
        if policy_version not in (1, 2):
            raise ValueError("unknown observation policy")
        if policy_version == 2 and binding.tick_max_age_seconds > 5:
            raise ValueError("v2 quote freshness cannot exceed five seconds")
        self.policy_version = policy_version
        self._mutex = RLock()
        self.binding = Binding.model_validate(binding.model_dump(mode="json"))
        self.run_id, self.clock = run_id, clock
        self.repo = Repository(dsn, binding.account)
        self.conn = psycopg.connect(dsn, autocommit=True)
        try:
            if not self.conn.execute(
                "SELECT pg_try_advisory_lock(%s)", (OBSERVER_LOCK,)
            ).fetchone()[0]:
                raise WriterBusy("another observer owns this fixture account")
            self.last = None
            for record in self.repo.history(correlation_id=run_id):
                if not isinstance(record.body, TerminalObservation):
                    raise ValueError("observer run contains unrelated records")
                if record.body.binding_hash != self.binding.fingerprint():
                    raise ValueError("restart cannot change the observer binding or policy")
                if (record.body.health is not None) != (policy_version == 2):
                    raise ValueError("new observation policy requires a new run ID")
                self.last = record
        except BaseException:
            self.conn.close()
            raise

    def close(self):
        with self._mutex:
            self.conn.close()

    def poll(self, reader, *, final_verification=False):
        with self._mutex:
            return self._poll(reader, final_verification=final_verification)

    def _poll(self, reader, *, final_verification=False):
        if final_verification and self.policy_version != 2:
            raise ValueError("final verification requires policy v2")
        if self.binding.source == "MT5":
            self.binding.require_permissions()
            if type(reader) is not MT5Reader:
                raise ValueError("demo observations require the MT5 reader")
        elif isinstance(reader, MT5Reader):
            raise ValueError("MT5 reader cannot write fixture evidence")
        self.repo._check_binding(self.conn)
        if not self.conn.execute(
            "SELECT 1 FROM pg_locks WHERE locktype='advisory' AND pid=pg_backend_pid() "
            "AND classid=0 AND objid=%s AND objsubid=1 AND granted",
            (OBSERVER_LOCK,),
        ).fetchone():
            raise WriterBusy("observer session lost ownership")
        guard = self.conn.execute(
            "SELECT status FROM fx.restore_history ORDER BY sequence DESC LIMIT 1"
        ).fetchone()
        if guard and guard[0] != "RELEASED":
            raise ValueError("restore has not been verified")
        now = self.clock.now()
        previous = self.last.body if self.last else None
        if self.last and now < self.last.recorded_at:
            raise ValueError("observer clock moved backwards")
        if previous and (
            previous.state == "HALTED"
            or (not final_verification and previous.next_retry_at and now < previous.next_retry_at)
        ):
            return self.last
        snapshot, reason = collect(reader, self.binding, now)
        checked_at = self.clock.now()
        if checked_at < now:
            raise ValueError("observer clock moved backwards during collection")
        reason = reason or assess(
            snapshot, self.binding, checked_at, quote_freshness=self.policy_version == 1
        )
        if (
            self.policy_version == 2
            and reason == "CURRENT"
            and any(
                (checked_at - t.at).total_seconds() > self.binding.tick_max_age_seconds
                for t in snapshot.ticks
            )
        ):
            reason = "STALE_TICKS"
        permanent = reason in {
            "INVALID_DATA",
            "IDENTITY_MISMATCH",
            "PATH_MISMATCH",
            "BUILD_CHANGED",
            "CURRENCY_MISMATCH",
            "MODE_MISMATCH",
            "COMPANY_MISMATCH",
            "SDK_MISMATCH",
        }
        failures = 0 if reason == "CURRENT" else (previous.failures if previous else 0) + 1
        state = "HEALTHY" if reason == "CURRENT" else "DEGRADED"
        if reason in {"TIMEOUT", "READER_FAILED", "DISCONNECTED"}:
            state = "BACKOFF"
        health = None
        exhausted = failures >= self.binding.max_failures
        if self.policy_version == 2:
            old = previous.health if previous else None
            transport_failed = reason in {"TIMEOUT", "READER_FAILED", "DISCONNECTED"}
            complete = reason in {"CURRENT", "STALE_TICKS"}
            transport_failures = (
                (old.transport_failures if old else 0) + 1
                if transport_failed
                else 0
                if complete
                else (old.transport_failures if old else 0)
            )
            completeness_failures = (
                (old.completeness_failures if old else 0) + 1
                if reason == "MISSING_DATA"
                else 0
                if complete
                else (old.completeness_failures if old else 0)
            )
            ages = (
                {
                    t.symbol: (checked_at - t.at).total_seconds()
                    for t in snapshot.ticks
                    if t.symbol in self.binding.symbols
                }
                if snapshot and not permanent
                else {}
            )
            health = ObservationHealth(
                collection_started_at=now,
                integrity="INVALID" if permanent else "VALID" if snapshot else "UNVERIFIED",
                transport="READ_FAILED"
                if transport_failed
                else "READ_OK"
                if snapshot and not permanent
                else "UNVERIFIED",
                complete_read=complete,
                quote_max_age_seconds=self.binding.tick_max_age_seconds,
                transport_failures=transport_failures,
                completeness_failures=completeness_failures,
                last_successful_read_at=checked_at
                if snapshot and not permanent and not transport_failed
                else old.last_successful_read_at
                if old
                else None,
                quote_ages_seconds=ages,
                quote_quality={
                    s: "UNKNOWN"
                    if s not in ages or ages[s] < 0
                    else "STALE"
                    if ages[s] > self.binding.tick_max_age_seconds
                    else "FRESH"
                    for s in self.binding.symbols
                },
                final_verification=final_verification,
            )
            exhausted = max(transport_failures, completeness_failures) >= self.binding.max_failures
        if permanent or exhausted:
            state = "HALTED"
        last_success = (
            checked_at if state == "HEALTHY" else (previous.last_success_at if previous else None)
        )
        # Valid but stale/incomplete reads remain eligible at the runner's next
        # scheduled poll. Only transport failures suppress new collections.
        # Keep an immediate deadline for DEGRADED to preserve the wire contract.
        body = TerminalObservation(
            binding_hash=self.binding.fingerprint(),
            state=state,
            reason=reason,
            failures=failures,
            last_success_at=last_success,
            next_retry_at=(
                checked_at
                + timedelta(
                    seconds=min(
                        300,
                        self.binding.backoff_seconds
                        * 2 ** ((health.transport_failures if health else failures) - 1),
                    )
                    if state == "BACKOFF"
                    else 0
                )
                if failures and state != "HALTED"
                else None
            ),
            snapshot=None if permanent else snapshot,
            health=health,
            diagnostic=getattr(reason, "diagnostic", None),
        )
        record = Record(
            account=self.binding.account,
            recorded_at=checked_at,
            correlation_id=self.run_id,
            body=body,
            provenance="BROKER_OBSERVATION" if self.binding.source == "MT5" else "SCRIPTED_FIXTURE",
            versions=Versions(component="observer/5"),
        )
        with self.conn.transaction():
            self.repo.append_in(self.conn, (record,))
        self.last = record
        return record
