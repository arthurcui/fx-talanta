"""Offline, read-only source audit and cost evidence; never connects to a terminal."""

import argparse
import json
import sqlite3
from collections import Counter
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from fx_talanta.research.session_study import background_priority
from fx_talanta.research.spool import file_hash


def weekend_seconds(start, end):
    """Fixed-EST January proxy only; split gaps rather than excuse whole weekends."""
    if start > end:
        raise ValueError("reversed interval")
    total = 0.0
    day = start.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=7)
    while day < end:
        if day.weekday() == 4:
            close = day + timedelta(hours=22)  # January NY 17:00 == UTC 22:00
            reopen = close + timedelta(days=2)
            total += max(0, (min(end, reopen) - max(start, close)).total_seconds())
        day += timedelta(days=1)
    return total


def distribution(hist):
    count = sum(hist.values())
    if not count:
        raise ValueError("empty spread population")
    ordered = sorted(hist.items())
    result = {"ticks": count, "minimum": str(ordered[0][0]), "maximum": str(ordered[-1][0])}
    for name, percent in (("p50", 50), ("p95", 95), ("p99", 99)):
        rank, cumulative = (count * percent + 99) // 100, 0
        for spread, n in ordered:
            cumulative += n
            if cumulative >= rank:
                result[name] = str(spread)
                break
    return result


def audit(path, symbol):
    if symbol not in ("EURUSD", "USDJPY"):
        raise ValueError("unsupported audit symbol")
    before = file_hash(path)
    pip = Decimal("0.01" if symbol == "USDJPY" else "0.0001")
    first_bound = datetime(2025, 1, 1, 5, tzinfo=UTC)
    end_bound = datetime(2025, 2, 1, 5, tzinfo=UTC)
    hist, daily, gaps = Counter(), {}, []
    previous = first = last = None
    ties = duplicates = count = 0
    with sqlite3.connect(path.resolve().as_uri() + "?mode=ro&immutable=1", uri=True) as db:
        db.execute("PRAGMA cache_size=-8192")
        metadata = json.loads(db.execute("SELECT value FROM metadata").fetchone()[0])
        if metadata.get("status") != "COMPLETE" or metadata.get("symbol") != symbol:
            raise ValueError("incomplete or mismatched index metadata")
        for seq, at_ms, bid, ask in db.execute("SELECT seq,at_ms,bid,ask FROM ticks ORDER BY seq"):
            count += 1
            at = datetime(1970, 1, 1, tzinfo=UTC) + timedelta(milliseconds=at_ms)
            bid, ask = Decimal(bid), Decimal(ask)
            if (
                seq != count - 1
                or not bid.is_finite()
                or not ask.is_finite()
                or bid <= 0
                or ask < bid
                or not first_bound <= at < end_bound
            ):
                raise ValueError("invalid source row or month boundary")
            if previous:
                if at < last:
                    raise ValueError("time regression")
                ties += at == last
                duplicates += (at_ms, bid, ask) == previous
                seconds = (at - last).total_seconds()
                if seconds > 60:
                    closed = weekend_seconds(last, at)
                    gaps.append(
                        {
                            "start": last.isoformat(),
                            "end": at.isoformat(),
                            "seconds": seconds,
                            "weekend_proxy_seconds": closed,
                            "unexplained_seconds": seconds - closed,
                        }
                    )
            first = first or at
            last, previous = at, (at_ms, bid, ask)
            spread = (ask - bid) / pip
            hist[spread] += 1
            daily.setdefault(at.date().isoformat(), Counter())[spread] += 1
    if not count or count != metadata["rows"] or before != file_hash(path):
        raise ValueError("empty, mismatched or changed source")
    return {
        "symbol": symbol,
        "index_sha256": before,
        "archive_sha256": metadata["archive_sha256"],
        "rows": count,
        "timestamp_ties": ties,
        "adjacent_duplicate_rows": duplicates,
        "first_utc": first.isoformat(),
        "last_utc": last.isoformat(),
        "unobserved_month_boundary_seconds": {
            "leading": (first - first_bound).total_seconds(),
            "trailing": (end_bound - last).total_seconds(),
        },
        "spread_pips_tick_weighted": distribution(hist),
        "daily_spread_pips_tick_weighted": {d: distribution(h) for d, h in daily.items()},
        "gaps_over_60_seconds": gaps,
        "gap_count": len(gaps),
        "unexplained_gap_seconds": round(sum(g["unexplained_seconds"] for g in gaps), 3),
        "unchanged_after_read": True,
    }


def retained_fees(path):
    """Aggregate one retained snapshot only, never merge overlapping deal histories."""
    before = file_hash(path)
    data = json.loads(path.read_text())
    if data["account"]["trade_mode"] != 0:
        raise ValueError("expected saved demo evidence")
    trades = [d for d in data["deals"] if d["type"] in (0, 1)]
    if len({d["ticket"] for d in trades}) != len(trades):
        raise ValueError("duplicate trade deal")
    if not trades or any(d["symbol"] != "EURUSD." for d in trades):
        raise ValueError("unexpected retained population")
    if before != file_hash(path):
        raise ValueError("changed retained evidence")
    return {
        "source_sha256": before,
        "mode": "DEMO",
        "currency": data["account"]["currency"],
        "symbol": "EURUSD",
        "deal_count": len(trades),
        "entry_deals": sum(d["entry"] == 0 for d in trades),
        "exit_deals": sum(d["entry"] == 1 for d in trades),
        "deal_lot_sizes": sorted({str(d["volume"]) for d in trades}),
        "charges": {
            k: str(sum((Decimal(str(d[k])) for d in trades), Decimal(0)))
            for k in ("commission", "swap", "fee")
        },
        "account_plan": "UNKNOWN",
        "slippage_calibration": "INSUFFICIENT_EVIDENCE",
        "historical_2025_applicability": "UNPROVEN",
        "unchanged_after_read": True,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--eurusd", type=Path, required=True)
    parser.add_argument("--usdjpy", type=Path, required=True)
    parser.add_argument("--retained-broker", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    background_priority()
    expected = (
        "2ca8a00c88d05a4bda8da080378544811df783fcbc3df7d555141791481864a9",
        "eb6b5c2129112b4177709a95f9371e56165e5650e6063768b66c20bf2a5d7029",
    )
    if tuple(file_hash(p) for p in (args.eurusd, args.usdjpy)) != expected:
        raise ValueError("source differs from predeclared January audit population")
    result = {
        "schema": "m3-input-cost-audit/1",
        "created_at": datetime.now(UTC).isoformat(),
        "auditor_sha256": file_hash(Path(__file__)),
        "scope": "January 2025 fixed-EST source audit; no strategy evaluation",
        "calendar": "Unqualified proxy: Friday 22 UTC to Sunday 22 UTC; January only",
        "gap_threshold_seconds": 60,
        "entry_ceiling_seconds_unchanged": 2,
        "arrival_times": "UNKNOWN",
        "source_revisions": "UNKNOWN",
        "historical_holiday_calendar": "UNKNOWN",
        "broker_costs_qualified": False,
        "sources": [audit(args.eurusd, "EURUSD"), audit(args.usdjpy, "USDJPY")],
        "retained_demo_fees": retained_fees(args.retained_broker),
    }
    with args.output.open("x") as f:
        json.dump(result, f, indent=2)
        f.write("\n")


if __name__ == "__main__":
    main()
