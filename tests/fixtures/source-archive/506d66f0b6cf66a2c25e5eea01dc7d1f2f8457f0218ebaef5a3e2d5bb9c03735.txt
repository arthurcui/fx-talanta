"""Short demo-only capability capture. No account login, subscriptions or order API."""

import hashlib
import json
import math
import subprocess
import time
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fx_talanta.acceptance.clock_probe import probe as clock_probe
from fx_talanta.observer.contracts import Binding, windows_path
from fx_talanta.observer.mt5 import ObservationFailure, SDKClock, validate_terminal

METHODS = frozenset(
    {
        "initialize",
        "shutdown",
        "terminal_info",
        "account_info",
        "symbol_info",
        "symbol_info_tick",
        "positions_get",
        "orders_get",
        "order_calc_profit",
        "order_calc_margin",
    }
)
CALCULATIONS = frozenset({"order_calc_profit", "order_calc_margin"})


class ProbeSDK:
    def __init__(self, module, symbols):
        self._module, self.symbols = module, frozenset(symbols)
        self.calls = Counter()

    def call(self, method, *args, **kwargs):
        if method not in METHODS:
            raise ValueError("outside no-order capability")
        if method in CALCULATIONS:
            if kwargs or args[0] not in (0, 1) or args[1] not in self.symbols:
                raise ValueError("invalid hypothetical calculation")
            if not all(math.isfinite(x) and x > 0 for x in args[2:]):
                raise ValueError("invalid hypothetical inputs")
        if method in {"symbol_info", "symbol_info_tick"} and args[0] not in self.symbols:
            raise ValueError("symbol outside pinned scope")
        self.calls[method] += 1
        result = getattr(self._module, method)(*args, **kwargs)
        if result is None and method != "shutdown":
            raise ObservationFailure("READER_FAILED")
        return result


def running_pids(binding):
    # Constant read-only command: no account/secret values are interpolated into a shell.
    command = (
        "@(Get-CimInstance Win32_Process -Filter \"Name='terminal64.exe'\" | "
        "Select-Object ProcessId,ExecutablePath) | ConvertTo-Json -Compress"
    )
    read = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
        capture_output=True,
        text=True,
        timeout=8,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        check=True,
    )
    values = json.loads(read.stdout or "[]")
    if isinstance(values, dict):
        values = [values]
    return sorted(
        p["ProcessId"]
        for p in values
        if p.get("ExecutablePath")
        and windows_path(p["ExecutablePath"]) == windows_path(binding.terminal_path)
    )


def write_json(path, value):
    with path.open("x", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(value, indent=2, allow_nan=False) + "\n")


def calculations(api, symbol, info, tick):
    required = (
        info.volume_min,
        info.volume_step,
        info.trade_contract_size,
        info.trade_tick_size,
        info.trade_tick_value_loss,
        tick.bid,
        tick.ask,
    )
    if not all(math.isfinite(v) and v > 0 for v in required) or tick.ask < tick.bid:
        raise ObservationFailure("INVALID_SPECIFICATION")
    distance = max(
        info.trade_stops_level * info.point + 2 * info.trade_tick_size, 20 * info.trade_tick_size
    )
    distance = math.ceil(distance / info.trade_tick_size) * info.trade_tick_size
    rows = []
    for action, side, entry, stop in (
        (0, "BUY", tick.ask, tick.bid - distance),
        (1, "SELL", tick.bid, tick.ask + distance),
    ):
        if stop <= 0:
            raise ObservationFailure("INVALID_SPECIFICATION")
        profit = api.call("order_calc_profit", action, symbol, info.volume_min, entry, stop)
        margin = api.call("order_calc_margin", action, symbol, info.volume_min, entry)
        estimate = (
            abs(entry - stop) / info.trade_tick_size * info.trade_tick_value_loss * info.volume_min
        )
        if not all(math.isfinite(v) for v in (profit, margin, estimate)):
            raise ObservationFailure("INVALID_CALCULATION")
        rows.append(
            {
                "side": side,
                "profit": profit,
                "margin": margin,
                "tick_value_loss_estimate": estimate,
                "valid_signs": profit < 0 and margin > 0,
                "within_one_account_cent": abs(-profit - estimate) <= 0.01,
            }
        )
    return rows


def summarize(rows):
    symbols = sorted({v["symbol"] for r in rows for v in r["quotes"]})
    result = {}
    for symbol in symbols:
        values = [v for r in rows for v in r["quotes"] if v["symbol"] == symbol]
        ages = sorted(v["age_upper_ms"] for v in values)
        latency = sorted(v["read_ms"] for v in values)
        result[symbol] = {
            "samples": len(values),
            "fresh_for_two_second_entry": sum(v["entry_fresh"] for v in values),
            "fresh_for_five_second_observer": sum(v["observer_fresh"] for v in values),
            "distinct_tick_times": len({v["tick_ms"] for v in values}),
            "age_upper_p95_ms": ages[math.ceil(len(ages) * 0.95) - 1],
            "read_p95_ms": latency[math.ceil(len(latency) * 0.95) - 1],
        }
    return result


def capture(binding_path: Path, folder: Path, seconds: int):
    if not 10 <= seconds <= 120:
        raise ValueError("bounded capture requires 10..120 seconds")
    raw_binding = binding_path.read_bytes()
    binding = Binding.model_validate_json(raw_binding)
    binding.require_permissions()
    if binding.source != "MT5" or len(binding.symbols) != 2:
        raise ValueError("two pinned demo forex symbols required")
    if [s[:6] for s in binding.symbols] != ["EURUSD", "USDJPY"]:
        raise ValueError("unexpected forex mapping")
    clock = SDKClock(binding)
    clock.check(datetime.now(UTC) + timedelta(seconds=seconds + 30))
    processes = running_pids(binding)
    if len(processes) != 1:
        raise ObservationFailure("RUNNING_TERMINAL_REQUIRED")
    before_clock = clock_probe()
    write_json(folder / "clock-before.json", before_clock)
    if not before_clock["passed"] or before_clock["error_bound_ms"] > 98:
        raise ObservationFailure("CLOCK_UNVERIFIED")
    bound = before_clock["error_bound_ms"]
    import MetaTrader5 as mt5

    if mt5.__version__ != binding.sdk_version:
        raise ObservationFailure("SDK_MISMATCH")
    api = ProbeSDK(mt5, binding.symbols)
    rows, specs, math_rows = [], {}, {}
    started = time.monotonic()
    initial_wall = datetime.now(UTC)
    try:
        if running_pids(binding) != processes:
            raise ObservationFailure("TERMINAL_PROCESS_CHANGED")
        if not api.call("initialize", binding.terminal_path, timeout=5000):
            raise ObservationFailure("DISCONNECTED")
        terminal, account = validate_terminal(api, binding)
        if running_pids(binding) != processes:
            raise ObservationFailure("TERMINAL_PROCESS_CHANGED")
        baseline = (len(api.call("positions_get")), len(api.call("orders_get")))
        for symbol in binding.symbols:
            info = api.call("symbol_info", symbol)
            if not info.visible:
                raise ObservationFailure("SYMBOL_NOT_VISIBLE")
            specs[symbol] = {
                k: getattr(info, k)
                for k in (
                    "digits",
                    "point",
                    "volume_min",
                    "volume_max",
                    "volume_step",
                    "trade_contract_size",
                    "trade_tick_size",
                    "trade_tick_value_loss",
                    "trade_stops_level",
                    "trade_freeze_level",
                    "trade_exemode",
                    "filling_mode",
                    "currency_base",
                    "currency_profit",
                    "swap_mode",
                )
            }
            tick = api.call("symbol_info_tick", symbol)
            math_rows[symbol[:6]] = calculations(api, symbol, info, tick)
        write_json(
            folder / "private-specs-calculations.json",
            {"currency": account.currency, "specifications": specs, "calculations": math_rows},
        )
        with (folder / "private-samples.jsonl").open("x", encoding="utf-8", newline="\n") as stream:
            for index in range(seconds):
                loop = time.monotonic()
                validate_terminal(api, binding)
                sampled_monotonic = time.monotonic()
                now = datetime.now(UTC)
                if (
                    abs((now - initial_wall).total_seconds() - (sampled_monotonic - started))
                    > 0.002
                ):
                    raise ObservationFailure("HOST_CLOCK_CHANGED")
                clock.check(now)
                quotes = []
                for symbol in binding.symbols:
                    begin = time.monotonic()
                    tick = api.call("symbol_info_tick", symbol)
                    if (
                        not all(
                            math.isfinite(v) and v > 0 for v in (tick.bid, tick.ask, tick.time_msc)
                        )
                        or tick.ask < tick.bid
                    ):
                        raise ObservationFailure("INVALID_QUOTE")
                    receipt = datetime.now(UTC)
                    if (
                        abs((receipt - initial_wall).total_seconds() - (time.monotonic() - started))
                        > 0.002
                    ):
                        raise ObservationFailure("HOST_CLOCK_CHANGED")
                    age = (receipt - clock.decode(tick.time_msc / 1000)).total_seconds() * 1000
                    quotes.append(
                        {
                            "symbol": symbol[:6],
                            "tick_ms": tick.time_msc,
                            "age_ms": age,
                            "age_upper_ms": age + bound,
                            "read_ms": (time.monotonic() - begin) * 1000,
                            "entry_fresh": 0 <= age - bound and age + bound <= 2000,
                            "observer_fresh": 0 <= age - bound and age + bound <= 5000,
                            "bid": tick.bid,
                            "ask": tick.ask,
                        }
                    )
                counts = (len(api.call("positions_get")), len(api.call("orders_get")))
                if counts != baseline:
                    raise ObservationFailure("EXTERNAL_ACCOUNT_CHANGE")
                row = {"index": index, "at": now.isoformat(), "quotes": quotes}
                rows.append(row)
                stream.write(json.dumps(row, allow_nan=False) + "\n")
                stream.flush()
                time.sleep(max(0, 1 - (time.monotonic() - loop)))
        validate_terminal(api, binding)
    finally:
        api.call("shutdown")
    after_clock = clock_probe()
    write_json(folder / "clock-after.json", after_clock)
    if (
        not after_clock["passed"]
        or after_clock["error_bound_ms"] > 98
        or running_pids(binding) != processes
    ):
        raise ObservationFailure("FINAL_CLOCK_OR_PROCESS_CHECK")
    if binding_path.read_bytes() != raw_binding:
        raise ObservationFailure("BINDING_CHANGED")
    used_bound = max(bound, after_clock["error_bound_ms"]) + 2
    for row in rows:
        for quote in row["quotes"]:
            age = quote["age_ms"]
            quote.update(
                age_upper_ms=age + used_bound,
                entry_fresh=0 <= age - used_bound and age + used_bound <= 2000,
                observer_fresh=0 <= age - used_bound and age + used_bound <= 5000,
            )
    return {
        "schema": "m2d-readonly-probe/1",
        "status": "CAPTURED",
        "seconds": seconds,
        "elapsed_seconds": time.monotonic() - started,
        "symbols": summarize(rows),
        "identity_verified": True,
        "terminal_process_unchanged": True,
        "binding_sha256": hashlib.sha256(raw_binding).hexdigest(),
        "account_currency": binding.expected_currency,
        "initial_positions": baseline[0],
        "initial_pending_orders": baseline[1],
        "account_counts_unchanged": True,
        "clock_before_bound_ms": bound,
        "clock_after_bound_ms": after_clock["error_bound_ms"],
        "used_clock_bound_ms": used_bound,
        "calculations": {
            symbol: [
                {k: r[k] for k in ("side", "valid_signs", "within_one_account_cent")}
                for r in values
            ]
            for symbol, values in math_rows.items()
        },
        "sdk_calls": dict(api.calls),
        "sampled_channel": "PYTHON_PACKAGE",
        "other_channels": {"EA": "NOT_TESTED", "MCP": "NOT_TESTED"},
        "execution_enabled": False,
        "qualified_for_trading": False,
        "m2d_accepted": False,
        "scope": (
            "Short read-only capability observation; "
            "not execution, cost calibration or sustained qualification"
        ),
    }
