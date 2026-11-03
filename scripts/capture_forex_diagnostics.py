"""Bounded, isolated MT5 tick diagnostics; no database or order interface.

Run only after the account's observation worker has exited. All output excludes
account identifiers and prices. This never contributes qualification evidence.
"""

import argparse
import json
import multiprocessing
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fx_talanta.observer.contracts import Binding  # noqa: E402
from fx_talanta.observer.mt5 import ReadOnlySDK, SDKClock, validate_terminal  # noqa: E402


def capture(binding_path, output, seconds, history=False):
    import MetaTrader5 as mt5

    binding = Binding.model_validate_json(Path(binding_path).read_text())
    binding.require_permissions()
    clock = SDKClock(binding)
    clock.check(datetime.now(UTC) + timedelta(seconds=seconds + 15))
    if mt5.__version__ != binding.sdk_version:
        raise ValueError("SDK mismatch")
    api = ReadOnlySDK(mt5)
    start = time.monotonic()
    previous = {}

    def stage(name):
        (Path(output) / "stage.json").write_text(
            json.dumps({"stage": name, "at": datetime.now(UTC).isoformat()})
        )

    with (Path(output) / "samples.jsonl").open("x", encoding="utf-8") as stream:
        try:
            stage("initialize")
            if not api.call("initialize", binding.terminal_path, timeout=5000):
                raise ValueError("initialization failed")
            stage("validate_identity")
            validate_terminal(api, binding)
            index = 0
            while time.monotonic() - start < seconds:
                loop = time.monotonic()
                clock.check(datetime.now(UTC))
                validate_terminal(api, binding)
                rows = []
                for symbol in binding.symbols:
                    begin = time.monotonic()
                    stage("latest_tick")
                    tick = api.call("symbol_info_tick", symbol)
                    finished = datetime.now(UTC)
                    at = clock.decode(tick.time_msc / 1000)
                    row = {
                        "symbol": symbol,
                        "read_at": finished.isoformat(),
                        "tick_at": at.isoformat(),
                        "age_seconds": (finished - at).total_seconds(),
                        "read_seconds": time.monotonic() - begin,
                        "same_tick": previous.get(symbol) == tick.time_msc,
                    }
                    previous[symbol] = tick.time_msc
                    if history:
                        # Explicit diagnostic-only read, outside production's
                        # narrower SDK allowlist. Never install a subscription.
                        begin = time.monotonic()
                        stage("copy_ticks_from")
                        ticks = mt5.copy_ticks_from(
                            symbol,
                            clock.encode(at - timedelta(seconds=90)),
                            5000,
                            mt5.COPY_TICKS_ALL,
                        )
                        row["history_seconds"] = time.monotonic() - begin
                        if ticks is None:
                            row["history_error"] = "READ_FAILED"
                        else:
                            row["history_count"] = len(ticks)
                            row["history_limit_reached"] = len(ticks) == 5000
                            row["history_tick_times"] = [
                                clock.decode(int(t["time_msc"]) / 1000).isoformat() for t in ticks
                            ]
                        after = api.call("symbol_info_tick", symbol)
                        row["post_history_tick_at"] = clock.decode(
                            after.time_msc / 1000
                        ).isoformat()
                    rows.append(row)
                validate_terminal(api, binding)
                stream.write(
                    json.dumps(
                        {
                            "index": index,
                            "elapsed_seconds": time.monotonic() - start,
                            "connected": True,
                            "ticks": rows,
                        }
                    )
                    + "\n"
                )
                stream.flush()
                index += 1
                if history:
                    break
                time.sleep(
                    max(0, min(1 - (time.monotonic() - loop), seconds - (time.monotonic() - start)))
                )
        finally:
            stage("shutdown")
            api.call("shutdown")


def worker(binding, output, seconds, history):
    try:
        capture(binding, output, seconds, history)
        status = "COMPLETE"
    except Exception:
        # Native errors can contain account details. Preserve only safe category.
        status = "FAILED"
    (Path(output) / "worker-result.json").write_text(
        json.dumps(
            {
                "status": status,
                "finished_at": datetime.now(UTC).isoformat(),
                "qualified_for_trading": False,
            }
        )
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binding", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seconds", type=int, default=900)
    parser.add_argument(
        "--history-only", action="store_true", help="one separately bounded history check"
    )
    args = parser.parse_args()
    if not 60 <= args.seconds <= 900:
        parser.error("duration must be 60 to 900 seconds")
    args.output.mkdir(exist_ok=False)
    began = datetime.now(UTC)
    process = multiprocessing.get_context("spawn").Process(
        target=worker, args=(str(args.binding), str(args.output), args.seconds, args.history_only)
    )
    process.start()
    process.join(15 if args.history_only else args.seconds + 15)
    timed_out = process.is_alive()
    if timed_out:
        process.terminate()
        process.join(5)
        if process.is_alive():
            process.kill()
            process.join(5)
    result_path = args.output / "worker-result.json"
    worker_status = (
        json.loads(result_path.read_text())["status"] if result_path.exists() else "FAILED"
    )
    status = "TIMED_OUT" if timed_out else worker_status if process.exitcode == 0 else "FAILED"
    report = {
        "started_at": began.isoformat(),
        "finished_at": datetime.now(UTC).isoformat(),
        "duration_seconds": None if args.history_only else args.seconds,
        "watchdog_seconds": 15 if args.history_only else args.seconds + 15,
        "mode": "history" if args.history_only else "latest_ticks",
        "status": status,
        "timed_out": timed_out,
        "child_exitcode": process.exitcode,
        "execution_enabled": False,
    }
    (args.output / "supervisor-result.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report))
    return 0 if status == "COMPLETE" else 2


if __name__ == "__main__":
    raise SystemExit(main())
