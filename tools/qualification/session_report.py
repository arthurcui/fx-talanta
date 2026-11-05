"""Verify private full-session artifacts and export only sanitized aggregates."""

import argparse
import json
import sqlite3
from collections import Counter
from decimal import Decimal, localcontext
from pathlib import Path

from fx_talanta.research.replay import digest, read
from fx_talanta.research.session_study import PHASES, Plan, background_priority, verify_phase, write
from fx_talanta.research.spool import file_hash


def reconcile_fills(result):
    """Rebuild balances and exposure from fills, independently of engine summaries."""
    with localcontext() as context:
        context.prec = 50
        capital = Decimal(result["experiment"]["policy"]["capital"])
        balance = capital
        exposure = {}
        for fill in result["deals"]:
            balance += Decimal(fill["realized"])
            position = fill["position_id"]
            volume = Decimal(fill["volume"])
            exposure[position] = exposure.get(position, Decimal(0)) + (
                volume if fill["action"] == "ENTER" else -volume
            )
            if exposure[position] < 0:
                raise ValueError("close exceeds owned simulated exposure")
        # Engine arithmetic uses Decimal precision 34; tolerate only round-off far
        # below a currency cent when independently accumulating at precision 50.
        if abs(balance - Decimal(result["balance"])) > Decimal("1e-25"):
            raise ValueError("fill-ledger balance mismatch")
        if sum(v > 0 for v in exposure.values()) != result["open_positions"]:
            raise ValueError("fill-ledger exposure mismatch")
        if sum(v == 0 for v in exposure.values()) != result["metrics"]["closed_trades"]:
            raise ValueError("closed-trade count mismatch")
        return {
            "balance_from_fills": True,
            "exposure_from_fills": True,
            "arithmetic_tolerance_usd": "1e-25",
        }


def summarize(result, receipt):
    with localcontext() as context:
        context.prec = 34
        capital = Decimal(result["experiment"]["policy"]["capital"])
        cost_totals = {
            key: str(sum((Decimal(c[key]) for c in result["fill_costs"]), Decimal(0)))
            for key in ("commission", "slippage", "half_spread")
        }
        cost_totals["financing"] = str(
            sum((Decimal(c["charge"]) for c in result["financing"]), Decimal(0))
        )
        return {
            "symbol": result["experiment"]["symbol"],
            "partition": result["partition"],
            "coverage": result["coverage"],
            "metrics": result["metrics"],
            "net_realized_return_percent": str(Decimal(result["net_realized_pnl"]) / capital * 100),
            "maximum_observed_drawdown_percent": str(
                Decimal(result["metrics"]["maximum_observed_drawdown_fraction"]) * 100
            ),
            "costs_usd": cost_totals,
            "cost_note": result["cost_note"],
            "decision_actions": dict(Counter(d["action"] for d in result["decisions"])),
            "entry_fills": sum(d["action"] == "ENTER" for d in result["deals"]),
            "close_fills": sum(d["action"] == "CLOSE" for d in result["deals"]),
            "open_positions": result["open_positions"],
            "unsettled_entry_orders": result["unsettled_entry_orders"],
            "fully_settled": result["fully_settled"],
            "journal_tip": result["journal_tip"],
            "receipt": receipt,
            "independently_reconstructed": True,
            "fill_ledger_verification": reconcile_fills(result),
        }


def report(directory):
    manifest = json.loads(read(directory / "manifest.json"))
    registration = json.loads(read(directory / "registration.json"))
    if registration["manifest_hash"] != digest(manifest):
        raise ValueError("registration mismatch")
    plan = Plan.model_validate(manifest["plan"])
    for index in manifest["indexes"].values():
        if file_hash(Path(index["path"])) != index["sha256"]:
            raise ValueError("registered source changed")
    sessions = []
    for phase in PHASES:
        for experiment in plan.experiments:
            output = directory / f"{experiment.symbol}-{phase}"
            verify_phase(output, manifest)  # Require successful verification marker too.
            result = verify_phase(output, manifest, full=True)
            index_path = Path(manifest["indexes"][experiment.symbol]["path"])
            start, end = experiment.window(phase)
            bounds = tuple(int(t.timestamp() * 1000) - plan.latency_ms for t in (start, end))
            connection = sqlite3.connect(
                index_path.resolve().as_uri() + "?mode=ro&immutable=1", uri=True
            )
            try:
                expected = connection.execute(
                    "SELECT count(*) FROM ticks WHERE at_ms>=? AND at_ms<?", bounds
                ).fetchone()[0]
            finally:
                connection.close()
            if expected != result["coverage"]["ticks"]:
                raise ValueError("source row count differs from replayed ticks")
            summary = summarize(result, json.loads(read(output / "receipt.json")))
            summary["source_rows_independently_counted"] = expected
            sessions.append(summary)
    return {
        "schema": "full-session-sanitized-report/1",
        "manifest_hash": digest(manifest),
        "engine_sha256": manifest["engine_sha256"],
        "runtime_observation": json.loads(read(directory / "runtime-observation.json"))
        if (directory / "runtime-observation.json").exists()
        else None,
        "plan": manifest["plan"],
        "indexes": {
            symbol: {k: v for k, v in index.items() if k != "path"}
            for symbol, index in manifest["indexes"].items()
        },
        "sessions": sessions,
        "total_ticks": sum(s["coverage"]["ticks"] for s in sessions),
        "total_closed_trades": sum(s["metrics"]["closed_trades"] for s in sessions),
        "all_sessions_flat": all(s["fully_settled"] for s in sessions),
        "execution_enabled": False,
        "m1_qualified": False,
        "economic_acceptance": False,
        "limitations": [
            "Three consecutive days, one chronological split, not multiple walk-forward folds.",
            "Independent cold-start accounts; no combined equity curve or compounded return.",
            "Calendar/news/history readiness assumed; receipt latency modeled, not measured.",
            "Unqualified revisions/session gaps; generic instrument and cost assumptions.",
            "No parameter tuning, annualization, significance claim or broker execution inference.",
            "Original pilot, M1 gaps and broader M2 fault requirements remain unchanged.",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    background_priority()
    result = report(args.study)
    write(args.output, result)
    print(
        json.dumps(
            {k: result[k] for k in ("total_ticks", "total_closed_trades", "all_sessions_flat")}
        )
    )


if __name__ == "__main__":
    main()
