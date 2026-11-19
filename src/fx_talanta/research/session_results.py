"""Descriptive entry-session attribution; never a profitability or promotion gate."""

from collections import defaultdict
from datetime import datetime
from decimal import Decimal, localcontext

import tzdata

from fx_talanta.research.market_sessions import DEFINITIONS, VERSION, context


def summarize(result):
    def bucket():
        return dict(
            closed_trades=0,
            wins=0,
            losses=0,
            net_pnl=Decimal(0),
            closed_trade_drawdown=Decimal(0),
            peak=Decimal(0),
            evaluations=0,
            candidates=0,
            evaluations_before_halt=0,
            candidates_before_halt=0,
            evaluations_after_halt=0,
            candidates_after_halt=0,
            holds={},
        )

    groups = defaultdict(bucket)
    trades = defaultdict(list)
    for deal in result["deals"]:
        trades[deal["position_id"]].append(deal)
    ordered = sorted(trades.values(), key=lambda ds: ds[-1]["at"])
    with localcontext() as ctx:
        ctx.prec = 34
        for deals in ordered:
            entries = [d for d in deals if d["action"] == "ENTER"]
            closes = [d for d in deals if d["action"] == "CLOSE"]
            if (
                not entries
                or not closes
                or sum(Decimal(d["volume"]) for d in entries)
                != sum(Decimal(d["volume"]) for d in closes)
            ):
                continue
            entry = min(entries, key=lambda d: d["at"])
            name = context(datetime.fromisoformat(entry["at"]))["regime"]
            g = groups[name]
            pnl = sum((Decimal(d["realized"]) for d in deals), Decimal(0))
            g["closed_trades"] += 1
            g["wins"] += int(pnl > 0)
            g["losses"] += int(pnl < 0)
            g["net_pnl"] += pnl
            g["peak"] = max(g["peak"], g["net_pnl"])
            g["closed_trade_drawdown"] = max(g["closed_trade_drawdown"], g["peak"] - g["net_pnl"])
        for d in result.get("decisions", []):
            if d["action"] not in {"HOLD", "CANDIDATE"}:
                continue
            at = datetime.fromisoformat(d.get("as_of") or d["at"])
            g = groups[context(at)["regime"]]
            g["evaluations"] += 1
            halt = result.get("risk_halt")
            phase = (
                "after_halt" if halt and at >= datetime.fromisoformat(halt["at"]) else "before_halt"
            )
            g["evaluations_" + phase] += 1
            if d["action"] == "CANDIDATE":
                g["candidates"] += 1
                g["candidates_" + phase] += 1
            else:
                reason = d.get("reason", "UNSPECIFIED")
                g["holds"][reason] = g["holds"].get(reason, 0) + 1
        attributed = sum((g["net_pnl"] for g in groups.values()), Decimal(0))
        remainder = Decimal(result["net_realized_pnl"]) - attributed
        rows = []
        for name, g in sorted(groups.items()):
            g.pop("peak")
            rows.append(
                dict(
                    regime=name,
                    **{k: str(v) if isinstance(v, Decimal) else v for k, v in g.items()},
                    sample_status="INSUFFICIENT_SESSION_SAMPLE"
                    if g["closed_trades"] < 20
                    else "DESCRIPTIVE_ONLY_NOT_VALIDATED",
                )
            )
    return dict(
        version=VERSION,
        tzdata=tzdata.__version__,
        symbol=result["experiment"]["symbol"],
        partition=result["partition"],
        conventions={
            k: dict(timezone=z, open_hour=a, close_hour=b) for k, (z, a, b) in DEFINITIONS.items()
        },
        buckets=rows,
        attributed_net_pnl=str(attributed),
        unattributed_realized_pnl=str(remainder),
        risk_halt=result.get("risk_halt"),
        attribution="Each closed position counted once, by entry session combination.",
        limitations=[
            "Session hours are research conventions, not exchange schedules or holiday calendars.",
            "Overlaps are separate, mutually exclusive buckets; no double counting.",
            "Closed-trade drawdown is not intratrade or marked-equity drawdown.",
            "Unattributed realized amounts may include open fees, "
            "separate financing or Decimal rounding.",
            "Twenty trades is a descriptive warning threshold, not statistical qualification.",
            "Post-halt evaluations are not executable opportunities; "
            "session effects cannot explain away a risk halt.",
            "No per-session spread/volatility or causal performance claim "
            "is inferred from aggregate results.",
        ],
        execution_enabled=False,
        qualified_for_paper=False,
    )
