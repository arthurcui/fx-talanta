"""Read-only diagnosis of the retained structural study, never a trading replay.

Reconcile stored decisions, bar timestamps and original quote rows. The optional
timestamp-only sensitivity check neither evaluates a signal nor simulates fills.
Write an exclusive new receipt outside the original study directory.
"""

import argparse
import json
import sqlite3
from bisect import bisect_right
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from pathlib import Path

D = Decimal
LATENCY = timedelta(milliseconds=250)
REPO = Path(__file__).resolve().parents[2]
PINNED_MANIFEST = "347f376536387cbd75bc84a47ae5612bdca8211088f29e85e87489f7bf5a6f73"
PINNED_INDEX = "83da17cedb8aa0b532a7141308a2bfe859d82d3d54dca6588f0e669e3ae2a02f"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(path):
    value = sha256()
    with path.open("rb") as stream:
        while part := stream.read(1024 * 1024):
            value.update(part)
    return value.hexdigest()


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def at(value):
    return datetime.fromisoformat(value)


def milliseconds(value):
    return int((value - datetime(1970, 1, 1, tzinfo=UTC)).total_seconds() * 1000)


def file_inventory(root):
    return {
        p.relative_to(root).as_posix(): digest(p) for p in sorted(root.rglob("*")) if p.is_file()
    }


def gap_kind(left, right):
    if left.weekday() == 4 and right.weekday() == 6:
        return "OBSERVED_WEEKEND_BOUNDARY"
    if left == at("2026-06-01T04:00:00+00:00") and right == at("2026-06-01T07:00:00+00:00"):
        return "MONTH_JOIN_OMISSION"
    return "OTHER_GAP"


def guard(times, cutoff):
    # Independent reconstruction of the frozen evaluator's clock-contiguity gate.
    visible = {tf: values[: bisect_right(values, cutoff - LATENCY)] for tf, values in times.items()}
    h1, m15 = visible["H1"], visible["M15"]
    reasons, kinds = [], set()
    if len(h1) < 53 or len(m15) < 15:
        reasons.append("INSUFFICIENT_BARS")
    for tf, series, count, step in (("H1", h1, 53, 60), ("M15", m15, 15, 15)):
        tail = series[-count:]
        gaps = [
            (a, b) for a, b in zip(tail, tail[1:], strict=False) if b - a != timedelta(minutes=step)
        ]
        if gaps:
            reasons.append(tf + "_NOT_CLOCK_CONTIGUOUS")
            if tf == "H1":
                kinds.update(gap_kind(a, b) for a, b in gaps)
    if h1 and cutoff - h1[-1] >= timedelta(hours=1):
        reasons.append("H1_STALE")
    if m15 and cutoff >= m15[-1] + LATENCY + timedelta(seconds=60):
        reasons.append("M15_STALE")
    return reasons, sorted(kinds)


def missing_bars(db, metadata):
    """Find fully bracketed quote buckets omitted from stored OHLC metadata."""
    known = {(b["timeframe"], at(b["close_at"])) for b in metadata["bars"]}
    lo, hi = db.execute("SELECT min(at_ms),max(at_ms) FROM ticks").fetchone()
    missing = []
    for minutes in (15, 60):
        width = minutes * 60_000
        tf = "M15" if minutes == 15 else "H1"
        query = (
            "SELECT CAST(at_ms / ? AS INTEGER)*?,count(*),min(at_ms),max(at_ms),"
            "count(DISTINCT CAST(at_ms / 60000 AS INTEGER)) FROM ticks GROUP BY 1"
        )
        for bucket, count, first, last, occupied in db.execute(query, (width, width)):
            close = datetime.fromtimestamp((bucket + width) / 1000, UTC)
            if bucket < lo or bucket + width > hi or (tf, close) in known:
                continue
            ticks = list(
                db.execute(
                    "SELECT at_ms,bid FROM ticks WHERE at_ms>=? AND at_ms<? ORDER BY at_ms,seq",
                    (bucket, bucket + width),
                )
            )
            values = [D(row[1]) for row in ticks]
            ohlc = [str(values[0]), str(max(values)), str(min(values)), str(values[-1])]
            intervals = [b[0] - a[0] for a, b in zip(ticks, ticks[1:], strict=False)]
            missing.append(
                dict(
                    timeframe=tf,
                    close_at=close.isoformat(),
                    quote_rows=count,
                    occupied_minutes=occupied,
                    expected_minutes=minutes,
                    first_quote_at=datetime.fromtimestamp(first / 1000, UTC).isoformat(),
                    last_quote_at=datetime.fromtimestamp(last / 1000, UTC).isoformat(),
                    maximum_internal_quote_gap_seconds=str(D(max(intervals)) / 1000),
                    reconstructed_ohlc_sha256=sha256(json.dumps(ohlc).encode()).hexdigest(),
                )
            )
    return missing


def diagnose(root):
    manifest = read(root / "manifest.json")
    index = root / "datasets/ticks.sqlite"
    canonical_manifest = sha256(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    require(canonical_manifest == PINNED_MANIFEST, "different preregistration")
    require(digest(index) == PINNED_INDEX, "prepared index changed")
    original = read(REPO / "docs/evidence/structural-pullback-20261119.json")
    arms = [read(root / name) for name in ("confirmation.json", "first-touch.json")]
    for item, receipt, filename in zip(
        arms, original["results"], ("confirmation.json", "first-touch.json"), strict=True
    ):
        require(digest(root / filename) == receipt["result_file_sha256"], "result changed")
        require(item["id"] == receipt["result_id"], "wrong result identity")
        require(item["payload"]["engine_sha256"] == manifest["engine_sha256"], "engine mismatch")
        result = item["payload"]["result"]
        require(result["experiment"]["policy"] == manifest["risk_policy"], "risk policy mismatch")
        require(
            not result["execution_enabled"]
            and not result["risk_halt"]
            and not result["integrity_halt"]
            and result["fully_settled"],
            "wrong run state",
        )
    primary, control = [item["payload"]["result"] for item in arms]
    decisions = primary["decisions"]
    require(all(d["action"] == "HOLD" for d in decisions), "entry candidate found")
    require(not primary["deals"], "confirmation fills found")
    db = sqlite3.connect(index.resolve().as_uri() + "?mode=ro&immutable=1", uri=True)
    try:
        metadata = json.loads(db.execute("SELECT value FROM metadata").fetchone()[0])
        omitted = missing_bars(db, metadata)
        rows = db.execute("SELECT count(*) FROM ticks").fetchone()[0]
    finally:
        db.close()
    times = {
        tf: sorted(at(b["close_at"]) for b in metadata["bars"] if b["timeframe"] == tf)
        for tf in ("M15", "H1")
    }
    restored_times = {
        tf: sorted(values + [at(b["close_at"]) for b in omitted if b["timeframe"] == tf])
        for tf, values in times.items()
    }
    days, combinations, reason_counts = defaultdict(Counter), Counter(), Counter()
    repaired_cutoffs, london = [], []
    for decision in decisions:
        cutoff = at(decision["as_of"])
        reasons, kinds = guard(times, cutoff)
        require(
            bool(reasons) == (decision["reason"] == "GAPPED_OR_STALE_INPUTS"),
            "input-gate reconstruction differs from retained decision",
        )
        if "LONDON" not in decision["market_session"]["active"]:
            continue
        london.append(decision)
        day = days[cutoff.date().isoformat()]
        day["decision_cutoffs"] += 1
        day["blocked_by_input_gate" if reasons else "passed_input_gate"] += 1
        if reasons:
            reason_counts.update(reasons)
            combinations[" + ".join(kinds)] += 1
            if not guard(restored_times, cutoff)[0]:
                repaired_cutoffs.append(cutoff.isoformat())
    opportunities = primary["structural_setups"]["opportunities"]
    twin = control["structural_setups"]["opportunities"]
    require(
        [{k: v for k, v in s.items() if k != "entry"} for s in opportunities]
        == [{k: v for k, v in s.items() if k != "entry"} for s in twin],
        "unmatched setups",
    )
    funnel, terminals, paths = Counter(), Counter(), []
    m15 = sorted(
        (b for b in metadata["bars"] if b["timeframe"] == "M15"), key=lambda b: at(b["close_at"])
    )
    for setup, match in zip(opportunities, twin, strict=True):
        transitions = setup["transitions"]
        states = {t["state"] for t in transitions}
        funnel.update(states)
        touched = next((t for t in transitions if t["state"] == "TOUCHED"), None)
        terminal = transitions[-1]
        terminals[("TOUCHED" if touched else "UNTOUCHED") + ":" + terminal["reason"]] += 1
        path = dict(
            setup_id=setup["setup_id"],
            side=setup["side"],
            known_at=setup["known_at"],
            transitions=transitions,
            expires_at=setup["expires_at"],
        )
        if touched:
            selected = [b for b in m15 if at(b["close_at"]) + LATENCY <= at(touched["at"])][-4:]
            ranges = [D(b["high"]) - D(b["low"]) for b in selected]
            prior, recent = sum(ranges[:2]), sum(ranges[2:])
            require(
                prior == D(setup["range_comparison"]["prior"])
                and recent == D(setup["range_comparison"]["recent"]),
                "range mismatch",
            )
            require((recent <= prior) == setup["weakening"], "weakening flag mismatch")
            path.update(
                weakening=setup["weakening"],
                prior_two_ranges_pips=str(prior / D("0.0001")),
                recent_two_ranges_pips=str(recent / D("0.0001")),
                recent_to_prior_range_ratio=str(recent / prior),
            )
            deals = match["entry"]["deals"]
            path["control_outcome"] = dict(
                entry_at=deals[0]["at"],
                exit_at=deals[-1]["at"],
                # This is the actual control result, not a hypothetical confirmation fill.
                deal_actions=[d["action"] for d in deals],
            )
        paths.append(path)
    h1 = times["H1"]
    gaps = [
        dict(
            left=a.isoformat(),
            right=b.isoformat(),
            elapsed_hours=(b - a).total_seconds() / 3600,
            classification=gap_kind(a, b),
        )
        for a, b in zip(h1, h1[1:], strict=False)
        if b - a != timedelta(hours=1)
    ]
    require(rows == primary["coverage"]["ticks"] == control["coverage"]["ticks"], "row mismatch")
    return dict(
        schema="structural-confirmation-diagnosis/1",
        execution_enabled=False,
        strategy_replayed=False,
        validation_or_holdout_opened=False,
        manifest_sha256=PINNED_MANIFEST,
        manifest_file_sha256=digest(root / "manifest.json"),
        index_sha256=PINNED_INDEX,
        engine_sha256=manifest["engine_sha256"],
        result_ids=[a["id"] for a in arms],
        window=[manifest["start"], manifest["end"]],
        quote_rows=rows,
        risk_policy=manifest["risk_policy"],
        confirmation=dict(
            decisions=len(decisions),
            all_decisions_hold=True,
            entry_candidates=0,
            deals=0,
            risk_rejections_after_entry_candidate=0,
            decision_reasons=dict(Counter(d["reason"] for d in decisions)),
        ),
        funnel=dict(funnel),
        terminal_partition=dict(terminals),
        opportunities=paths,
        input_eligibility=dict(
            london_decision_cutoffs=len(london),
            blocked=sum(combinations.values()),
            blocked_h1_combinations=dict(combinations),
            overlapping_guard_reasons=dict(reason_counts),
            by_date=dict(days),
        ),
        h1_discontinuities=gaps,
        quote_buckets_missing_from_bars=omitted,
        boundary_timestamp_sensitivity=dict(
            scope="TIMESTAMP_GATE_ONLY; no signal, price-feature, order or P&L evaluation",
            additional_existing_london_cutoffs_passing=len(repaired_cutoffs),
            cutoffs=repaired_cutoffs,
            remaining_blocked=sum(combinations.values()) - len(repaired_cutoffs),
        ),
        interpretation="Missing-input defect plus restrictive setup path; no profitability verdict",
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("study", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root, output = args.study.resolve(), args.output.resolve()
    require(not output.is_relative_to(root), "diagnostic output must be outside original evidence")
    require(not output.exists(), "never overwrite an earlier diagnostic")
    before = file_inventory(root)
    report = diagnose(root)
    require(before == file_inventory(root), "original study files changed during diagnosis")
    report["original_files_unchanged"] = True
    report["original_file_count"] = len(before)
    report["original_inventory_sha256"] = sha256(
        json.dumps(before, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    report["analysis_script_sha256"] = digest(Path(__file__))
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(report, stream, indent=2)
        stream.write("\n")
    print(
        json.dumps(
            {
                k: report[k]
                for k in (
                    "confirmation",
                    "funnel",
                    "input_eligibility",
                    "quote_buckets_missing_from_bars",
                    "original_files_unchanged",
                )
            }
        )
    )


if __name__ == "__main__":
    main()
