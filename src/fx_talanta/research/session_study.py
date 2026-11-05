"""Preregistered full-session historical study. Offline simulation only."""

import argparse
import heapq
import json
import os
from datetime import timedelta
from decimal import Decimal, localcontext
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
from uuid import NAMESPACE_URL, uuid5

from pydantic import Field, model_validator

from fx_talanta.domain.models import FrozenModel
from fx_talanta.research.replay import Experiment, digest, execute_timeline, read, source_hash
from fx_talanta.research.spool import EquitySpool, Spool, file_hash, rows
from fx_talanta.research.tick_index import TickIndex, build_index

PHASES = ("training", "validation", "holdout")
MAX_SESSION_TICKS = 300000


class Plan(FrozenModel):
    experiments: tuple[Experiment, ...] = Field(min_length=1, max_length=2)
    latency_ms: int = Field(default=250, ge=0, le=10000)
    assume_research_inputs: bool = False
    description: str = Field(min_length=1, max_length=2000)

    @model_validator(mode="after")
    def sessions(self):
        if len({e.symbol for e in self.experiments}) != len(self.experiments):
            raise ValueError("duplicate pair")
        for e in self.experiments:
            for phase in PHASES:
                start, end = e.window(phase)
                if start.microsecond % 1000 or end.microsecond % 1000:
                    raise ValueError("study boundaries must align to source milliseconds")
                if end - start > timedelta(days=1):
                    raise ValueError("each study partition is bounded to one session/day")
        return self


def engine_hash():
    root = Path(__file__).parent
    return digest(
        {
            "shared_engine": source_hash(),
            **{
                name: sha256((root / name).read_bytes().replace(b"\r\n", b"\n")).hexdigest()
                for name in ("session_study.py", "spool.py", "tick_index.py", "historical.py")
            },
            "clock": sha256(
                (root.parent / "clock.py").read_bytes().replace(b"\r\n", b"\n")
            ).hexdigest(),
        }
    )


def write(path, value):
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(value, indent=2) + "\n")


def register_study(directory, plan, indexes):
    plan = Plan.model_validate_json(plan.model_dump_json())
    if set(indexes) != {e.symbol for e in plan.experiments}:
        raise ValueError("exact study pair/index mapping required")
    pinned = {}
    for symbol, path in indexes.items():
        path = Path(path).resolve()
        index = TickIndex(path)
        try:
            if index.metadata["symbol"] != symbol:
                raise ValueError("index symbol mismatch")
            pinned[symbol] = {
                "path": str(path),
                "sha256": file_hash(path),
                "archive_sha256": index.metadata["archive_sha256"],
            }
        finally:
            index.close()
    manifest = {
        "schema": "full-session-study/1",
        "plan": plan.model_dump(mode="json"),
        "indexes": pinned,
        "engine_sha256": engine_hash(),
        "execution_enabled": False,
    }
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    write(directory / "manifest.json", manifest)
    write(directory / "registration.json", {"manifest_hash": digest(manifest)})
    return manifest


def timeline(bars, events, start, end):
    bar_times = sorted({b.available_at for b in bars if start <= b.available_at < end})
    bar_items = ((at, 0, True, ()) for at in bar_times)
    quote_items = ((e.available_at, 1, False, (e,)) for e in events)
    for at, _, bar, group in heapq.merge(bar_items, quote_items, key=lambda item: item[:2]):
        yield at, bar, group


class TrackedEvents:
    def __init__(self, source, start, end):
        self.source, self.start, self.end = source, start, end
        self.count = 0
        self.first = self.last = None
        self.max_gap = Decimal(0)

    def __iter__(self):
        for event in self.source:
            at = event.available_at
            if not self.start <= at < self.end:
                raise ValueError("event outside registered partition")
            previous = self.last or self.start
            self.max_gap = max(self.max_gap, Decimal(str((at - previous).total_seconds())))
            self.first = self.first or at
            self.last = at
            self.count += 1
            if self.count > MAX_SESSION_TICKS:
                raise ValueError("session tick bound; no downsampling allowed")
            if self.count % 25000 == 0:
                print(json.dumps({"processed_ticks": self.count}), flush=True)
            yield event

    def report(self):
        if self.last:
            self.max_gap = max(self.max_gap, Decimal(str((self.end - self.last).total_seconds())))
        return {
            "ticks": self.count,
            "first": self.first.isoformat() if self.first else None,
            "last": self.last.isoformat() if self.last else None,
            "maximum_arrival_gap_seconds_including_edges": str(self.max_gap),
            "receipt_timing": "MODELED_NOT_MEASURED",
        }


def verify_phase(output, manifest, *, full=False):
    if (output / "failed.json").exists():
        raise ValueError("failed partition cannot be certified")
    result = json.loads(read(output / "result.json"))
    receipt = json.loads(read(output / "receipt.json"))
    if receipt["manifest_hash"] != digest(manifest) or receipt["result_hash"] != digest(result):
        raise ValueError("changed result or manifest")
    if not full:
        verified = json.loads(read(output / "verified.json"))
        if verified.get("reconstructed") is not True or verified.get("result_hash") != digest(
            result
        ):
            raise ValueError("partition lacks independent verification")
    for name in ("journal", "equity"):
        if file_hash(output / f"{name}.jsonl.gz") != receipt[name]["sha256"]:
            raise ValueError("changed streamed artifact")
    if full:
        previous = "0" * 64
        broker = None
        count = 0
        for item in rows(output / "journal.jsonl.gz"):
            payload = item["payload"]
            if payload["previous"] != previous or digest(payload) != item["hash"]:
                raise ValueError("journal chain invalid")
            previous = item["hash"]
            if payload["stream"] == "broker":
                broker = payload["book"]
            count += 1
        if (
            count != receipt["journal"]["rows"]
            or previous != result["journal_tip"]
            or broker is None
        ):
            raise ValueError("journal terminal evidence missing")
        if Decimal(broker["balance"]) != Decimal(result["balance"]):
            raise ValueError("balance reconstruction mismatch")
        if broker["deals"] != result["deals"]:
            raise ValueError("fill reconstruction mismatch")
        if sum(bool(Decimal(p["volume"])) for p in broker["positions"]) != result["open_positions"]:
            raise ValueError("exposure reconstruction mismatch")
        with localcontext() as context:
            context.prec = 34
            peak = Decimal(result["experiment"]["policy"]["capital"])
            drawdown = Decimal(0)
            last = None
            count = 0
            for sample in rows(output / "equity.jsonl.gz"):
                last = Decimal(sample["equity"])
                peak = max(peak, last)
                drawdown = max(drawdown, (peak - last) / peak)
                count += 1
            if count != receipt["equity"]["rows"] or count != result["coverage"]["ticks"]:
                raise ValueError("equity stream count mismatch")
            if last != Decimal(result["marked_equity"]) or drawdown != Decimal(
                result["metrics"]["maximum_observed_drawdown_fraction"]
            ):
                raise ValueError("equity/drawdown reconstruction mismatch")
    return result


def execute_phase(directory, symbol, partition):
    directory = Path(directory)
    manifest = json.loads(read(directory / "manifest.json"))
    registration = json.loads(read(directory / "registration.json"))
    if (
        registration["manifest_hash"] != digest(manifest)
        or manifest["engine_sha256"] != engine_hash()
    ):
        raise ValueError("registered engine or plan changed")
    plan = Plan.model_validate(manifest["plan"])
    experiment = next((e for e in plan.experiments if e.symbol == symbol), None)
    if experiment is None or partition not in PHASES:
        raise ValueError("pair or partition outside plan")
    # All earlier partitions/pairs must be certified flat before proceeding.
    for prior in PHASES[: PHASES.index(partition)]:
        for e in plan.experiments:
            previous = verify_phase(directory / f"{e.symbol}-{prior}", manifest)
            if not previous["fully_settled"]:
                raise ValueError("prior exposure unresolved; cannot reset it into a new partition")
    pinned = manifest["indexes"][symbol]
    index_path = Path(pinned["path"])
    if file_hash(index_path) != pinned["sha256"]:
        raise ValueError("registered index changed")
    output = directory / f"{symbol}-{partition}"
    output.mkdir(exist_ok=False)
    journal = equity_sink = index = None
    try:
        index = TickIndex(index_path)
        if index.metadata["symbol"] != symbol:
            raise ValueError("index binding mismatch")
        start, end = experiment.window(partition)
        bars = index.bars(plan.latency_ms)
        metadata = SimpleNamespace(
            bars=bars,
            history_complete=plan.assume_research_inputs,
            provenance="HISTORICAL_UNQUALIFIED",
            source=f"HistData {symbol} SHA256 {pinned['archive_sha256']}",
        )
        events = TrackedEvents(
            index.events(start, end, plan.latency_ms, plan.assume_research_inputs), start, end
        )
        journal = Spool(output / "journal.jsonl.gz")
        equity_sink = EquitySpool(output / "equity.jsonl.gz", experiment.policy.capital)
        run_id = uuid5(
            NAMESPACE_URL,
            digest({"study": digest(manifest), "pair": symbol, "partition": partition}),
        )
        result, _ = execute_timeline(
            metadata,
            experiment,
            partition,
            timeline(bars, events, start, end),
            run_id,
            journal_sink=journal,
            samples_sink=equity_sink,
        )
        journal.close()
        equity_sink.close()
        result["schema"] = "full-session-result/1"
        result["coverage"] = events.report()
        result["equity_stream"] = "equity.jsonl.gz"
        result["journal_stream"] = "journal.jsonl.gz"
        result["research_inputs_assumed"] = plan.assume_research_inputs
        result["modeled_latency_ms"] = plan.latency_ms
        result["independent_cold_start"] = True
        if file_hash(index_path) != pinned["sha256"]:
            raise ValueError("index changed during replay")
        write(output / "result.json", result)
        write(
            output / "receipt.json",
            {
                "manifest_hash": digest(manifest),
                "result_hash": digest(result),
                "journal": journal.receipt(),
                "equity": equity_sink.receipt(),
            },
        )
        verify_phase(output, manifest, full=True)
        write(
            output / "verified.json",
            {
                "reconstructed": True,
                "result_hash": digest(result),
                "fully_settled": result["fully_settled"],
            },
        )
        return result
    except Exception as error:
        write(
            output / "failed.json",
            {
                "status": "FAILED",
                "error_type": type(error).__name__,
                "reason": str(error)[:500],
                "retry_allowed": False,
            },
        )
        raise
    finally:
        for sink in (journal, equity_sink):
            if sink is not None and not sink.raw.closed:
                sink.close()
        if index is not None:
            index.close()


def background_priority():
    if os.name == "nt":
        import ctypes

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.GetCurrentProcess.restype = ctypes.c_void_p
        kernel.SetPriorityClass.argtypes = [ctypes.c_void_p, ctypes.c_uint]
        if not kernel.SetPriorityClass(kernel.GetCurrentProcess(), 0x4000):
            raise OSError("could not set this worker to below-normal priority")
    else:
        os.nice(10)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    indexing = sub.add_parser("index")
    indexing.add_argument("--archive", type=Path, required=True)
    indexing.add_argument("--symbol", choices=("EURUSD", "USDJPY"), required=True)
    indexing.add_argument("--output", type=Path, required=True)
    registration = sub.add_parser("register")
    registration.add_argument("--plan", type=Path, required=True)
    registration.add_argument(
        "--index", action="append", required=True, help="SYMBOL=path/to/ticks.sqlite"
    )
    registration.add_argument("--output", type=Path, required=True)
    running = sub.add_parser("run")
    running.add_argument("--study", type=Path, required=True)
    running.add_argument("--symbol", choices=("EURUSD", "USDJPY"), required=True)
    running.add_argument("--partition", choices=PHASES, required=True)
    args = parser.parse_args(argv)
    background_priority()
    if args.command == "index":
        print(json.dumps(build_index(args.archive, args.symbol, args.output)), flush=True)
    elif args.command == "register":
        indexes = dict(item.split("=", 1) for item in args.index)
        manifest = register_study(args.output, Plan.model_validate_json(read(args.plan)), indexes)
        print(json.dumps({"registered": digest(manifest), "execution_enabled": False}), flush=True)
    else:
        result = execute_phase(args.study, args.symbol, args.partition)
        print(
            json.dumps(
                {
                    "symbol": args.symbol,
                    "partition": args.partition,
                    "closed_trades": result["metrics"]["closed_trades"],
                    "fully_settled": result["fully_settled"],
                    "result_hash": digest(result),
                    "execution_enabled": False,
                }
            ),
            flush=True,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
