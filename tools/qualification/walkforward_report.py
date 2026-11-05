"""Independently reverify frozen-session artifacts and export a sanitized verdict."""

import argparse
import json
from decimal import Decimal
from hashlib import sha256
from pathlib import Path

from fx_talanta.research.replay import digest
from fx_talanta.research.session_study import background_priority, verify_phase, write
from fx_talanta.research.spool import file_hash, rows
from fx_talanta.research.tick_index import TickIndex, milliseconds
from tools.qualification.session_report import summarize
from tools.qualification.walkforward import Session, verdict


def report(directory):
    manifest = json.loads((directory / "manifest.json").read_text())
    registration = json.loads((directory / "registration.json").read_text())
    conclusion = json.loads((directory / "conclusion.json").read_text())
    if registration["manifest_hash"] != digest(manifest):
        raise ValueError("registration mismatch")
    if conclusion["manifest_hash"] != digest(manifest):
        raise ValueError("conclusion mismatch")
    if any(
        conclusion[k] is not False
        for k in ("economic_acceptance", "m1_qualified", "execution_enabled")
    ):
        raise ValueError("unsupported qualification claim")
    if conclusion["no_trade_comparator"] != {
        "return_percent": "0",
        "drawdown_percent": "0",
        "costs": "0",
        "cash_interest": "EXCLUDED",
    }:
        raise ValueError("changed analytical comparator")
    for symbol, path in manifest["paths"].items():
        if file_hash(Path(path)) != manifest["protocol"]["index_hashes"][symbol]:
            raise ValueError("changed source index")
    sessions, unfinished = [], []
    for job in manifest["jobs"]:
        session = Session.model_validate(job["session"])
        output = directory / session.name
        if not (output / "verified.json").exists():
            unfinished.append(
                {
                    "name": session.name,
                    "state": "FAILED" if (output / "failed.json").exists() else "NOT_RUN",
                }
            )
            continue
        if unfinished:
            raise ValueError("execution advanced past an unverified predecessor")
        if sessions and not sessions[-1]["fully_settled"]:
            raise ValueError("execution advanced past unresolved exposure")
        verify_phase(output, manifest)
        result = verify_phase(output, manifest, full=True)
        if result["experiment"] != job["session"]:
            raise ValueError("experiment differs from registered job")
        index = TickIndex(Path(manifest["paths"][session.symbol]))
        try:
            delay = manifest["protocol"]["latency_ms"]
            expected = index.db.execute(
                "SELECT count(*) FROM ticks WHERE at_ms>=? AND at_ms<?",
                (milliseconds(session.start) - delay, milliseconds(session.end) - delay),
            ).fetchone()[0]
        finally:
            index.close()
        if expected != result["coverage"]["ticks"] or expected != job["expected_ticks"]:
            raise ValueError("independent source count mismatch")
        summary = summarize(result, json.loads((output / "receipt.json").read_text()))
        summary.update({k: job[k] for k in ("fold", "role", "arm", "prior_h1_bars")})
        states = {}
        for sample in rows(output / "equity.jsonl.gz"):
            states[sample["state"]] = states.get(sample["state"], 0) + 1
        summary["equity_sample_states"] = states
        summary["source_rows_independently_counted"] = expected
        sessions.append(summary)
    saved = [
        {
            k: v
            for k, v in s.items()
            if k not in ("equity_sample_states", "source_rows_independently_counted")
        }
        for s in sessions
    ]
    if saved != conclusion["sessions"] or verdict(saved) != conclusion["verdict"]:
        raise ValueError("independent conclusion mismatch")
    groups = []
    unique_counts = {}
    for session in sessions:
        key = (session["fold"], session["symbol"])
        count = session["coverage"]["ticks"]
        if key in unique_counts and unique_counts[key] != count:
            raise ValueError("scenario source populations differ")
        unique_counts[key] = count
    for symbol in ("EURUSD", "USDJPY"):
        for arm in ("base", "stress"):
            group = [s for s in sessions if s["symbol"] == symbol and s["arm"] == arm]
            if not group:
                continue
            returns = [Decimal(s["net_realized_return_percent"]) for s in group]
            groups.append(
                {
                    "symbol": symbol,
                    "arm": arm,
                    "sessions": len(group),
                    "positive_sessions": sum(r > 0 for r in returns),
                    "closed_trades": sum(s["metrics"]["closed_trades"] for s in group),
                    "minimum_session_return_percent": str(min(returns)),
                    "maximum_session_return_percent": str(max(returns)),
                    "maximum_single_session_drawdown_percent": str(
                        max(Decimal(s["maximum_observed_drawdown_percent"]) for s in group)
                    ),
                }
            )
    return {
        **{
            k: conclusion[k]
            for k in (
                "schema",
                "manifest_hash",
                "engine_sha256",
                "protocol",
                "verdict",
                "no_trade_comparator",
                "economic_acceptance",
                "m1_qualified",
                "execution_enabled",
            )
        },
        "runtime": manifest["runtime"],
        "reporter_sha256": sha256(Path(__file__).read_bytes().replace(b"\r\n", b"\n")).hexdigest(),
        "sessions": sessions,
        "unfinished_jobs": unfinished,
        "completed_sessions": len(sessions),
        "planned_sessions": len(manifest["jobs"]),
        "replayed_ticks_including_scenario_reuse": sum(s["coverage"]["ticks"] for s in sessions),
        "unique_pair_day_ticks": sum(unique_counts.values()),
        "groups": groups,
        "independently_verified": True,
        "limitations": [
            "Four selected dates in one month; this is a fixed-parameter "
            "advancing-origin study, not fitted model validation.",
            "Earlier evaluation bars enter later expanding prefixes; day/account "
            "resets require verified flatness.",
            "Holdout strategy outcomes were unseen at registration; January prices "
            "and gaps were already audited.",
            "Scenarios and pairs are dependent; no summed returns, annualization, "
            "significance or profitability certification.",
            "No-trade comparator is analytical zero trading return without interest, "
            "not a separate broker account.",
            "Legacy costs and receipt latency are assumptions; readiness is "
            "counterfactual; original availability is unknown.",
            "Spread/slippage are embedded in fills; cost attribution is descriptive "
            "and must not be deducted again.",
            "M1, broader M2 fault gates and historical broker-cost qualification "
            "remain open; trading stays disabled.",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    background_priority()
    write(args.output, report(args.directory))


if __name__ == "__main__":
    main()
