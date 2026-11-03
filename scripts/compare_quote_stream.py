"""Bounded Windows EA-vs-Python comparison. Private raw evidence, sanitized summary.

No database, order functions, terminal restart or trading configuration changes.
The SDK runs in a separate child so its calls cannot block the file-tail loop.
"""

import argparse
import ctypes
import json
import multiprocessing as mp
import queue
import sys
import time
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fx_talanta.observer.contracts import Binding  # noqa: E402
from fx_talanta.observer.mt5 import ReadOnlySDK, SDKClock, validate_terminal  # noqa: E402
from fx_talanta.observer.quote_stream import (  # noqa: E402
    Tail,
    distribution,
    entry_fresh,
    quote_age,
)


def uptime():
    fn = ctypes.windll.kernel32.GetTickCount64
    fn.restype = ctypes.c_ulonglong
    return fn()


def poll(binding_path, output, stop):
    import MetaTrader5 as mt5

    api = ReadOnlySDK(mt5)
    try:
        binding = Binding.model_validate_json(Path(binding_path).read_text())
        binding.require_permissions()
        if mt5.__version__ != binding.sdk_version:
            raise ValueError("SDK mismatch")
        if not api.call("initialize", binding.terminal_path, timeout=5000):
            raise ValueError("initialize failed")
        while not stop.is_set():
            begin = time.monotonic()
            terminal, _ = validate_terminal(api, binding)
            if terminal.trade_allowed:
                raise ValueError("terminal trading enabled")
            if api.call("positions_get") or api.call("orders_get"):
                raise ValueError("account is not flat")
            SDKClock(binding).check(datetime.now(UTC))
            rows = []
            for symbol in binding.symbols:
                tick = api.call("symbol_info_tick", symbol)
                rows.append(
                    {
                        "symbol": symbol,
                        "tick_ms": tick.time_msc,
                        "bid": tick.bid,
                        "ask": tick.ask,
                        "receipt_ms": uptime(),
                        "epoch": time.time(),
                    }
                )
            output.put(
                {"kind": "POLL", "rows": rows, "read_seconds": time.monotonic() - begin}, timeout=2
            )
            stop.wait(max(0, 1 - (time.monotonic() - begin)))
    except Exception as error:
        output.put({"kind": "ERROR", "class": type(error).__name__}, timeout=2)
    finally:
        api.call("shutdown")


def run(args):
    if not 10 <= args.seconds <= 600:
        raise ValueError("comparison must be 10..600 seconds")
    binding = Binding.model_validate_json(args.binding.read_text())
    SDKClock(binding).check(datetime.now(UTC) + timedelta(seconds=args.seconds + 30))
    args.output.mkdir(parents=True, exist_ok=False)
    tails = {
        s: Tail(args.stream_dir / f"{args.token}-{s.replace('.', '_')}.csv", args.token, s)
        for s in binding.symbols
    }
    cache = {"EA": {}, "POLL": {}}
    last_heartbeat = {}
    for symbol, tail in tails.items():
        for row in tail.read():
            if row.kind in {"INITIAL", "TICK"}:
                cache["EA"][symbol] = row.tick_ms
            if row.kind == "HEARTBEAT":
                last_heartbeat[symbol] = row.captured_ms
            if row.kind == "STOP" or row.dropped or not row.connected:
                raise ValueError("publisher is stopped/disconnected or has dropped records")
    if any(uptime() - last_heartbeat.get(s, 0) > 2500 for s in tails):
        raise ValueError("publisher heartbeat missing/stale")
    context = mp.get_context("spawn")
    output, stop = context.Queue(512), context.Event()
    worker = context.Process(target=poll, args=(str(args.binding), output, stop))
    worker.start()
    start, started_epoch = time.monotonic(), time.time()
    deadline, next_assess = start + args.seconds, start
    latency = {s: [] for s in tails}
    first = {kind: {s: {} for s in tails} for kind in cache}
    ages = {kind: {s: [] for s in tails} for kind in cache}
    fresh = {kind: {s: 0 for s in tails} for kind in cache}
    missing = {kind: {s: 0 for s in tails} for kind in cache}
    read_seconds, loop_delays = [], []
    assessments = 0
    failure = None
    try:
        with (args.output / "events.jsonl").open("x") as evidence:

            def record(event):
                evidence.write(json.dumps(event) + "\n")

            while time.monotonic() < deadline:
                for symbol, tail in tails.items():
                    for row in tail.read():
                        received, epoch = uptime(), time.time()
                        record(
                            {"path": "EA", **asdict(row), "receipt_ms": received, "epoch": epoch}
                        )
                        if row.kind == "STOP" or row.dropped or not row.connected:
                            raise ValueError("publisher stopped/disconnected/dropped records")
                        if row.kind == "HEARTBEAT":
                            last_heartbeat[symbol] = row.captured_ms
                        if row.kind in {"TICK", "INITIAL"}:
                            if received < row.emitted_ms:
                                raise ValueError("uptime clocks are inconsistent")
                            cache["EA"][symbol] = row.tick_ms
                            key = (row.tick_ms, row.bid, row.ask)
                            first["EA"][symbol].setdefault(key, received)
                            latency[symbol].append(received - row.captured_ms)
                while True:
                    try:
                        event = output.get_nowait()
                    except queue.Empty:
                        break
                    record({"path": "POLL", **event})
                    if event["kind"] == "ERROR":
                        raise ValueError("poller failed: " + event["class"])
                    read_seconds.append(event["read_seconds"])
                    for row in event["rows"]:
                        symbol = row["symbol"]
                        if not (row["tick_ms"] > 0 and 0 < row["bid"] <= row["ask"]):
                            raise ValueError("invalid polled quote")
                        cache["POLL"][symbol] = row["tick_ms"]
                        key = (row["tick_ms"], row["bid"], row["ask"])
                        first["POLL"][symbol].setdefault(key, row["receipt_ms"])
                if not worker.is_alive():
                    raise ValueError("poller exited unexpectedly")
                if any(uptime() - last_heartbeat[s] > 2500 for s in tails):
                    raise ValueError("publisher heartbeat stale")
                now = time.monotonic()
                if now >= next_assess:
                    loop_delays.append(now - next_assess)
                    assessments += 1
                    epoch = time.time()
                    assessment = {}
                    for kind in cache:
                        assessment[kind] = {}
                        for symbol in tails:
                            tick = cache[kind].get(symbol)
                            age = (
                                quote_age(tick, epoch, binding.sdk_time_offset_seconds)
                                if tick
                                else None
                            )
                            assessment[kind][symbol] = age
                            if age is None:
                                missing[kind][symbol] += 1
                            else:
                                ages[kind][symbol].append(age)
                            fresh[kind][symbol] += entry_fresh(age)
                    record({"path": "ASSESS", "epoch": epoch, "ages": assessment})
                    next_assess += 0.1
                    if next_assess <= now:
                        next_assess = now + 0.1  # Never fabricate missed assessments.
                time.sleep(0.01)
    except Exception as error:
        failure = str(error)
    finally:
        stop.set()
        worker.join(7)
        if worker.is_alive():
            worker.terminate()
            worker.join(3)
            failure = failure or "poller shutdown timeout"
        for tail in tails.values():
            tail.close()
    result = {
        "status": "FAILED" if failure else "COMPLETED",
        "failure": failure,
        "started_utc": datetime.fromtimestamp(started_epoch, UTC).isoformat(),
        "requested_seconds": args.seconds,
        "collection_seconds": time.monotonic() - start,
        "poll_interval_seconds": 1,
        "assessment_interval_seconds": 0.1,
        "assessments": assessments,
        "entry_ceiling_seconds": 2,
        "qualification": False,
        "symbols": {},
        "poll_cycle_seconds": distribution(read_seconds),
        "assessment_lateness_seconds": distribution(loop_delays),
    }
    for symbol in tails:
        ea, py = first["EA"][symbol], first["POLL"][symbol]
        shared = ea.keys() & py.keys()
        result["symbols"][symbol] = {
            "ea_delivery_ms": distribution(latency[symbol]),
            "matched_poll_minus_ea_receipt_ms": distribution([py[k] - ea[k] for k in shared]),
            "ea_unique_quotes": len(ea),
            "poll_unique_quotes": len(py),
            "ea_only_quotes": len(ea.keys() - py.keys()),
            "poll_only_quotes": len(py.keys() - ea.keys()),
            "buffer_drops": tails[symbol].dropped,
            "paths": {
                kind: {
                    "age_seconds": distribution(ages[kind][symbol]),
                    "fresh_at_two_seconds": fresh[kind][symbol],
                    "missing": missing[kind][symbol],
                }
                for kind in cache
            },
        }
    (args.output / "summary.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))
    if failure:
        raise SystemExit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--binding", type=Path, required=True)
    parser.add_argument("--stream-dir", type=Path, required=True)
    parser.add_argument("--token", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seconds", type=int, default=300)
    run(parser.parse_args())
