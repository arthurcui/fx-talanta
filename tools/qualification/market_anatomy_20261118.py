"""Read-only, pinned exploratory market measurement; no trading or replay imports."""

import hashlib
import json
import math
import random
import sqlite3
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from statistics import mean, median

from fx_talanta.research.market_sessions import context, zone

OUT = Path("/review")
PLAN = json.loads((OUT / "plan.json").read_text(encoding="utf-8-sig"))
START = datetime.fromisoformat(PLAN["start_utc"])
END = datetime.fromisoformat(PLAN["end_utc_exclusive"])
START_MS, END_MS = int(START.timestamp() * 1000), int(END.timestamp() * 1000)


def sha(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for data in iter(lambda: f.read(1024 * 1024), b""):
            h.update(data)
    return h.hexdigest()


def percentile(xs, p):
    if not xs:
        return None
    xs = sorted(xs)
    t = (len(xs) - 1) * p
    lo, hi = math.floor(t), math.ceil(t)
    return xs[lo] + (xs[hi] - xs[lo]) * (t - lo)


def dist(xs):
    return dict(
        n=len(xs),
        mean=mean(xs) if xs else None,
        median=median(xs) if xs else None,
        p05=percentile(xs, 0.05),
        p95=percentile(xs, 0.95),
    )


def fresh(x):
    return x is not None and 0 <= x[0] <= 2000


def analyze(folder):
    bundle_path = folder / "acquired-index.json"
    bundle = json.loads(bundle_path.read_text())
    symbol = bundle["experiment"]["symbol"]
    assert START >= datetime.fromisoformat(bundle["experiment"]["start"].replace("Z", "+00:00"))
    assert END <= datetime.fromisoformat(
        bundle["experiment"]["training_end"].replace("Z", "+00:00")
    )
    path = folder / bundle["index_file"]
    before = sha(path)
    assert before == bundle["index_sha256"], "source fingerprint changed"
    print(json.dumps(dict(stage="reading_exposed_training", symbol=symbol)), flush=True)
    db = sqlite3.connect(path.resolve().as_uri() + "?mode=ro&immutable=1", uri=True)
    db.execute("PRAGMA query_only=ON")
    db.execute("PRAGMA cache_size=-8192")
    scale = Decimal(100000 if symbol == "EURUSD" else 1000)
    stats = Counter()
    snapshots = {}
    next_ms, previous, previous_key = START_MS, None, None
    seen_at_time = set()
    for seq, at, bid, ask in db.execute(
        "SELECT seq,at_ms,bid,ask FROM ticks WHERE at_ms>=? AND at_ms<? ORDER BY at_ms,seq",
        (START_MS, END_MS),
    ):
        stats["rows"] += 1
        key = (at, seq)
        assert previous_key is None or key > previous_key
        while next_ms < at:
            snapshots[next_ms] = (
                None if previous is None else (next_ms - previous[0], previous[1], previous[2])
            )
            next_ms += 60000
        b, a = Decimal(bid), Decimal(ask)
        assert b.is_finite() and a.is_finite() and 0 < b <= a
        assert b * scale == (b * scale).to_integral_value()
        assert a * scale == (a * scale).to_integral_value()
        b, a = int(b * scale), int(a * scale)
        stats["zero_spread_rows"] += a == b
        if previous_key is not None and previous_key[0] == at:
            stats["tied_timestamp_rows"] += 1
        else:
            seen_at_time.clear()
        stats["duplicate_timestamp_quote_rows"] += (b, a) in seen_at_time
        seen_at_time.add((b, a))
        previous_key, previous = key, (at, b, a)
    while next_ms < END_MS:
        snapshots[next_ms] = (
            None if previous is None else (next_ms - previous[0], previous[1], previous[2])
        )
        next_ms += 60000
    buckets = defaultdict(
        lambda: dict(expected=0, fresh=0, stale=0, no_quote=0, spreads=[], moves=[], costs=[])
    )
    daily = defaultdict(lambda: dict(expected=0, fresh=0))
    for at, q in snapshots.items():
        d = datetime.fromtimestamp(at / 1000, UTC)
        if d.weekday() >= 5:
            continue
        name = context(d)["regime"]
        b = buckets[name]
        b["expected"] += 1
        daily[d.date().isoformat()]["expected"] += 1
        if not fresh(q):
            b["no_quote" if q is None else "stale"] += 1
            continue
        b["fresh"] += 1
        daily[d.date().isoformat()]["fresh"] += 1
        b["spreads"].append((q[2] - q[1]) / 10)
        # Outcomes remain descriptive; never feed future values into a decision.
        other = snapshots.get(at + 15 * 60000)
        finish = d + timedelta(minutes=15)
        if fresh(other) and finish.date() == d.date() and context(finish)["regime"] == name:
            b["moves"].append(abs((other[1] + other[2]) - (q[1] + q[2])) / 20)
            b["costs"].append(((q[2] - q[1]) + (other[2] - other[1])) / 20)
    summary = []
    for name, b in buckets.items():
        summary.append(
            dict(
                session=name,
                expected_minutes=b["expected"],
                fresh_minutes=b["fresh"],
                source_fresh_fraction=b["fresh"] / b["expected"],
                stale_minutes=b["stale"],
                no_quote_minutes=b["no_quote"],
                spread_pips=dist(b["spreads"]),
                absolute_15m_mid_change_pips=dist(b["moves"]),
                endpoint_roundtrip_spread_pips=dist(b["costs"]),
            )
        )
    result = dict(
        symbol=symbol,
        index_sha256=before,
        bundle_sha256=sha(bundle_path),
        quality=dict(stats),
        sessions=summary,
        day_coverage=daily,
    )
    if symbol == "EURUSD":
        rows = []
        day = START
        weekday_index = 0
        while day < END:
            if day.weekday() < 5:
                weekday_index += 1
                begin = datetime(
                    day.year, day.month, day.day, 16, 5, tzinfo=zone("Europe/London")
                ).astimezone(UTC)
                end = begin.replace(
                    hour=17, minute=0
                )  # 18:00 London in this all-BST sample, asserted below.
                end = datetime(
                    day.year, day.month, day.day, 18, tzinfo=zone("Europe/London")
                ).astimezone(UTC)
                t0, t1 = int(begin.timestamp() * 1000), int(end.timestamp() * 1000)
                q0, q1 = snapshots.get(t0), snapshots.get(t1)
                row = dict(
                    date=day.date().isoformat(),
                    block=(weekday_index - 1) // 25 + 1,
                    included=fresh(q0) and fresh(q1),
                    entry_source_age_ms=q0[0] if q0 else None,
                    exit_source_age_ms=q1[0] if q1 else None,
                )
                if row["included"]:
                    row.update(
                        mid_change_pips=((q1[1] + q1[2]) - (q0[1] + q0[2])) / 20,
                        bid_ask_long_pips=(q1[1] - q0[2]) / 10,
                        spread_cost_pips=((q0[2] - q0[1]) + (q1[2] - q1[1])) / 20,
                    )
                    assert (
                        abs(
                            row["mid_change_pips"]
                            - row["spread_cost_pips"]
                            - row["bid_ask_long_pips"]
                        )
                        < 1e-10
                    )
                    # Point queries independently check each boundary and exact Decimal return.
                    points = []
                    for t in (t0, t1):
                        point = db.execute(
                            "SELECT at_ms,bid,ask FROM ticks WHERE at_ms>=? AND at_ms<=? "
                            "ORDER BY at_ms DESC,seq DESC LIMIT 1",
                            (START_MS, t),
                        ).fetchone()
                        assert point is not None and 0 <= t - point[0] <= 2000
                        points.append(point)
                    checked = (Decimal(points[1][1]) - Decimal(points[0][2])) / Decimal(".0001")
                    assert checked == Decimal(str(row["bid_ask_long_pips"]))
                rows.append(row)
            day += timedelta(days=1)
        included = [x for x in rows if x["included"]]
        groups = defaultdict(list)
        for x in included:
            date = datetime.fromisoformat(x["date"])
            groups[date.isocalendar()[:2]].append(x["bid_ask_long_pips"])
        groups = list(groups.values())
        rng = random.Random(20261118)
        boot = []
        for _ in range(5000):
            draw = [x for _ in groups for x in rng.choice(groups)]
            boot.append(mean(draw))
        result["eurusd_post_fix_diagnostic"] = dict(
            expected_days=len(rows),
            included_days=len(included),
            excluded_days=len(rows) - len(included),
            mid_change_pips=dist([x["mid_change_pips"] for x in included]),
            source_bid_ask_long_pips=dist([x["bid_ask_long_pips"] for x in included]),
            mean_interval_week_cluster_percentile95=[
                percentile(boot, 0.025),
                percentile(boot, 0.975),
            ],
            week_clusters=len(groups),
            positive_days=sum(x["bid_ask_long_pips"] > 0 for x in included),
            blocks=[
                dict(
                    block=i,
                    expected_days=sum(x["block"] == i for x in rows),
                    source_bid_ask_long_pips=dist(
                        [x["bid_ask_long_pips"] for x in included if x["block"] == i]
                    ),
                )
                for i in (1, 2, 3)
            ],
            daily=rows,
            independent_endpoint_checks=len(included) * 2,
        )
    db.close()
    assert sha(path) == before, "input changed while reading"
    result["source_unchanged_after"] = True
    print(json.dumps(dict(stage="complete", symbol=symbol, rows=stats["rows"])), flush=True)
    return result


result = dict(
    schema="market-anatomy/1",
    date="2026-11-18",
    plan=PLAN,
    plan_sha256=sha(OUT / "plan.json"),
    script_sha256=sha(Path(__file__)),
    execution_enabled=False,
    results=[],
)
for p in sorted(Path("/data/preview/history").glob("*/acquired-index.json")):
    result["results"].append(analyze(p.parent))
assert {r["symbol"] for r in result["results"]} == {"EURUSD", "USDJPY"}
result["limitations"] = [
    "Exploratory, already-exposed training; neither independent validation "
    "nor live market monitoring.",
    "Source timestamps do not measure receipt latency; quote freshness here does not qualify "
    "the live two-second gate.",
    "No verified calendar/news veto, broker fills, commission, slippage or financing; "
    "source-spread returns are optimistic proxies.",
    "Fixed minute snapshots and overlapping 15-minute changes are descriptive; "
    "ticks and minute counts are not independent trades.",
    "Nominal weekday/session conventions do not establish holiday availability "
    "or institutional fixing flow.",
    "Two-second endpoint selection can bias the observed day subset; "
    "exclusions and per-day counts are retained.",
    "No stops, targets, risk engine, equity curve or trading authority in this diagnostic.",
]
with (OUT / "result.json").open("x") as f:
    json.dump(result, f, indent=2)
    f.write("\n")
print("Saved market observations; no trading or replay actions", flush=True)
