"""Independently reconcile a completed input repair against retained originals."""

import argparse
import json
from collections import Counter
from datetime import datetime
from decimal import Decimal
from hashlib import sha256
from pathlib import Path

from fx_talanta.research.replay import digest
from fx_talanta.research.spool import file_hash
from tools.research.correct_structural_inputs import inventory, readonly, require
from tools.research.structural_study import save
from tools.research.verify_structural_study import verify


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def summarize(root):
    results = []
    for name in ("confirmation.json", "first-touch.json"):
        item = read(root / name)
        result = item["payload"]["result"]
        opportunities = result["structural_setups"]["opportunities"]
        cutoffs = [d for d in result["decisions"] if "market_session" in d]
        require(
            all(
                d["action"] == "SUBMITTED_TO_SIMULATOR"
                for d in result["decisions"]
                if "market_session" not in d
            ),
            "unclassified decision without session context",
        )
        london = [d for d in cutoffs if "LONDON" in d["market_session"]["active"]]
        touched = [
            s for s in opportunities if any(t["state"] == "TOUCHED" for t in s["transitions"])
        ]
        results.append(
            dict(
                arm=item["payload"]["rules"]["arm"],
                result_id=item["id"],
                watched=len(opportunities),
                transitions=dict(
                    Counter(t["state"] for s in opportunities for t in s["transitions"])
                ),
                decisions=len(result["decisions"]),
                signal_cutoffs=len(cutoffs),
                london_cutoffs=len(london),
                london_input_blocks=sum(
                    d.get("reason") == "GAPPED_OR_STALE_INPUTS" for d in london
                ),
                closed_trades=result["metrics"]["closed_trades"],
                winning_trades=result["metrics"]["winning_trades"],
                touched_with_weakening=sum(s["weakening"] for s in touched),
                retested_paths=[
                    {k: s[k] for k in ("setup_id", "side", "weakening", "transitions")}
                    for s in touched
                    if any(t["state"] == "RETESTED" for t in s["transitions"])
                ],
                net_realized_pnl=result["net_realized_pnl"],
                drawdown_fraction=result["metrics"]["maximum_observed_drawdown_fraction"],
                fully_settled=result["fully_settled"],
                risk_halt=result["risk_halt"],
                integrity_halt=result["integrity_halt"],
            )
        )
    return results


def verify_correction(original, corrected):
    before = inventory(original)
    require(
        before == read(corrected / "original-evidence-fingerprints.json"),
        "original evidence differs from pre-run fingerprints",
    )
    old_manifest, manifest = [read(r / "manifest.json") for r in (original, corrected)]
    old_bundle, bundle = [read(r / "datasets/structural-index.json") for r in (original, corrected)]
    for key in ("start", "end", "arms", "risk_policy", "economic_acceptance", "execution_enabled"):
        require(manifest[key] == old_manifest[key], "entry/risk/window/authority changed: " + key)
    for key in (
        "experiment",
        "latency_ms",
        "assume_research_inputs",
        "minimum_closed_trades",
        "maximum_drawdown_fraction",
        "acquired_history",
        "development_only",
    ):
        require(bundle[key] == old_bundle[key], "research assumption changed: " + key)
    require(manifest["parent_manifest_sha256"] == digest(old_manifest), "wrong parent")
    require(bundle["input_calendar"] == manifest["input_calendar"], "calendar changed")
    require(
        bundle["input_calendar"]["index_sha256"] == file_hash(corrected / "datasets/ticks.sqlite"),
        "calendar index binding changed",
    )
    require(
        bundle["input_calendar"]["evidence_sha256"]
        == file_hash(corrected / "weekend-reconciliation.json"),
        "calendar evidence changed",
    )
    a, b = [readonly(r / "datasets/ticks.sqlite") for r in (original, corrected)]
    try:
        count, quote_digest = 0, sha256()
        for left, right in zip(
            a.execute("SELECT * FROM ticks ORDER BY at_ms,seq"),
            b.execute("SELECT * FROM ticks ORDER BY at_ms,seq"),
            strict=True,
        ):
            require(left == right, "quote data or source sequence changed")
            quote_digest.update((json.dumps(left, separators=(",", ":")) + "\n").encode())
            count += 1
        ma, mb = [
            json.loads(db.execute("SELECT value FROM metadata").fetchone()[0]) for db in (a, b)
        ]

        def bars(meta):
            return {
                (r["timeframe"], datetime.fromisoformat(r["close_at"])): r for r in meta["bars"]
            }

        old_bars, new_bars = bars(ma), bars(mb)
        require(all(new_bars[k] == v for k, v in old_bars.items()), "an old bar changed")
        added = []
        for tf, close in sorted(set(new_bars) - set(old_bars)):
            width = (60 if tf == "H1" else 15) * 60_000
            end = int(close.timestamp() * 1000)
            bids = [
                Decimal(r[0])
                for r in a.execute(
                    "SELECT bid FROM ticks WHERE at_ms>=? AND at_ms<? ORDER BY at_ms,seq",
                    (end - width, end),
                )
            ]
            bar = new_bars[(tf, close)]
            require(
                [Decimal(bar[k]) for k in ("open", "high", "low", "close")]
                == [bids[0], max(bids), min(bids), bids[-1]],
                "OHLC does not match original ticks",
            )
            added.append(
                dict(timeframe=tf, close_at=close.isoformat(), original_quote_rows=len(bids))
            )
        require(len(added) == 4 and count == 660471, "unexpected repair scope")
    finally:
        a.close()
        b.close()
    summaries = [summarize(root) for root in (original, corrected)]
    independent = verify(corrected)  # Hash chains, all equity observations, fills, fees and risk.
    require(before == inventory(original), "original evidence changed during verification")
    return dict(
        schema="structural-input-repair-verification/1",
        verified=True,
        execution_enabled=False,
        qualified_for_paper=False,
        economic_acceptance=False,
        original_manifest_sha256=digest(old_manifest),
        corrected_manifest_sha256=digest(manifest),
        frozen_source=read(corrected / "source-revision.json"),
        unchanged_original_files=len(before),
        original_inventory_sha256=digest(before),
        identical_quote_rows=count,
        quote_rows_sha256=quote_digest.hexdigest(),
        unchanged_original_bars=len(old_bars),
        restored_bars=added,
        unchanged_entry_risk_costs_window=True,
        input_calendar=manifest["input_calendar"],
        original=summaries[0],
        corrected=summaries[1],
        independent_replay_verification=independent,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("original", type=Path)
    parser.add_argument("corrected", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    report = verify_correction(args.original, args.corrected)
    save(args.output, report)
    print(json.dumps({k: report[k] for k in ("verified", "unchanged_original_files", "corrected")}))
