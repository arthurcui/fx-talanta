"""No listener deployment or terminal access: deterministic session lifecycle seams."""

import json
import threading
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from fx_talanta.connected_shadow.authority import Authority
from fx_talanta.connected_shadow.inputs import capture_once
from fx_talanta.connected_shadow.service import hold_receipt
from fx_talanta.observer.contracts import Binding
from fx_talanta.shadow.store import SQLiteStore
from fx_talanta.shadow.wire import Frame
from tests.test_connected_capture import AdvancingSDK, Timer
from tests.test_connected_inputs import binding
from tools.qualification import connected_session
from tools.qualification.connected_session import ClockSlot, Runtime, session, startup_renew


def test_status_reader_conflict_preserves_old_snapshot_until_atomic_replacement(
    tmp_path, monkeypatch
):
    path = tmp_path / "status.json"
    old = b'{"status":"previous"}\n'
    path.write_bytes(old)
    original_replace = connected_session.os.replace
    attempts = []

    def conflict(source, destination):
        attempts.append(source)
        assert path.read_bytes() == old
        assert json.loads(source.read_bytes()) == {"status": "current"}
        if len(attempts) <= 2:
            error = PermissionError("synthetic Windows sharing conflict")
            error.winerror = 32
            raise error
        original_replace(source, destination)

    monkeypatch.setattr(connected_session.os, "replace", conflict)
    connected_session.atomic_status(path, {"status": "current"})
    assert len(attempts) == 3 and len(set(attempts)) == 1
    assert json.loads(path.read_bytes()) == {"status": "current"}
    assert not list(tmp_path.glob("*.pending"))


def test_status_persistent_reader_conflict_is_bounded_and_retains_both_snapshots(
    tmp_path, monkeypatch
):
    path = tmp_path / "status.json"
    path.write_text('{"status":"previous"}')
    elapsed, attempts = [0.0], []

    def denied(source, destination):
        attempts.append(source)
        error = PermissionError("synthetic Windows access denial")
        error.winerror = 5
        raise error

    monkeypatch.setattr(connected_session.os, "replace", denied)
    monkeypatch.setattr(connected_session.time, "monotonic", lambda: elapsed[0])
    monkeypatch.setattr(
        connected_session.time,
        "sleep",
        lambda seconds: elapsed.__setitem__(0, elapsed[0] + seconds),
    )
    with pytest.raises(ValueError, match="^STATUS_REPLACE_BLOCKED$"):
        connected_session.atomic_status(path, {"status": "current"})
    assert 0 < elapsed[0] <= 0.101 and len(attempts) <= 11
    assert json.loads(path.read_bytes()) == {"status": "previous"}
    pending = list(tmp_path.glob("*.pending"))
    assert len(pending) == 1 and json.loads(pending[0].read_bytes()) == {"status": "current"}


def test_status_other_permission_errors_are_not_retried(tmp_path, monkeypatch):
    calls = []

    def denied(*args):
        calls.append(args)
        raise PermissionError("synthetic non-Windows permission failure")

    monkeypatch.setattr(connected_session.os, "replace", denied)
    with pytest.raises(PermissionError):
        connected_session.atomic_status(tmp_path / "status.json", {"status": "current"})
    assert len(calls) == 1 and len(list(tmp_path.glob("*.pending"))) == 1


@pytest.mark.parametrize("after_sleep", [0.1, 1.0])
def test_status_does_not_attempt_replace_after_retry_cutoff(tmp_path, monkeypatch, after_sleep):
    path = tmp_path / "status.json"
    old = b'{"status":"previous"}\n'
    path.write_bytes(old)
    elapsed, attempts = [0.0], []

    def conflict(source, destination):
        attempts.append(elapsed[0])
        if len(attempts) > 1:
            pytest.fail("replacement attempted after the retry deadline")
        error = PermissionError("synthetic Windows sharing conflict")
        error.winerror = 32
        raise error

    monkeypatch.setattr(connected_session.os, "replace", conflict)
    monkeypatch.setattr(connected_session.time, "monotonic", lambda: elapsed[0])
    monkeypatch.setattr(
        connected_session.time, "sleep", lambda _: elapsed.__setitem__(0, after_sleep)
    )
    with pytest.raises(ValueError, match="^STATUS_REPLACE_BLOCKED$"):
        connected_session.atomic_status(path, {"status": "current"})
    assert attempts == [0.0] and path.read_bytes() == old
    pending = list(tmp_path.glob("*.pending"))
    assert len(pending) == 1 and json.loads(pending[0].read_bytes()) == {"status": "current"}


class FakeHostClock:
    def __init__(self, timer, error=10):
        self.timer, self.error = timer, error

    def read(self):
        return self.timer.now(), self.error


class FakeServer:
    def __init__(self, application):
        self.application = application
        self.stopped = threading.Event()
        self.closed = False

    def serve_forever(self, **kwargs):
        self.stopped.wait()

    def shutdown(self):
        self.stopped.set()

    def server_close(self):
        self.closed = True


def setup(tmp_path, *, peer=True, fail_capture=False):
    timer = Timer()
    at = datetime.fromtimestamp(timer.now() / 1000, UTC)
    values = binding().model_dump(mode="json")
    values.update(
        time_policy_from=(at - timedelta(seconds=5)).isoformat(),
        time_policy_until=(at + timedelta(minutes=10)).isoformat(),
        time_policy_evidence="PROVISIONAL_CONSISTENCY_ONLY:test",
    )
    pinned = Binding.model_validate(values)
    path = tmp_path / "binding.json"
    path.write_text(pinned.model_dump_json())
    cert, key = tmp_path / "cert.pem", tmp_path / "key.pem"
    cert.write_text("synthetic-certificate")
    key.write_text("synthetic-key")
    out = tmp_path / "session"
    state = {"ntp": 0, "capture": 0, "loads": 0, "nonce": 0, "peer_synced": False}
    authority_store = SQLiteStore(tmp_path / "authority.db", bootstrap=True)
    backend_store = SQLiteStore(tmp_path / "backend.db", bootstrap=True)

    def measured():
        state["ntp"] += 1
        return dict(
            passed=True,
            error_bound_ms=10,
            checked_at=datetime.fromtimestamp(timer.now() / 1000, UTC).isoformat(),
        )

    def served(application, *args, **kwargs):
        state["server"] = FakeServer(application)
        return state["server"]

    def sdk():
        state["loads"] += 1
        assert state["peer_synced"]  # No module load/capture before authentication.
        return AdvancingSDK(timer)

    def captured(module, binding, **kwargs):
        state["capture"] += 1
        assert state["peer_synced"]
        if fail_capture:
            raise ValueError("SIMULATED_CAPTURE_FAILURE")
        return capture_once(
            module, binding, process_check=lambda _: [123], now_ms=timer.now, **kwargs
        )

    def call(op, receipt=""):
        fields = next(out.glob("fxcs-*.tsv")).read_text().split("\t")
        assert len(fields) == 13
        secret = fields[12].encode()
        state["nonce"] += 1
        nonce = f"{state['nonce']:064x}"
        text = f"connected/1\t{op}\t{fields[4]}\t{fields[5]}"
        if receipt:
            text += "\t" + receipt.encode().hex()
        frame = Frame(
            "C2S",
            fields[2],
            fields[3],
            nonce,
            timer.now(),
            timer.now() + 5000,
            "REPORT" if op == "REPORT" else "PULL",
            text,
        )
        service = state["server"].application.backend
        raw = service.exchange(frame.encode(secret))
        return Frame.decode(
            raw,
            secret,
            direction="S2C",
            scope=fields[2],
            client=fields[3],
            now=timer.now(),
            nonce=nonce,
        )

    def sleep(seconds):
        timer.sleep(seconds)
        if peer:
            if not state["peer_synced"]:
                assert call("SYNC").operation == "WORK"
                state["peer_synced"] = True
            else:
                response = call("PULL")
                if response.operation == "WORK":
                    receipt = hold_receipt(response.payload, timer.now(), 20, timer.now() - 400)
                    assert call("REPORT", receipt).operation == "ACK"

    runtime = Runtime(
        probe=measured,
        clock=lambda _: FakeHostClock(timer),
        stores=lambda *args: (authority_store, backend_store),
        listener=served,
        tls_material=lambda *args: None,
        capture=captured,
        load_sdk=sdk,
        monotonic=timer.monotonic,
        sleep=sleep,
    )
    return dict(
        path=path,
        out=out,
        cert=cert,
        key=key,
        state=state,
        timer=timer,
        authority_store=authority_store,
        backend_store=backend_store,
        runtime=runtime,
    )


def run(parts, seconds=4):
    return session(
        parts["path"],
        parts["out"],
        parts["cert"],
        parts["key"],
        "synthetic-no-dsn",
        seconds=seconds,
        bootstrap_authority=True,
        conversion_symbol="USDCAD",
        runtime=parts["runtime"],
    )


def test_native_handshake_precedes_single_capture_two_hold_receipts_and_shutdown(tmp_path):
    parts = setup(tmp_path)
    original = parts["path"].read_bytes()
    report = run(parts)
    assert report["status"] == "COMPLETED" and report["receipt_count"] == 2
    assert report["channel_state"] == "DISCONNECTED"
    assert report["last_observed_channel_state"] == "HEALTHY"
    assert report["native_acknowledgement_verified"] is False
    assert not report["execution_enabled"] and not report["timestamp_mapping_qualified"]
    assert parts["state"]["loads"] == parts["state"]["capture"] == 1
    assert parts["state"]["server"].closed and parts["path"].read_bytes() == original
    raw = json.loads((parts["out"] / "private-capture.json").read_text())
    assert raw["timestamp_mapping_qualified"] is False
    assert all("TIMESTAMP_MAPPING_UNQUALIFIED" in row["missing"] for row in report["results"])
    events = (parts["out"] / "private-events.jsonl").read_text()
    assert "STARTUP_SAME_OWNER_RENEWAL" not in events and "LEASE_NOT_RETIRED" in events
    config = next(parts["out"].glob("fxcs-*.tsv")).read_text().split("\t")
    assert len(config) == 13 and config[6:8] == ["123", "TEST-DEMO"]
    assert config[1] == "https://127.0.0.1:8443/v1/connected-shadow"
    assert config[12] not in events and config[12] not in json.dumps(report)
    with parts["authority_store"].transaction() as journal:
        assert not any(e["kind"] == "retire" for e in journal.records)


@pytest.mark.parametrize("winerror", [32, None])
def test_terminal_report_survives_final_status_failure_without_qualification(
    tmp_path, monkeypatch, winerror
):
    parts = setup(tmp_path)
    original_replace = connected_session.os.replace
    preserved = {}
    private_message = "synthetic credential-like text that must not escape"

    def blocked_final_replace(source, destination):
        server = parts["state"].get("server")
        if server is None or not server.closed:
            return original_replace(source, destination)
        if not preserved:
            preserved.update(old=destination.read_bytes(), pending=source.read_bytes(), path=source)
        assert destination.read_bytes() == preserved["old"]
        assert source == preserved["path"] and source.read_bytes() == preserved["pending"]
        error = PermissionError(private_message)
        if winerror is not None:
            error.winerror = winerror
        raise error

    monkeypatch.setattr(connected_session.os, "replace", blocked_final_replace)
    report = run(parts)
    assert report["status"] == "BLOCKED" and report["reason"] == "FINAL_STATUS_UPDATE_FAILED"
    assert report["final_status_error"] == (
        "STATUS_REPLACE_BLOCKED" if winerror is not None else "STATUS_WRITE_FAILED"
    )
    assert report["outcome_before_status_failure"] == dict(status="COMPLETED", reason=None)
    assert report["receipt_count"] == 2 and report["channel_state"] == "DISCONNECTED"
    assert not report["connected_execution_accepted"] and not report["execution_enabled"]
    assert (
        not report["timestamp_mapping_qualified"] and not report["native_acknowledgement_verified"]
    )
    assert parts["state"]["server"].closed and parts["state"]["capture"] == 1
    assert (parts["out"] / "status.json").read_bytes() == preserved["old"]
    assert preserved["path"].read_bytes() == preserved["pending"]
    assert json.loads(preserved["pending"])["status"] == "COMPLETED"
    terminal = parts["out"] / "report.json"
    assert json.loads(terminal.read_text()) == report
    assert private_message not in terminal.read_text()
    assert private_message not in (parts["out"] / "private-events.jsonl").read_text()
    before = terminal.read_bytes()
    with pytest.raises(FileExistsError):
        connected_session.exclusive_bytes(terminal, b"must not replace retained evidence")
    assert terminal.read_bytes() == before


def test_no_peer_gets_only_bounded_startup_renewals_and_no_sdk_capture(tmp_path):
    parts = setup(tmp_path, peer=False)
    report = run(parts, seconds=100)
    assert report["status"] == "BLOCKED" and report["reason"] == "NATIVE_ATTACH_WINDOW_EXPIRED"
    assert parts["state"]["loads"] == parts["state"]["capture"] == 0
    assert parts["timer"].elapsed == 60
    with parts["authority_store"].transaction() as journal:
        renewed = [e for e in journal.records if e["kind"] == "renew"]
        assert len(renewed) == 11
        assert all(e["at_ms"] < parts["timer"].now() for e in renewed)
        assert not any(e["kind"] == "retire" for e in journal.records)


def test_capture_failure_is_not_retried_and_private_failures_stay_sanitized(tmp_path):
    parts = setup(tmp_path, fail_capture=True)
    report = run(parts)
    assert report["status"] == "BLOCKED" and report["reason"] == "SIMULATED_CAPTURE_FAILURE"
    assert parts["state"]["capture"] == 1 and parts["state"]["server"].closed
    assert report["phase"] == "BROKER_CAPTURE"


def test_clock_refresh_never_clears_disjoint_or_invalid_evidence():
    timer = Timer()
    current = FakeHostClock(timer, 10)
    slot = ClockSlot(current)
    slot()
    timer.sleep(0.01)
    slot.refresh(FakeHostClock(timer, 5))
    assert slot()[1] == 5
    broken = FakeHostClock(timer)
    broken.read = lambda: (timer.now() + 1000, 10)
    with pytest.raises(ValueError, match="INTERVAL_DISJOINT"):
        slot.refresh(broken)
    current = FakeHostClock(timer)
    slot = ClockSlot(current)
    current.read = lambda: (_ for _ in ()).throw(ValueError("HOST_CLOCK_CHANGED"))
    with pytest.raises(ValueError, match="HOST_CLOCK_CHANGED"):
        slot.refresh(FakeHostClock(timer))


def test_clock_refresh_accounts_for_elapsed_sampling_time_without_quote_age_credit():
    timer = Timer()
    original = FakeHostClock(timer, 2)
    slot = ClockSlot(original, monotonic_ns=lambda: int(timer.monotonic() * 1e9))

    # Scheduling can consume time between readings even when the wall clock is
    # healthy. The sample intervals need projecting to a common instant.
    def delayed_read():
        sample = timer.now(), 2
        timer.sleep(0.050)
        return sample

    original.read = delayed_read
    before = timer.now()
    slot.refresh(FakeHostClock(timer, 2))
    now, error = slot()
    assert now == before + 50 and error == 2


def test_authenticated_sync_without_pull_never_gets_startup_or_automatic_renewal(tmp_path):
    parts = setup(tmp_path)
    initial_sleep = parts["runtime"].sleep

    def only_sync(seconds):
        if not parts["state"]["peer_synced"]:
            initial_sleep(seconds)
        else:
            parts["timer"].sleep(seconds)

    parts["runtime"] = replace(parts["runtime"], sleep=only_sync)
    report = run(parts, seconds=20)
    assert report["status"] == "INCOMPLETE" and report["receipt_count"] == 0
    assert parts["state"]["capture"] == 1
    with parts["authority_store"].transaction() as journal:
        assert not any(e["kind"] in {"renew", "retire"} for e in journal.records)


def test_startup_renewal_cannot_extend_after_any_authenticated_exchange(tmp_path):
    parts = setup(tmp_path)
    run(parts)
    service = parts["state"]["server"].application.backend
    with parts["authority_store"].transaction() as journal:
        before = len(journal.records)
    assert not startup_renew(
        service.authority,
        service.store,
        service.client,
        service.incarnation,
        service.epoch,
        service.clock_upper,
        parts["timer"].monotonic,
        60,
    )
    with parts["authority_store"].transaction() as journal:
        assert len(journal.records) == before


def test_session_cannot_rebootstrap_or_automatically_adopt_expired_authority(tmp_path):
    parts = setup(tmp_path, peer=False)
    run(parts, seconds=20)
    parts["timer"].sleep(20)
    another = replace(
        parts["runtime"],
        stores=lambda *args: (
            parts["authority_store"],
            SQLiteStore(tmp_path / "another.db", bootstrap=True),
        ),
    )
    report = session(
        parts["path"],
        tmp_path / "second",
        parts["cert"],
        parts["key"],
        "synthetic",
        seconds=10,
        runtime=another,
    )
    assert report["status"] == "BLOCKED" and report["reason"] == "EXPLICIT_RETIREMENT_REQUIRED"
    assert parts["state"]["capture"] == 0
    with pytest.raises(ValueError, match="EXPLICIT_RETIREMENT_REQUIRED"):
        Authority(parts["authority_store"], binding().account).claim(
            "b" * 64, "d" * 64, parts["timer"].now() + 10
        )


@pytest.mark.parametrize(
    "identity,allowed",
    [
        (
            (
                "fx_connected_a_paper_writer",
                "postgres",
                "fx_connected_a_paper",
                False,
                False,
                False,
            ),
            False,
        ),
        (("postgres", "postgres", "fx_connected_a_paper", True, True, True), False),
        (
            (
                "fx_connected_a_live_writer",
                "fx_connected_a_live_writer",
                "fx_connected_a_live",
                False,
                False,
                False,
            ),
            False,
        ),
        (
            (
                "fx_connected_a_paper_writer",
                "fx_connected_a_paper_writer",
                "fx_connected_a_paper",
                False,
                True,
                False,
            ),
            False,
        ),
        (
            (
                "fx_forex_paper_writer",
                "fx_forex_paper_writer",
                "fx_forex_paper",
                False,
                False,
                False,
            ),
            False,
        ),
        (
            (
                "fx_connected_a_paper_writer",
                "fx_connected_a_paper_writer",
                "fx_connected_a_paper",
                False,
                False,
                False,
            ),
            True,
        ),
    ],
)
def test_runtime_dsn_requires_isolated_paper_runtime_role(monkeypatch, identity, allowed):
    class DB:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def execute(self, *args):
            return self

        def fetchone(self):
            return identity

    monkeypatch.setattr(connected_session.psycopg, "connect", lambda *args, **kwargs: DB())
    if allowed:
        connected_session.check_runtime_dsn("host=127.0.0.1")
    else:
        with pytest.raises(ValueError, match="PAPER_RUNTIME_ROLE_REQUIRED"):
            connected_session.check_runtime_dsn("host=127.0.0.1")


def test_remote_database_address_cannot_override_loopback_name():
    with pytest.raises(ValueError, match="LOOPBACK_RUNTIME_DATABASE_REQUIRED"):
        connected_session.check_runtime_dsn("host=localhost hostaddr=203.0.113.1")
