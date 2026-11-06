"""Bounded demo account inspection of an already running MT5. No clock normalization.

Separate from the strict qualified observer: receipts cannot authorize entry,
certify quotes or populate strategy/reconciliation journals.
"""

import argparse
import json
import math
import multiprocessing
import os
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from fx_talanta.dashboard.current_broker import CurrentConfig, Receipt
from fx_talanta.dashboard.quote_clock import QuoteClock, QuoteSample, host_identity
from fx_talanta.observer.contracts import Binding, windows_path
from fx_talanta.observer.mt5 import ObservationFailure, ReadOnlySDK, number, validate_terminal


def existing_terminal(binding):
    if os.name != "nt":
        raise ValueError("Windows terminal required")
    result = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-Command",
            "Get-CimInstance Win32_Process -Filter \"Name='terminal64.exe'\" | "
            "Select-Object ProcessId,ExecutablePath | ConvertTo-Json -Compress",
        ],
        capture_output=True,
        text=True,
        timeout=10,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    if result.returncode:
        raise ValueError("terminal process unavailable")
    rows = json.loads(result.stdout or "[]")
    rows = rows if isinstance(rows, list) else [rows]
    matches = [
        r
        for r in rows
        if windows_path(r.get("ExecutablePath") or "") == windows_path(binding.terminal_path)
    ]
    if len(matches) != 1:
        raise ValueError("exact existing terminal required")
    return matches[0]["ProcessId"]


def capture(module, binding, run, sequence, now, proof=None, monotonic=time.monotonic):
    binding.require_permissions()
    if binding.source != "MT5" or module.__version__ != binding.sdk_version:
        raise ValueError("pinned MT5 reader required")
    api = ReadOnlySDK(module)
    started = now()
    started_monotonic = monotonic()
    if proof and (
        proof.binding_hash != binding.fingerprint()
        or proof.server_offset_seconds != binding.sdk_time_offset_seconds
        or proof.symbols != binding.symbols
        or proof.status(started, started_monotonic, host_identity())[0] != "VERIFIED_BOUNDED"
    ):
        raise ValueError("current clock evidence required")
    try:
        if not api.call("initialize", binding.terminal_path, timeout=5000):
            raise ValueError("terminal attach failed")
        terminal, account = validate_terminal(api, binding)
        if terminal.trade_allowed:
            raise ValueError("Algo Trading must be disabled")
        positions, orders = api.call("positions_get"), api.call("orders_get")
        samples, quotes = [], 0
        for symbol in binding.symbols:
            try:
                tick = api.call("symbol_info_tick", symbol)
            except ObservationFailure:
                if not proof:
                    raise
                tick = None
            if tick is not None and tick.time_msc > 0:
                quotes += 1
            if proof:
                valid = (
                    tick is not None
                    and tick.time_msc > 0
                    and all(math.isfinite(v) and v > 0 for v in (tick.bid, tick.ask))
                    and tick.ask >= tick.bid
                )
                samples.append(
                    QuoteSample(
                        symbol=symbol,
                        received_at=now(),
                        native_time_ms=int(tick.time_msc) if valid else None,
                        state="AVAILABLE" if valid else "MISSING" if tick is None else "INVALID",
                    )
                )
        terminal, _ = validate_terminal(api, binding)
        if terminal.trade_allowed:
            raise ValueError("Algo Trading changed")
        return Receipt(
            run_id=run,
            binding_hash=binding.fingerprint(),
            sequence=sequence,
            started_at=started,
            observed_at=now(),
            currency=account.currency,
            balance=number(account.balance),
            equity=number(account.equity),
            positions=len(positions),
            orders=len(orders),
            quotes_received=quotes,
            expected_quotes=len(binding.symbols),
            quote_clock_hash=proof.fingerprint() if proof else None,
            quotes=tuple(samples),
        )
    finally:
        api.call("shutdown")


def _worker(pipe, binding, run, sequence, proof):
    try:
        import MetaTrader5 as mt5

        receipt = capture(mt5, binding, run, sequence, lambda: datetime.now(UTC), proof)
        pipe.send(receipt.model_dump_json())
    except Exception:
        pipe.send(None)
    finally:
        pipe.close()


def bounded_capture(binding, run, sequence, proof=None):
    ctx = multiprocessing.get_context("spawn")
    reader, writer = ctx.Pipe(duplex=False)
    child = ctx.Process(target=_worker, args=(writer, binding, run, sequence, proof))
    child.start()
    writer.close()
    try:
        if not reader.poll(15):
            raise ValueError("capture deadline exceeded")
        raw = reader.recv()
        if raw is None:
            raise ValueError("capture rejected")
        return Receipt.model_validate_json(raw)
    finally:
        reader.close()
        child.join(1)
        if child.is_alive():
            child.terminate()
            child.join(5)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binding", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--samples", type=int, default=10)
    parser.add_argument(
        "--quote-clock", type=Path, help="Fresh independently corroborated clock JSON"
    )
    args = parser.parse_args()
    if not 1 <= args.samples <= 60:
        parser.error("samples must be 1..60")
    binding = Binding.model_validate_json(args.binding.read_bytes())
    proof = (
        QuoteClock.model_validate_json(args.quote_clock.read_bytes()) if args.quote_clock else None
    )
    pid = existing_terminal(binding)
    args.output.mkdir(parents=True, exist_ok=False)
    out = args.output.resolve()
    run = uuid4()
    config = CurrentConfig(
        label="Broker demo inspection",
        run_id=run,
        binding_hash=binding.fingerprint(),
        receipt_file=out / "latest.json",
        quote_clock=proof,
    )
    (out / "view.json").write_text(config.model_dump_json(indent=2), encoding="utf-8")
    try:
        for sequence in range(1, args.samples + 1):
            if existing_terminal(binding) != pid:
                raise ValueError("terminal process changed")
            receipt = bounded_capture(binding, run, sequence, proof)
            if existing_terminal(binding) != pid:
                raise ValueError("terminal process changed during capture")
            raw = receipt.model_dump_json(indent=2)
            (out / f"receipt-{sequence:04}.json").write_text(raw, encoding="utf-8")
            temp = out / "next.json"
            temp.write_text(raw, encoding="utf-8")
            temp.replace(out / "latest.json")
            if sequence < args.samples:
                time.sleep(1)
        print(
            json.dumps(
                dict(captured=args.samples, quote_freshness="UNVERIFIED", execution_enabled=False)
            )
        )
    except Exception:
        # Preserve receipts; remove current pointer to invalidate display immediately.
        (out / "latest.json").unlink(missing_ok=True)
        (out / "failed.json").write_text('{"status":"CAPTURE_FAILED"}', encoding="utf-8")
        raise RuntimeError("read-only capture failed; inspect private evidence") from None


if __name__ == "__main__":
    main()
