"""Frozen advancing-origin B01 study; serial offline sessions, exclusive evidence."""

import argparse
import json
import platform
import sqlite3
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
from typing import Literal
from uuid import NAMESPACE_URL, uuid5

from pydantic import model_validator

from fx_talanta.domain.models import FrozenModel, Timestamp
from fx_talanta.domain.offline import Policy
from fx_talanta.research.broker_costs import BrokerCosts
from fx_talanta.research.replay import Costs, digest, execute_timeline
from fx_talanta.research.session_study import (
    TrackedEvents,
    background_priority,
    engine_hash,
    timeline,
    verify_phase,
    write,
)
from fx_talanta.research.spool import EquitySpool, Spool, file_hash
from fx_talanta.research.tick_index import TickIndex, milliseconds
from tools.qualification.session_report import summarize


class Session(FrozenModel):
    name: str
    symbol: Literal["EURUSD", "USDJPY"]
    start: Timestamp
    end: Timestamp
    costs: Costs | BrokerCosts
    policy: Policy

    @model_validator(mode="after")
    def bounded(self):
        if self.end - self.start != timedelta(days=1):
            raise ValueError("one full UTC day required")
        if self.start.hour or self.start.minute or self.start.second or self.start.microsecond:
            raise ValueError("UTC midnight required")
        if self.policy.maximum_positions != 1 or self.policy.quote_age_seconds != 2:
            raise ValueError("frozen one-position/two-second policy required")
        return self

    def window(self, partition):
        if partition != "evaluation":
            raise ValueError("evaluation only; no fitting or optimization")
        return self.start, self.end


def wrapper_hash():
    return digest(
        {
            name: sha256(
                (Path(__file__).parent / name).read_bytes().replace(b"\r\n", b"\n")
            ).hexdigest()
            for name in ("walkforward.py", "session_report.py")
        }
    )


def register(directory, protocol, indexes):
    if protocol["execution_enabled"] is not False:
        raise ValueError("offline-only protocol required")
    dates = [f["evaluation_start"] for f in protocol["folds"]]
    if (
        len(dates) != 4
        or dates != sorted(set(dates))
        or [f["role"] for f in protocol["folds"]] != ["walkforward"] * 3 + ["final_holdout"]
        or {d[:10] for d in dates} & set(protocol["prior_outcomes_examined"])
        or set(protocol["arms"]) != {"base", "stress"}
    ):
        raise ValueError("three advancing folds and new final outcome holdout required")
    pinned = {}
    for symbol in ("EURUSD", "USDJPY"):
        path = Path(indexes[symbol]).resolve()
        if file_hash(path) != protocol["index_hashes"][symbol]:
            raise ValueError("source differs from preregistered audit")
        pinned[symbol] = str(path)
    jobs = []
    for fold in protocol["folds"]:
        day = datetime.fromisoformat(fold["evaluation_start"])
        for arm, costs in protocol["arms"].items():
            for symbol in ("EURUSD", "USDJPY"):
                session = Session(
                    name=f"{fold['name']}-{arm}-{symbol.lower()}",
                    symbol=symbol,
                    start=day,
                    end=day + timedelta(days=1),
                    costs=costs,
                    policy=Policy.model_validate(protocol["policy"]),
                )
                index = TickIndex(Path(pinned[symbol]))
                try:
                    h1 = sum(
                        b.timeframe == "H1" and b.available_at < day
                        for b in index.bars(protocol["latency_ms"])
                    )
                    count = index.db.execute(
                        "SELECT count(*) FROM ticks WHERE at_ms>=? AND at_ms<?",
                        (
                            milliseconds(day) - protocol["latency_ms"],
                            milliseconds(session.end) - protocol["latency_ms"],
                        ),
                    ).fetchone()[0]
                    if h1 < 200 or not 0 < count <= 300000:
                        raise ValueError("warm-up or complete-session tick bound failed")
                finally:
                    index.close()
                jobs.append(
                    {
                        "fold": fold["name"],
                        "role": fold["role"],
                        "arm": arm,
                        "expected_ticks": count,
                        "prior_h1_bars": h1,
                        "session": session.model_dump(mode="json"),
                    }
                )
    manifest = {
        "schema": "walkforward/1",
        "protocol": protocol,
        "jobs": jobs,
        "paths": pinned,
        "engine_sha256": engine_hash(),
        "wrapper_sha256": wrapper_hash(),
        "execution_enabled": False,
        "registered_at": datetime.now(UTC).isoformat(),
        "runtime": {"python": platform.python_version(), "sqlite": sqlite3.sqlite_version},
    }
    directory.mkdir(parents=True, exist_ok=False)
    write(directory / "manifest.json", manifest)
    write(directory / "registration.json", {"manifest_hash": digest(manifest)})
    return manifest


def run_job(directory, manifest, job):
    session = Session.model_validate(job["session"])
    output = directory / session.name
    output.mkdir(exist_ok=False)
    index = journal = equity = None
    try:
        path = Path(manifest["paths"][session.symbol])
        expected_hash = manifest["protocol"]["index_hashes"][session.symbol]
        if file_hash(path) != expected_hash:
            raise ValueError("changed index")
        index = TickIndex(path)
        latency = manifest["protocol"]["latency_ms"]
        bars = index.bars(latency)
        metadata = SimpleNamespace(
            bars=bars,
            history_complete=True,
            provenance="HISTORICAL_UNQUALIFIED",
            source=f"HistData index SHA256 {expected_hash}",
        )
        events = TrackedEvents(
            index.events(session.start, session.end, latency, True), session.start, session.end
        )
        journal = Spool(output / "journal.jsonl.gz")
        equity = EquitySpool(output / "equity.jsonl.gz", session.policy.capital)
        result, _ = execute_timeline(
            metadata,
            session,
            "evaluation",
            timeline(bars, events, session.start, session.end),
            uuid5(NAMESPACE_URL, digest({"manifest": digest(manifest), "job": job})),
            journal_sink=journal,
            samples_sink=equity,
        )
        journal.close()
        equity.close()
        result["coverage"] = events.report()
        if result["coverage"]["ticks"] != job["expected_ticks"]:
            raise ValueError("source tick reconciliation failed")
        if file_hash(path) != expected_hash:
            raise ValueError("source changed during replay")
        write(output / "result.json", result)
        receipt = {
            "manifest_hash": digest(manifest),
            "result_hash": digest(result),
            "journal": journal.receipt(),
            "equity": equity.receipt(),
        }
        write(output / "receipt.json", receipt)
        verify_phase(output, manifest, full=True)
        summary = summarize(result, receipt)
        write(output / "verified.json", {"reconstructed": True, "result_hash": digest(result)})
        return summary
    except Exception as error:
        write(
            output / "failed.json",
            {
                "error_type": type(error).__name__,
                "reason": str(error)[:500],
                "retry_allowed": False,
            },
        )
        raise
    finally:
        if index:
            index.close()
        for sink in (journal, equity):
            if sink is not None and not sink.raw.closed:
                sink.close()


def verdict(sessions):
    """Prespecified research screen, never operational or statistical acceptance."""
    if any(not s["fully_settled"] for s in sessions):
        return "INSUFFICIENT_EVIDENCE_UNRESOLVED_EXPOSURE"
    if len(sessions) != 16:
        return "INSUFFICIENT_EVIDENCE_INCOMPLETE"
    tests = [s for s in sessions if s["role"] == "final_holdout"]
    if len(tests) != 4:
        return "INSUFFICIENT_EVIDENCE_INCOMPLETE"
    if any(Decimal(s["net_realized_return_percent"]) <= 0 for s in tests):
        return "REJECT_FOR_PROMOTION"
    folds = [s for s in sessions if s["role"] == "walkforward"]
    for symbol in ("EURUSD", "USDJPY"):
        for arm in ("base", "stress"):
            selected = [s for s in folds if s["symbol"] == symbol and s["arm"] == arm]
            if len(selected) != 3:
                return "INSUFFICIENT_EVIDENCE_INCOMPLETE"
            if sum(Decimal(s["net_realized_return_percent"]) > 0 for s in selected) < 2:
                return "REJECT_FOR_PROMOTION"
    return "KEEP_FOR_FURTHER_RESEARCH_ONLY"


def run(directory):
    manifest = json.loads((directory / "manifest.json").read_text())
    receipt = json.loads((directory / "registration.json").read_text())
    if (
        receipt["manifest_hash"] != digest(manifest)
        or engine_hash() != manifest["engine_sha256"]
        or wrapper_hash() != manifest["wrapper_sha256"]
    ):
        raise ValueError("frozen engine or registry changed")
    # No automatic resume: starting is exclusive, including after a failure.
    write(directory / "started.json", {"at": datetime.now(UTC).isoformat()})
    sessions = []
    try:
        for job in manifest["jobs"]:
            if (
                engine_hash() != manifest["engine_sha256"]
                or wrapper_hash() != manifest["wrapper_sha256"]
            ):
                raise ValueError("frozen source changed")
            print(json.dumps({"starting": job["session"]["name"]}), flush=True)
            summary = run_job(directory, manifest, job)
            summary.update({k: job[k] for k in ("fold", "role", "arm", "prior_h1_bars")})
            sessions.append(summary)
            write(directory / f"summary-{len(sessions):02}.json", summary)
            print(
                json.dumps({"completed": len(sessions), "flat": summary["fully_settled"]}),
                flush=True,
            )
            if not summary["fully_settled"]:
                break
    finally:
        write(
            directory / "conclusion.json",
            {
                "schema": "walkforward-report/1",
                "manifest_hash": digest(manifest),
                "engine_sha256": manifest["engine_sha256"],
                "protocol": manifest["protocol"],
                "sessions": sessions,
                "completed_sessions": len(sessions),
                "planned_sessions": len(manifest["jobs"]),
                "verdict": verdict(sessions),
                "no_trade_comparator": {
                    "return_percent": "0",
                    "drawdown_percent": "0",
                    "costs": "0",
                    "cash_interest": "EXCLUDED",
                },
                "economic_acceptance": False,
                "m1_qualified": False,
                "execution_enabled": False,
            },
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("register", "run"))
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--protocol", type=Path)
    parser.add_argument("--index", action="append", default=[])
    args = parser.parse_args()
    background_priority()
    if args.command == "register":
        manifest = register(
            args.directory,
            json.loads(args.protocol.read_text()),
            dict(x.split("=", 1) for x in args.index),
        )
        print(json.dumps({"registered": digest(manifest), "jobs": len(manifest["jobs"])}))
    else:
        run(args.directory)


if __name__ == "__main__":
    main()
