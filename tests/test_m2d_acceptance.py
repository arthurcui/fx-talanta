import hashlib
import importlib.util
import json
import struct
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from fx_talanta.acceptance import probe
from fx_talanta.acceptance.clock_probe import decode, packet
from fx_talanta.acceptance.faults import readiness, run
from fx_talanta.domain.models import AccountIdentity
from fx_talanta.observer.contracts import Binding
from fx_talanta.observer.mt5 import READ_METHODS, ObservationFailure

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 1, 5, 12, tzinfo=UTC)


def test_published_evidence_matches_final_harness_and_retains_failures():
    evidence = json.loads((ROOT / "docs/evidence/m2d-no-order-20261103.json").read_text())
    for path, digest in evidence["final_harness_source_sha256"].items():
        assert hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == digest
    for path, digest in evidence["offline"]["historical_evidence_sha256"].items():
        assert hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == digest
    assert evidence["probes"]["cmc_first"]["report"]["status"] == "BLOCKED"
    for name in ("cmc_corrected", "forex"):
        report = evidence["probes"][name]["report"]
        assert report["status"] == "CAPTURED"
        assert not report["execution_enabled"] and not report["m2d_accepted"]
        assert not report["qualified_for_trading"]
        for symbol in report["symbols"].values():
            assert 0 <= symbol["fresh_for_two_second_entry"] <= symbol["samples"] == 30
    assert evidence["preservation"]["private_bindings_and_envs_unchanged"]


def test_durable_composed_fault_trace_and_preserved_gaps(tmp_path):
    report = run(ROOT, tmp_path)
    assert report["status"] == "NO_ORDER_CHECKS_PASSED"
    assert len(report["results"]) == 30
    assert report["durable_records"] > len(report["results"])
    assert not report["execution_enabled"] and not report["m2d_accepted"]
    assert report["gates"] == readiness(ROOT)
    for broker in report["gates"]["broker_historical_acceptance"].values():
        assert not any(broker.values())
    assert not report["gates"]["provider_qualified_for_trading"]
    # Re-running into a used evidence directory must not reuse/reset the journal.
    with pytest.raises(ValueError):
        run(ROOT, tmp_path)


def response(sent, received, offset=0):
    request = packet(sent)
    raw = bytearray(48)
    raw[0], raw[1] = 0x24, 2
    raw[24:32] = request[40:48]
    raw[32:40] = packet(sent + 0.01 + offset)[40:48]
    raw[40:48] = packet(received - 0.01 + offset)[40:48]
    return raw, request


def test_clock_measures_uncertainty_and_rejects_replay_step_and_unsynced_peer():
    sent = NOW.timestamp()
    raw, request = response(sent, sent + 0.03)
    result = decode(raw, request, sent, sent + 0.03, 0.03)
    assert 10 <= result["error_bound_ms"] <= 12
    raw[8:12] = struct.pack("!I", 65536)
    assert decode(raw, request, sent, sent + 0.03, 0.03)["error_bound_ms"] > 1000
    for changed in (packet(sent - 1), packet(sent + 1)):
        with pytest.raises(ValueError):
            decode(raw, changed, sent, sent + 0.03, 0.03)
    with pytest.raises(ValueError):
        decode(raw, request, sent, sent + 1, 0.03)
    raw[0] |= 0xC0
    with pytest.raises(ValueError):
        decode(raw, request, sent, sent + 0.03, 0.03)


@pytest.mark.parametrize(
    "method", ["order_send", "order_check", "login", "symbol_select", "market_book_add"]
)
def test_probe_cannot_reach_mutating_or_extra_sdk_methods(method):
    sdk = NS()
    api = probe.ProbeSDK(sdk, ("EURUSD", "USDJPY"))
    with pytest.raises(ValueError, match="no-order"):
        api.call(method)
    assert not api.calls
    assert "order_calc_profit" not in READ_METHODS  # M1 observer allowlist unchanged.


@pytest.fixture
def capture_fixture(tmp_path, monkeypatch):
    elapsed = [0.0]

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW + timedelta(seconds=elapsed[0])

    monkeypatch.setattr(probe, "datetime", Clock)
    monkeypatch.setattr(probe.time, "monotonic", lambda: elapsed[0])
    monkeypatch.setattr(
        probe.time, "sleep", lambda seconds: elapsed.__setitem__(0, elapsed[0] + seconds)
    )
    monkeypatch.setattr(probe, "running_pids", lambda _: [123])
    clocks = iter(({"passed": True, "error_bound_ms": 10}, {"passed": True, "error_bound_ms": 90}))
    monkeypatch.setattr(probe, "clock_probe", lambda: next(clocks))
    binding = Binding(
        account=AccountIdentity(
            environment="PAPER",
            venue="BROKER_DEMO",
            broker="fixture",
            server="TEST-DEMO",
            login="12345",
        ),
        source="MT5",
        terminal_path="C:/test/terminal64.exe",
        data_path="C:/test/data",
        expected_build=123,
        expected_currency="CAD",
        expected_company="Fixture",
        expected_margin_mode=2,
        permissions_confirmed=True,
        permission_evidence="synthetic fixture only",
    )
    path = tmp_path / "binding.json"
    path.write_text(binding.model_dump_json(), encoding="utf-8")
    folder = tmp_path / "capture"
    folder.mkdir()
    calls = []
    info = NS(
        visible=True,
        digits=5,
        point=0.00001,
        volume_min=0.01,
        volume_max=100,
        volume_step=0.01,
        trade_contract_size=100000,
        trade_tick_size=0.00001,
        trade_tick_value_loss=1.35,
        trade_stops_level=0,
        trade_freeze_level=0,
        trade_exemode=2,
        filling_mode=1,
        currency_base="EUR",
        currency_profit="USD",
        swap_mode=1,
    )
    sdk = NS(
        __version__="5.0.6231",
        initialize=lambda *a, **k: calls.append("initialize") or True,
        shutdown=lambda: calls.append("shutdown"),
        positions_get=lambda: (),
        orders_get=lambda: (),
        terminal_info=lambda: NS(
            path="C:/test", data_path="C:/test/data", build=123, connected=True
        ),
        account_info=lambda: NS(
            trade_mode=0,
            login=12345,
            server="TEST-DEMO",
            company="Fixture",
            margin_mode=2,
            currency="CAD",
        ),
        symbol_info=lambda _: info,
        symbol_info_tick=lambda _: NS(
            bid=1.1, ask=1.1002, time_msc=int((NOW.timestamp() + elapsed[0] - 1.95) * 1000)
        ),
        order_calc_profit=lambda action, symbol, volume, entry, stop: (
            -abs(stop - entry) * 100000 * volume * 1.35
        ),
        order_calc_margin=lambda *args: 20.0,
    )
    monkeypatch.setitem(sys.modules, "MetaTrader5", sdk)
    return path, folder, sdk, calls, binding


def test_capture_recomputes_freshness_with_worse_final_clock_and_no_prices_escape(capture_fixture):
    path, folder, sdk, calls, binding = capture_fixture
    result = probe.capture(path, folder, 10)
    assert calls == ["initialize", "shutdown"]
    assert result["status"] == "CAPTURED" and result["used_clock_bound_ms"] == 92
    for value in result["symbols"].values():
        assert value["fresh_for_two_second_entry"] == 0
        assert value["fresh_for_five_second_observer"] == 10
    output = json.dumps(result)
    assert binding.account.login not in output
    assert '"bid"' not in output and '"ask"' not in output and '"tick_ms"' not in output
    assert not result["m2d_accepted"] and not result["qualified_for_trading"]
    assert set(result["sdk_calls"]) <= probe.METHODS


def test_failed_clock_never_initializes_terminal(capture_fixture, monkeypatch):
    path, folder, _, calls, _ = capture_fixture
    monkeypatch.setattr(probe, "clock_probe", lambda: {"passed": False, "error_bound_ms": 110})
    with pytest.raises(ObservationFailure, match="CLOCK_UNVERIFIED"):
        probe.capture(path, folder, 10)
    assert calls == []


def test_slow_identity_read_is_not_a_clock_jump(capture_fixture):
    path, folder, sdk, _, _ = capture_fixture
    original = sdk.account_info

    def slow():
        probe.time.sleep(0.1)
        return original()

    sdk.account_info = slow
    assert probe.capture(path, folder, 10)["status"] == "CAPTURED"


def test_jump_smaller_than_old_detector_exceeds_two_ms_guard(capture_fixture, monkeypatch):
    path, folder, sdk, _, _ = capture_fixture
    original_clock = probe.datetime
    shift = [0]

    class JumpingClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return original_clock.now(tz) + timedelta(seconds=shift[0])

    original_tick = sdk.symbol_info_tick

    def tick(symbol):
        shift[0] = 0.03
        return original_tick(symbol)

    monkeypatch.setattr(probe, "datetime", JumpingClock)
    sdk.symbol_info_tick = tick
    with pytest.raises(ObservationFailure, match="HOST_CLOCK_CHANGED"):
        probe.capture(path, folder, 10)


def test_existing_terminal_required_before_initialize(capture_fixture, monkeypatch):
    path, folder, _, calls, _ = capture_fixture
    monkeypatch.setattr(probe, "running_pids", lambda _: [])
    with pytest.raises(ObservationFailure, match="RUNNING_TERMINAL_REQUIRED"):
        probe.capture(path, folder, 10)
    assert calls == []


def test_account_change_detaches_without_mutation(capture_fixture):
    path, folder, sdk, calls, _ = capture_fixture
    sdk.account_info = lambda: NS(trade_mode=2)
    with pytest.raises(ObservationFailure, match="IDENTITY_MISMATCH"):
        probe.capture(path, folder, 10)
    assert calls == ["initialize", "shutdown"]


def test_invalid_calculation_never_becomes_valid(capture_fixture):
    path, folder, sdk, calls, _ = capture_fixture
    sdk.order_calc_profit = lambda *args: float("nan")
    with pytest.raises(ObservationFailure, match="INVALID_CALCULATION"):
        probe.capture(path, folder, 10)
    assert calls == ["initialize", "shutdown"]


def test_expired_clock_policy_is_not_extended(capture_fixture):
    path, folder, _, calls, binding = capture_fixture
    expired = binding.model_copy(
        update={
            "time_policy_from": NOW - timedelta(hours=2),
            "time_policy_until": NOW - timedelta(hours=1),
            "time_policy_evidence": "fixture expired",
        }
    )
    path.write_text(expired.model_dump_json(), encoding="utf-8")
    original = path.read_bytes()
    with pytest.raises(ObservationFailure):
        probe.capture(path, folder, 10)
    assert calls == [] and path.read_bytes() == original


def test_supervisor_timeout_is_retained_without_retry(tmp_path, monkeypatch, capsys):
    spec = importlib.util.spec_from_file_location("m2d_cli", ROOT / "scripts/m2d_acceptance.py")
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    entrypoint = tmp_path / "scripts" / "m2d_acceptance.py"
    entrypoint.parent.mkdir()
    entrypoint.write_text("# synthetic supervisor fixture\n")
    monkeypatch.setattr(cli, "__file__", str(entrypoint))
    folder = tmp_path / ".local" / "timeout"
    calls = []

    def timeout(command, **kwargs):
        calls.append(command)
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])

    monkeypatch.setattr(cli.subprocess, "run", timeout)
    monkeypatch.setattr(sys, "argv", ["m2d", "--output", str(folder), "--binding", "unused.json"])
    assert cli.main() == 2 and len(calls) == 1
    assert json.loads((folder / "supervisor-timeout.json").read_text())["status"] == "TIMEOUT"
    assert json.loads(capsys.readouterr().out)["m2d_accepted"] is False
    with pytest.raises(FileExistsError):
        cli.main()
    assert len(calls) == 1


def test_worktree_local_ancestor_does_not_allow_tracked_output(monkeypatch):
    spec = importlib.util.spec_from_file_location("m2d_cli", ROOT / "scripts/m2d_acceptance.py")
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    monkeypatch.setattr(sys, "argv", ["m2d", "--output", str(ROOT / "docs" / "forbidden-capture")])
    with pytest.raises(SystemExit) as failure:
        cli.main()
    assert failure.value.code == 2
    assert not (ROOT / "docs" / "forbidden-capture").exists()
