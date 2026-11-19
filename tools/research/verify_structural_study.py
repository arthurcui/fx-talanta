"""Independently verify retained study evidence; never replay or modify a run."""

import argparse
import json
import sqlite3
from collections import Counter
from datetime import datetime
from decimal import Decimal, localcontext
from hashlib import sha256
from pathlib import Path

from fx_talanta.research.replay import digest
from fx_talanta.research.spool import file_hash, rows
from fx_talanta.research.tick_index import milliseconds

D = Decimal


def require(condition, message):
    if not condition:
        raise ValueError(message)


def equal_decimal(actual, expected):
    require(abs(D(actual) - D(expected)) < D("1e-24"), "numeric reconciliation failed")


def verified_rows(path, receipt):
    require(file_hash(path) == receipt["sha256"], "audit file hash changed")
    count, size, raw = 0, 0, sha256()
    for row in rows(path):
        encoded = (json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n").encode()
        count += 1
        size += len(encoded)
        raw.update(encoded)
        yield row
    require(
        (count, size, raw.hexdigest())
        == (receipt["rows"], receipt["raw_bytes"], receipt["raw_sha256"]),
        "audit receipt changed",
    )


def check_arm(root, item, manifest, db):
    p, r = item["payload"], item["payload"]["result"]
    require(p["engine_sha256"] == manifest["engine_sha256"], "run engine mismatch")
    require(r["experiment"]["policy"] == manifest["risk_policy"], "run policy mismatch")
    require(not r["execution_enabled"] and not p["qualified_for_paper"], "authority mismatch")
    require(r["fully_settled"] and not r["pending_signal"], "unsettled run")
    require(not r["integrity_halt"] and not r["risk_halt"], "unexpected halt")
    receipt = r["audit_streams"]["journal"]
    matches = [
        x.parent
        for x in (root / "state/research-runs").glob("*/journal.manifest.json")
        if file_hash(x) == receipt["sha256"]
    ]
    require(len(matches) == 1, "ambiguous audit stream")
    directory = matches[0]
    previous, books, events = "0" * 64, {}, Counter()
    for row in verified_rows(directory / receipt["file"], receipt):
        body = row["payload"]
        require(body["previous"] == previous and digest(body) == row["hash"], "broken chain")
        previous = row["hash"]
        events[body["event"]] += 1
        stream = body["stream"]
        if "book" in body:
            books[stream] = body["book"]
        elif "book_delta" in body:
            require(stream in books, "delta without initial book")
            books[stream].update(body["book_delta"])
            for key in body["book_removed"]:
                del books[stream][key]
        if stream == "gateway":
            require(books[stream]["policy"] == manifest["risk_policy"], "policy changed in run")
            require(not books[stream]["integrity_halt"], "hidden halt in journal")
    require(previous == r["journal_tip"], "wrong journal tip")
    require(books["broker"]["deals"] == r["deals"], "journal deals differ from report")
    equal_decimal(books["broker"]["balance"], r["balance"])
    peak, drawdown, count = D(manifest["risk_policy"]["capital"]), D(0), 0
    receipt = r["audit_streams"]["equity"]
    for row in verified_rows(directory / receipt["file"], receipt):
        value = D(row["equity"])
        peak = max(peak, value)
        drawdown = max(drawdown, (peak - value) / peak)
        count += 1
    require(count == r["coverage"]["ticks"], "equity observation missing")
    equal_decimal(drawdown, r["metrics"]["maximum_observed_drawdown_fraction"])
    opportunities = r["structural_setups"]["opportunities"]
    trades, total, commission, financing = [], D(0), D(0), D(0)
    capital = D(manifest["risk_policy"]["capital"])
    for setup in opportunities:
        known = datetime.fromisoformat(setup["known_at"])
        require(datetime.fromisoformat(setup["pivot_confirmed_at"]) <= known, "future pivot")
        require(
            all(datetime.fromisoformat(b["available_at"]) <= known for b in setup["h1"]),
            "future H1 context",
        )
        times = [datetime.fromisoformat(t["at"]) for t in setup["transitions"]]
        require(times == sorted(times) and times[0] == known, "noncausal transitions")
        entry = setup.get("entry")
        if not entry or not entry.get("deals"):
            continue
        deals = entry["deals"]
        require([d["action"] for d in deals] == ["ENTER", "CLOSE"], "unexpected deal lifecycle")
        opened, closed = deals
        volume = D(opened["volume"])
        require(volume == D(closed["volume"]) and D(entry["open_volume"]) == 0, "volume mismatch")
        side = 1 if setup["side"] == "BUY" else -1
        for deal in deals:
            at = datetime.fromisoformat(deal["at"])
            source = db.execute(
                "SELECT bid,ask FROM ticks WHERE at_ms=?", (milliseconds(at) - 250,)
            ).fetchall()
            require(len(source) == 1, "fill lacks an exact original quote")
            buying = (deal["action"] == "ENTER") == (side == 1)
            price = D(source[0][1 if buying else 0]) + (D("0.00002") if buying else -D("0.00002"))
            equal_decimal(deal["price"], price)
            equal_decimal(deal["commission"], volume * 4)
            commission += volume * 4
        elapsed = D(
            str(
                (
                    datetime.fromisoformat(closed["at"]) - datetime.fromisoformat(opened["at"])
                ).total_seconds()
            )
        )
        charge = volume * 3 * elapsed / 86400
        financing += charge
        pnl = (
            side * (D(closed["price"]) - D(opened["price"])) * 100000 * volume - 8 * volume - charge
        )
        equal_decimal(pnl, entry["net_realized"])
        equal_decimal(pnl, sum(D(d["realized"]) for d in deals))
        require(D(entry["quote_age_seconds"]) <= 2, "quote ceiling exceeded")
        require(
            datetime.fromisoformat(opened["at"]) > datetime.fromisoformat(entry["at"]),
            "same-bar fill",
        )
        initial = volume * D(entry["reservation"]["risk_per_lot"])
        require(initial <= (capital + total) * D("0.001"), "initial risk cap exceeded")
        bound = entry["reservation"]["lifecycle_bound"]
        equal_decimal(bound["equity_floor"], capital + total - initial)
        equal_decimal(bound["peak_planned_giveback"], volume * D(bound["peak_per_lot"]))
        require(D(bound["admission_fraction"]) == D("0.0009"), "admission cap changed")
        require(
            D(bound["peak_planned_giveback"]) <= D(bound["equity_floor"]) * D("0.0009"),
            "lifecycle risk exceeded",
        )
        trades.append(
            dict(
                setup_id=setup["setup_id"],
                side=setup["side"],
                entered_at=opened["at"],
                exited_at=closed["at"],
                volume=str(volume),
                net_pnl_usd=str(pnl),
                initial_planned_risk_usd=str(initial),
                exit=entry["exit_context"][0]["observed_conditions"],
            )
        )
        total += pnl
    equal_decimal(total, r["net_realized_pnl"])
    equal_decimal(commission, r["commission"])
    equal_decimal(financing, sum(D(x["charge"]) for x in r["financing"]))
    require(len(trades) == r["metrics"]["closed_trades"], "trade count mismatch")
    return dict(
        arm=r["structural_setups"]["rules"]["arm"],
        result_id=item["id"],
        result_file_sha256=file_hash(
            root
            / (
                "confirmation.json"
                if r["structural_setups"]["rules"]["arm"] == "RETEST_CONFIRMATION"
                else "first-touch.json"
            )
        ),
        audit_streams=r["audit_streams"],
        journal_tip=previous,
        fills_reconciled=len(r["deals"]),
        net_pnl_usd=str(total),
        commission_usd=str(commission),
        financing_usd=str(financing),
        maximum_drawdown_fraction=str(drawdown),
        opportunity_states=dict(Counter(s["state"] for s in opportunities)),
        transitions=dict(Counter(t["state"] for s in opportunities for t in s["transitions"])),
        decision_reasons=dict(Counter(x.get("reason", x["action"]) for x in r["decisions"])),
        setup_dates=sorted({s["known_at"][:10] for s in opportunities}),
        skipped_stop_crossing_paths=sum(
            x.get("reason") == "STOP_ALREADY_CROSSED" for x in r["decisions"]
        ),
        trades=trades,
    )


def verify(root):
    manifest = json.loads((root / "manifest.json").read_text())
    summary = json.loads((root / "comparison.json").read_text())
    bundle = json.loads((root / "datasets/structural-index.json").read_text())
    require(digest(manifest) == summary["manifest_sha256"], "manifest changed")
    require(
        file_hash(root / "datasets/structural-index.json") == manifest["bundle_sha256"],
        "bundle changed",
    )
    require(
        file_hash(root / "datasets/ticks.sqlite") == bundle["index_sha256"],
        "historical index changed",
    )
    items = [
        json.loads((root / name).read_text()) for name in ("confirmation.json", "first-touch.json")
    ]
    require(
        items[0]["payload"]["structural_comparison_key"]
        == items[1]["payload"]["structural_comparison_key"],
        "unmatched control",
    )
    setups = [
        [
            {k: v for k, v in s.items() if k != "entry"}
            for s in item["payload"]["result"]["structural_setups"]["opportunities"]
        ]
        for item in items
    ]
    require(setups[0] == setups[1], "opportunity geometry or transitions differ")
    db = sqlite3.connect(
        (root / "datasets/ticks.sqlite").resolve().as_uri() + "?mode=ro&immutable=1", uri=True
    )
    try:
        with localcontext() as context:
            context.prec = 34
            results = [check_arm(root, item, manifest, db) for item in items]
    finally:
        db.close()
    return dict(
        schema="structural-independent-verification/1",
        verified=True,
        manifest_sha256=digest(manifest),
        engine_sha256=manifest["engine_sha256"],
        comparison_key=items[0]["payload"]["structural_comparison_key"],
        source_index_sha256=manifest["source_sha256"],
        prepared_index_sha256=bundle["index_sha256"],
        same_opportunity_geometry_and_transitions=True,
        economic_acceptance=False,
        execution_enabled=False,
        results=results,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    report = verify(args.directory)
    with args.output.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(report, stream, indent=2)
        stream.write("\n")
    print(json.dumps({"verified": report["verified"], "arms": len(report["results"])}))
