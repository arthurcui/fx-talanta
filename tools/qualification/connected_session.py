"""One explicit, bounded localhost no-order session; never install or attach an EA.

Run as a child with an external 360-second deadline. Runtime PAPER credentials
must be in FX_SHADOW_RUNTIME_DSN; this program never bootstraps a database or
reads administrative credentials. Expired/retired authority is never adopted.
"""

import argparse
import hashlib
import json
import os
import re
import secrets
import ssl
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import psycopg
from psycopg.conninfo import conninfo_to_dict

from fx_talanta.acceptance.clock_probe import probe
from fx_talanta.acceptance.probe import write_json
from fx_talanta.connected_shadow.authority import Authority, PostgresAuthorityStore
from fx_talanta.connected_shadow.host_clock import HostClock
from fx_talanta.connected_shadow.inputs import canonical_hash, capture_once, normalize
from fx_talanta.connected_shadow.listener import listener
from fx_talanta.connected_shadow.service import PATH, ConnectedApplication, Service
from fx_talanta.observer.contracts import Binding
from fx_talanta.observer.mt5 import SDKClock
from fx_talanta.shadow.store import PostgresStore
from fx_talanta.shadow.work import scope_for
from tools.qualification.connected_capture import safe_reason

ROOT = Path(__file__).resolve().parents[2]


def exclusive_bytes(path, content):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())


def atomic_status(path, value):
    temporary = path.with_name(path.name + "." + secrets.token_hex(6) + ".pending")
    exclusive_bytes(temporary, (json.dumps(value, indent=2, allow_nan=False) + "\n").encode())
    # Windows readers can briefly deny replacement even though the writer has
    # directory permission. Retry only those sharing/access errors within a
    # 100 ms retry window; never truncate the old snapshot, discard pending bytes, or
    # extend a session/clock/lease deadline. Other I/O errors remain fatal.
    cutoff = time.monotonic() + 0.1
    for attempt in range(11):
        if attempt and time.monotonic() >= cutoff:
            raise ValueError("STATUS_REPLACE_BLOCKED")
        try:
            os.replace(temporary, path)
            return
        except PermissionError as error:
            if getattr(error, "winerror", None) not in {5, 32, 33}:
                raise
            remaining = cutoff - time.monotonic()
            if attempt == 10 or remaining <= 0:
                raise ValueError("STATUS_REPLACE_BLOCKED") from None
            time.sleep(min(0.01, remaining))


def check_runtime_dsn(dsn):
    connection = conninfo_to_dict(dsn)
    if connection.get("host") not in {"127.0.0.1", "localhost", "::1"} or connection.get(
        "hostaddr", "127.0.0.1"
    ) not in {"127.0.0.1", "::1"}:
        raise ValueError("LOOPBACK_RUNTIME_DATABASE_REQUIRED")
    with psycopg.connect(dsn, connect_timeout=2) as db:
        db.execute("SET LOCAL statement_timeout='2000ms'")
        identity = db.execute(
            "SELECT current_user,session_user,current_database(),"
            "rolsuper,rolcreatedb,rolcreaterole "
            "FROM pg_roles WHERE rolname=current_user"
        ).fetchone()
        if (
            identity is None
            or identity[0] != identity[1]
            or identity[0] != identity[2] + "_writer"
            or not identity[2].startswith("fx_connected_")
            or not identity[2].endswith("_paper")
            or any(identity[3:])
        ):
            raise ValueError("PAPER_RUNTIME_ROLE_REQUIRED")


def stores(dsn, account, stream):
    check_runtime_dsn(dsn)
    return (
        PostgresAuthorityStore(dsn, account, reuse_connection=True),
        PostgresStore(dsn, account, stream, reuse_connection=True),
    )


def tls_material(cert, key):
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(cert, key)


def load_sdk():
    import MetaTrader5

    return MetaTrader5


def drain_listener(server, timeout=5):
    """Wait for the four bounded owned handlers after closing accepted sockets."""
    slots = getattr(server, "slots", None)
    if slots is None:  # Deterministic fake listener; real listener always has four slots.
        return True
    end, acquired = time.monotonic() + timeout, 0
    try:
        for _ in range(4):
            if not slots.acquire(timeout=max(0, end - time.monotonic())):
                return False
            acquired += 1
        return True
    finally:
        for _ in range(acquired):
            slots.release()


@dataclass(frozen=True)
class Runtime:
    probe: object = probe
    clock: object = HostClock
    stores: object = stores
    listener: object = listener
    tls_material: object = tls_material
    capture: object = capture_once
    load_sdk: object = load_sdk
    monotonic: object = time.monotonic
    sleep: object = time.sleep


class ClockSlot:
    """Refresh measurements without clearing an invalid clock or changing its midpoint."""

    def __init__(self, clock, *, monotonic_ns=time.monotonic_ns):
        self.clock = clock
        self.monotonic_ns = monotonic_ns
        self.lock = threading.Lock()
        self.last_now = -1

    def _read(self):
        now, error = self.clock.read()
        if now < self.last_now:
            raise ValueError("HOST_CLOCK_REGRESSION")
        if not 0 <= error <= 100:
            raise ValueError("HOST_CLOCK_UNVERIFIED")
        self.last_now = now
        return now, error

    def __call__(self):
        with self.lock:
            return self._read()

    def refresh(self, replacement):
        with self.lock:
            old_before = self.monotonic_ns()
            old, old_error = self._read()  # expired/invalid clocks are not repaired here
            old_after = self.monotonic_ns()
            new_before = self.monotonic_ns()
            new, new_error = replacement.read()
            new_after = self.monotonic_ns()
            if not old_before <= old_after <= new_before <= new_after:
                raise ValueError("HOST_MONOTONIC_CHANGED")
            # The intervals describe different sample instants. Project only the
            # comparison interval by the bracketed elapsed time; neither the new
            # clock midpoint nor quote age/uncertainty receives an adjustment.
            minimum_elapsed = (new_before - old_after) // 1_000_000
            maximum_elapsed = (new_after - old_before + 999_999) // 1_000_000
            if (
                new < old
                or new + new_error < old - old_error + minimum_elapsed
                or new - new_error > old + old_error + maximum_elapsed
            ):
                raise ValueError("HOST_CLOCK_INTERVAL_DISJOINT")
            self.clock = replacement
            return self._read()


def startup_renew(authority, store, client, incarnation, epoch, clock_upper, monotonic, cutoff):
    """Atomic check-and-renew under the same authority→backend lock order as Service.

    This narrow startup exception expires after 60 seconds and cannot race a
    committed authenticated exchange. It never claims or revives a lease.
    """
    with authority.store.transaction() as events:
        upper = clock_upper()
        state = authority._state(events, upper)
        authority._valid(state, client, incarnation, epoch, upper)
        with store.transaction() as peer:
            if any(e["kind"] == "exchange" for e in peer.records):
                return False
            if monotonic() >= cutoff:
                raise ValueError("NATIVE_ATTACH_WINDOW_EXPIRED")
            state = dict(state, kind="renew", at_ms=upper, expires_ms=upper + 15000)
            events.append(state)
            authority._valid(state, client, incarnation, epoch, clock_upper())
            if monotonic() >= cutoff:
                raise ValueError("NATIVE_ATTACH_WINDOW_EXPIRED")
    return True


def native_config(binding, *, endpoint, client, incarnation, epoch, deadline, names, key):
    fields = (
        "connected-config/1",
        endpoint,
        scope_for(binding.account),
        client,
        incarnation,
        str(epoch),
        binding.account.login,
        binding.account.server,
        binding.fingerprint(),
        str(deadline),
        names["journal"],
        names["checkpoint"],
        key.decode("ascii"),
    )
    if len(fields) != 13 or any(any(c in f for c in "\t\r\n|") for f in fields):
        raise ValueError("NATIVE_CONFIG_FIELDS")
    return "\t".join(fields).encode("ascii")  # No newline: native file is exactly one record.


def session(
    binding_path,
    output,
    cert,
    tls_key,
    dsn,
    *,
    seconds=300,
    port=8443,
    bootstrap_authority=False,
    conversion_symbol=None,
    runtime=None,
):
    runtime = runtime or Runtime()
    if type(seconds) is not int or not 1 <= seconds <= 300 or not 1 <= port <= 65535:
        raise ValueError("BOUNDED_SESSION_REQUIRED")
    output.mkdir(parents=True, exist_ok=False)
    summary = dict(
        status="STARTING",
        phase="PREFLIGHT",
        execution_enabled=False,
        connected_execution_accepted=False,
        timestamp_mapping_qualified=False,
        native_acknowledgement_verified=False,
        campaign_started=False,
        receipt_count=0,
    )
    server = server_thread = None
    events = (output / "private-events.jsonl").open("x", encoding="utf-8", newline="\n")
    event_lock = threading.Lock()

    def event(kind, **details):
        row = dict(event=kind, **details)
        with event_lock:
            events.write(json.dumps(row, allow_nan=False) + "\n")
            events.flush()
            os.fsync(events.fileno())

    original = None
    service = None
    try:
        original = binding_path.read_bytes()
        binding = Binding.model_validate_json(original)
        binding.require_permissions()
        if binding.source != "MT5" or binding.account.venue != "BROKER_DEMO":
            raise ValueError("PINNED_DEMO_REQUIRED")
        runtime.tls_material(cert, tls_key)
        ntp = runtime.probe()
        write_json(output / "clock-000.json", ntp)
        clock = ClockSlot(runtime.clock(ntp), monotonic_ns=lambda: int(runtime.monotonic() * 1e9))
        now, error = clock()
        SDKClock(binding).check(datetime.fromtimestamp(now / 1000, UTC))
        if binding.time_policy_until is None:
            raise ValueError("BOUNDED_BINDING_REQUIRED")
        deadline = min(
            now + seconds * 1000, int(binding.time_policy_until.timestamp() * 1000) - error - 1
        )
        if deadline <= now + error + 1000:
            raise ValueError("BINDING_EXPIRES_BEFORE_SESSION")
        session_id = uuid4()
        client, incarnation, key = (
            secrets.token_hex(32),
            secrets.token_hex(32),
            secrets.token_hex(24).encode(),
        )
        stem = "fxcs-" + session_id.hex[:16]
        names = dict(
            config=stem + ".tsv", journal=stem + ".journal", checkpoint=stem + ".checkpoint"
        )
        authority_store, backend_store = runtime.stores(dsn, binding.account, session_id)
        authority = Authority(authority_store, binding.account, bootstrap=bootstrap_authority)
        service = Service(
            backend_store,
            authority,
            binding.account,
            client,
            incarnation,
            1,
            key,
            clock,
            bootstrap=True,
        )
        claimed_at = service.clock_upper()
        lease = authority.claim(client, incarnation, claimed_at)
        if lease.epoch != service.epoch:
            raise ValueError("INITIAL_AUTHORITY_EPOCH_REQUIRED")
        event("EXPLICIT_INITIAL_CLAIM", epoch=lease.epoch, upper_ms=claimed_at)
        server = runtime.listener(
            ConnectedApplication(service, audit=event), cert, tls_key, port=port, audit=event
        )
        endpoint = f"https://127.0.0.1:{port}{PATH}"
        exclusive_bytes(
            output / names["config"],
            native_config(
                binding,
                endpoint=endpoint,
                client=client,
                incarnation=incarnation,
                epoch=lease.epoch,
                deadline=deadline,
                names=names,
                key=key,
            ),
        )
        write_json(
            output / "private-session.json",
            dict(
                session_id=str(session_id),
                client=client,
                incarnation=incarnation,
                epoch=lease.epoch,
                account_scope=service.scope,
                stream_id=str(session_id),
                deadline_ms=deadline,
                binding_sha256=binding.fingerprint(),
                binding_file_sha256=hashlib.sha256(original).hexdigest(),
                certificate_sha256=hashlib.sha256(cert.read_bytes()).hexdigest(),
                native_files=names,
                execution_enabled=False,
            ),
        )
        server_thread = threading.Thread(
            target=server.serve_forever, kwargs={"poll_interval": 0.1}, daemon=True
        )
        server_thread.start()
        started = runtime.monotonic()
        cutoff = started + min(60, (deadline - now) / 1000)
        next_renew, next_clock = started + 5, started + 30
        peer_seen, capture_attempted, clock_number = False, False, 0
        summary.update(
            status="WAITING_FOR_NATIVE",
            phase="ATTACH",
            deadline_ms=deadline,
            native_attach_window_seconds=min(60, (deadline - now) / 1000),
        )
        atomic_status(output / "status.json", summary)
        event("LISTENER_STARTED_NO_ORDER", port=port)
        while True:
            at = runtime.monotonic()
            now, error = clock()
            if now + error >= deadline or at - started >= seconds:
                summary.update(service.status())
                summary.update(
                    status="COMPLETED" if summary["receipt_count"] == 2 else "INCOMPLETE",
                    phase="DEADLINE",
                )
                break
            status = service.status()
            if status["last_exchange_ms"] is not None and not peer_seen:
                with backend_store.transaction() as journal:
                    first_exchange = next(e for e in journal.records if e["kind"] == "exchange")
                if first_exchange["at_ms"] + error >= claimed_at + 60000:
                    raise ValueError("NATIVE_ATTACH_WINDOW_EXPIRED")
                peer_seen = True
                event("FIRST_AUTHENTICATED_EXCHANGE", at_ms=first_exchange["at_ms"])
            if not peer_seen:
                if at >= cutoff:
                    summary.update(
                        status="BLOCKED", phase="ATTACH", reason="NATIVE_ATTACH_WINDOW_EXPIRED"
                    )
                    break
                if at >= next_renew:
                    renewed = startup_renew(
                        authority,
                        backend_store,
                        client,
                        incarnation,
                        lease.epoch,
                        service.clock_upper,
                        runtime.monotonic,
                        cutoff,
                    )
                    if renewed:
                        event("STARTUP_SAME_OWNER_RENEWAL", elapsed_ms=int((at - started) * 1000))
                    next_renew = runtime.monotonic() + 5
            if at >= next_clock:
                clock_number += 1
                measured = runtime.probe()
                write_json(output / f"clock-{clock_number:03d}.json", measured)
                clock.refresh(runtime.clock(measured))
                ntp = measured
                next_clock = runtime.monotonic() + 30
                event("CLOCK_MEASUREMENT_REFRESHED", measurement=clock_number)
            if peer_seen and not capture_attempted:
                capture_attempted = True
                summary.update(phase="BROKER_CAPTURE", status="CAPTURING")
                atomic_status(output / "status.json", summary)
                if binding_path.read_bytes() != original:
                    raise ValueError("BINDING_CHANGED")
                _, bound = clock()
                event("ONE_BROKER_CAPTURE_STARTED")
                raw = runtime.capture(
                    runtime.load_sdk(),
                    binding,
                    clock_error_ms=bound,
                    clock_evidence_sha256=canonical_hash(ntp),
                    conversion_symbol=conversion_symbol,
                )
                raw["timestamp_mapping_qualified"] = False
                raw["capture_sha256"] = canonical_hash(
                    {k: v for k, v in raw.items() if k != "capture_sha256"}
                )
                write_json(output / "private-capture.json", raw)
                for symbol in ("EURUSD", "USDJPY"):
                    normalized = normalize(raw, symbol=symbol, side="BUY")
                    if (
                        normalized.snapshot is not None
                        or "TIMESTAMP_MAPPING_UNQUALIFIED" not in normalized.missing
                    ):
                        raise ValueError("UNQUALIFIED_INPUTS_CANNOT_BE_PROMOTED")
                    service.publish(raw, symbol)
                event(
                    "TWO_HOLD_OBSERVATIONS_PUBLISHED",
                    capture_sha256=raw["capture_sha256"],
                    work_deadline_ms=raw["measured_at_ms"] + 60000,
                )
                summary.update(status="OBSERVING_HOLD_RECEIPTS", phase="RECEIPTS")
            summary.update(service.status())
            atomic_status(output / "status.json", summary)
            runtime.sleep(0.25)
    except (Exception, KeyboardInterrupt) as error:
        reason = safe_reason(error)
        if isinstance(error, ValueError) and re.fullmatch(r"[A-Z_]{1,64}", str(error)):
            reason = str(error)
        summary.update(status="BLOCKED", reason=reason)
        event("SESSION_STOPPED_ON_FAILURE", reason=reason)
    finally:
        if server_thread is not None:
            server.shutdown()
            server_thread.join(timeout=3)
        if server is not None:
            server.server_close()
            if not drain_listener(server):
                summary.update(status="BLOCKED", reason="LISTENER_INFLIGHT_TIMEOUT")
        if original is not None:
            try:
                summary["binding_unchanged"] = binding_path.read_bytes() == original
            except OSError:
                summary["binding_unchanged"] = False
            if not summary["binding_unchanged"]:
                summary.update(status="BLOCKED", reason="BINDING_CHANGED")
        if service is not None:
            try:
                summary.update(service.status())
            except Exception:
                event("FINAL_CHANNEL_STATUS_UNAVAILABLE")
            try:
                with service.store.transaction() as journal:
                    summary["receipt_count"] = sum(e["kind"] == "receipt" for e in journal.records)
                    event(
                        "BACKEND_CHECKPOINT_RETAINED",
                        journal_hash=journal.tip,
                        journal_records=len(journal.records),
                    )
            except Exception:
                event("FINAL_BACKEND_CHECKPOINT_UNAVAILABLE")
                summary.update(status="BLOCKED", reason="FINAL_BACKEND_CHECKPOINT_UNAVAILABLE")
        if service is not None:
            for store in (service.store, service.authority.store):
                if hasattr(store, "close"):
                    try:
                        store.close()
                    except Exception:
                        summary.update(status="BLOCKED", reason="DATABASE_CLOSE_FAILED")
                        event("DATABASE_CLOSE_FAILED")
        summary["last_observed_channel_state"] = summary.get("channel_state", "DISCONNECTED")
        summary["channel_state"] = "DISCONNECTED"
        event("LISTENER_STOPPED_LEASE_NOT_RETIRED")
        try:
            atomic_status(output / "status.json", summary)
        except Exception as error:
            # A blocked mutable status file must not suppress the separate
            # terminal report or promote a partial run. Preserve both the old
            # complete snapshot and pending bytes for inspection; never retry
            # this finalization with a different filename or a longer deadline.
            summary["outcome_before_status_failure"] = dict(
                status=summary["status"], reason=summary.get("reason")
            )
            summary.update(
                status="BLOCKED",
                reason="FINAL_STATUS_UPDATE_FAILED",
                final_status_error=(
                    "STATUS_REPLACE_BLOCKED"
                    if isinstance(error, ValueError) and str(error) == "STATUS_REPLACE_BLOCKED"
                    else "STATUS_WRITE_FAILED"
                ),
                connected_execution_accepted=False,
            )
        finally:
            events.close()
        exclusive_bytes(
            output / "report.json", (json.dumps(summary, indent=2, allow_nan=False) + "\n").encode()
        )
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binding", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--certificate", type=Path, required=True)
    parser.add_argument("--certificate-key", type=Path, required=True)
    parser.add_argument("--seconds", type=int, default=300)
    parser.add_argument("--port", type=int, default=8443)
    parser.add_argument("--bootstrap-authority", action="store_true")
    parser.add_argument("--conversion-symbol")
    args = parser.parse_args()
    output = args.output.resolve()
    private = (ROOT / ".local").resolve()
    if not output.is_relative_to(private) or output == private:
        parser.error("use a NEW output directory in this checkout's .local")
    dsn = os.environ.get("FX_SHADOW_RUNTIME_DSN")
    if not dsn:
        parser.error("FX_SHADOW_RUNTIME_DSN is required; no administrative fallback")
    try:
        result = session(
            args.binding,
            output,
            args.certificate,
            args.certificate_key,
            dsn,
            seconds=args.seconds,
            port=args.port,
            bootstrap_authority=args.bootstrap_authority,
            conversion_symbol=args.conversion_symbol,
        )
    except Exception as error:
        result = dict(status="BLOCKED", reason=safe_reason(error), execution_enabled=False)
    print(json.dumps(result, allow_nan=False))


if __name__ == "__main__":
    main()
