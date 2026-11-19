"""Prepare/run the preregistered exposed EURUSD slice in a NEW offline directory.

No credentials, terminals, network data acquisition, or broker execution. The
source SQLite is opened read-only; original source/evidence is never rewritten.
"""

import argparse
import json
import secrets
import sqlite3
import time
from collections import Counter
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from fx_talanta.clock import SystemClock
from fx_talanta.dashboard.app import Dashboard
from fx_talanta.dashboard.demo import demo
from fx_talanta.dashboard.indexed_research import IndexedBundle
from fx_talanta.dashboard.research import indexed_engine_hash
from fx_talanta.dashboard.server import make_server
from fx_talanta.research.market_sessions import bounds
from fx_talanta.research.replay import Experiment, digest
from fx_talanta.research.spool import file_hash
from fx_talanta.research.structural import StructuralRules
from fx_talanta.research.tick_index import milliseconds

START = datetime(2026, 6, 1, tzinfo=UTC)
END = datetime(2026, 6, 13, tzinfo=UTC)
SOURCE_HASH = "16bfee856c1b2c52c913da3e925422569006c2c95878de2b2bcc5069b0cffd49"


def save(path, data):
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(data, stream, indent=2)
        stream.write("\n")


def prepare(source, output):
    source, output = Path(source), Path(output)
    original = IndexedBundle.model_validate_json((source / "acquired-index.json").read_bytes())
    index = source / original.index_file
    if original.index_sha256 != SOURCE_HASH or file_hash(index) != SOURCE_HASH:
        raise ValueError("preregistered historical source changed")
    if not original.experiment.start <= START < END <= original.experiment.training_end:
        raise ValueError("study must remain within already-exposed training")
    output.mkdir(parents=True, exist_ok=False)
    catalog = output / "datasets"
    catalog.mkdir()
    target = catalog / "ticks.sqlite"
    src = sqlite3.connect(index.resolve().as_uri() + "?mode=ro&immutable=1", uri=True)
    dst = sqlite3.connect(target)
    try:
        dst.execute("CREATE TABLE ticks(seq INTEGER PRIMARY KEY,at_ms INTEGER,bid TEXT,ask TEXT)")
        dst.execute("CREATE TABLE metadata(value TEXT NOT NULL)")
        cursor = src.execute(
            "SELECT seq,at_ms,bid,ask FROM ticks WHERE at_ms>=? AND at_ms<? ORDER BY at_ms,seq",
            (milliseconds(START) - original.latency_ms, milliseconds(END) - original.latency_ms),
        )
        while batch := cursor.fetchmany(5000):
            dst.executemany("INSERT INTO ticks VALUES(?,?,?,?)", batch)
        dst.execute("CREATE INDEX tick_time ON ticks(at_ms,seq)")
        # SQL returns only warmup/development bars. No holdout price rows are selected.
        bars = [
            json.loads(row[0])
            for row in src.execute(
                "SELECT b.value FROM metadata,json_each(metadata.value,'$.bars') b "
                "WHERE julianday(json_extract(b.value,'$.close_at'))<=julianday(?) "
                "AND julianday(json_extract(b.value,'$.close_at'))>=julianday(?)",
                (END.isoformat(), original.experiment.start.isoformat()),
            )
        ]
        metadata = json.loads(
            src.execute("SELECT json_remove(value,'$.bars') FROM metadata").fetchone()[0]
        )
        metadata.update(
            bars=bars,
            parent_index_sha256=SOURCE_HASH,
            development_window=[START.isoformat(), END.isoformat()],
        )
        dst.execute("INSERT INTO metadata VALUES(?)", (json.dumps(metadata),))
        dst.commit()
        count, unique_times = dst.execute(
            "SELECT count(*),count(DISTINCT at_ms) FROM ticks"
        ).fetchone()
        days = dict(
            dst.execute("SELECT date(at_ms/1000,'unixepoch'),count(*) FROM ticks GROUP BY 1")
        )
        max_gap = dst.execute(
            "SELECT max(gap)/1000.0 FROM (SELECT at_ms-lag(at_ms) "
            "OVER(ORDER BY at_ms,seq) gap FROM ticks)"
        ).fetchone()[0]
        seen = {datetime.fromisoformat(b["close_at"]) for b in bars if b["timeframe"] == "M15"}
        missing = []
        expected = 0
        for i in range(12):
            day = START + timedelta(days=i, hours=12)
            if day.weekday() >= 5:
                continue
            begin, end = bounds("LONDON", day)
            for slot in range(1, 37):
                at = begin + timedelta(minutes=15 * slot)
                expected += 1
                if at not in seen:
                    missing.append(at.isoformat())
        quality = dict(
            source_index_sha256=SOURCE_HASH,
            rows=count,
            bars=len(bars),
            duplicate_source_sequence_ids=0,
            timestamp_ties=count - unique_times,
            rows_by_utc_date=days,
            largest_gap_seconds_including_weekend=max_gap,
            expected_london_m15_closes=expected,
            missing_london_m15_closes=missing,
            source_time_convention="HistData fixed EST translated to UTC; no DST",
            receipt_latency="250ms modeled, not measured delivery",
            intended_use="Exposed development comparison only; unqualified",
        )
    finally:
        src.close()
        dst.close()
    if file_hash(index) != SOURCE_HASH:
        raise ValueError("source changed during read-only preparation")
    experiment = original.experiment.model_dump(mode="json")
    experiment.update(
        name="eurusd-structural-development-june01-12",
        start=START.isoformat(),
        training_end=END.isoformat(),
        validation_end=(END + timedelta(microseconds=1)).isoformat(),
        end=(END + timedelta(microseconds=2)).isoformat(),
    )
    for field in ("trade_fraction", "aggregate_fraction"):
        experiment["policy"][field] = str(
            min(Decimal(experiment["policy"][field]), Decimal("0.001"))
        )
    bundle = IndexedBundle(
        index_file="ticks.sqlite",
        index_sha256=file_hash(target),
        experiment=Experiment.model_validate(experiment),
        latency_ms=original.latency_ms,
        assume_research_inputs=original.assume_research_inputs,
        acquired_history=True,
        development_only=True,
        minimum_closed_trades=20,
    )
    save(catalog / "structural-index.json", bundle.model_dump(mode="json"))
    save(
        output / "quality.json",
        dict(quality, source_unchanged=True, prepared_index_sha256=bundle.index_sha256),
    )
    save(
        output / "manifest.json",
        dict(
            schema="structural-comparison/1",
            start=START.isoformat(),
            end=END.isoformat(),
            source_sha256=SOURCE_HASH,
            bundle_sha256=file_hash(catalog / "structural-index.json"),
            engine_sha256=indexed_engine_hash(),
            arms=[
                StructuralRules().model_dump(mode="json"),
                StructuralRules(arm="FIRST_TOUCH").model_dump(mode="json"),
            ],
            economic_acceptance=False,
            execution_enabled=False,
            risk_policy=bundle.experiment.policy.model_dump(mode="json"),
        ),
    )
    print(
        json.dumps(
            dict(
                stage="PREPARED",
                rows=count,
                bars=len(bars),
                missing_london_bars=len(missing),
                source_unchanged=True,
            )
        ),
        flush=True,
    )


def open_app(root):
    return Dashboard(
        demo(),
        root / "state",
        secrets.token_urlsafe(32),
        SystemClock(),
        dataset_directory=root / "datasets",
    )


def wait_result(app, result):
    while result.get("kind") == "BACKGROUND_RUN":
        status = app.research.run_status(result["id"])
        if status["status"] == "COMPLETED":
            result = (
                app.research.item(status["outcome"]["id"])
                if status["outcome"].get("kind") == "BACKTEST"
                else status["outcome"]
            )
            break
        if status["status"] != "RUNNING":
            raise ValueError("study interrupted; preserve evidence, no resend")
        time.sleep(1)
    if result.get("kind") != "BACKTEST":
        raise ValueError("study did not complete; preserve failure, no resend")
    return result


def run_study(root):
    manifest = json.loads((root / "manifest.json").read_text())
    if manifest["engine_sha256"] != indexed_engine_hash():
        raise ValueError("prepared engine changed")
    save(root / "started.json", dict(at=datetime.now(UTC).isoformat(), manifest=digest(manifest)))
    app = open_app(root)
    try:
        spec = dict(
            name="EUR/USD structural pullback · June development comparison",
            pairs=["EURUSD", "USDJPY"],
            hypothesis="A closed-bar retest confirmation may filter weak first touches; unproven.",
            input_policy="Exposed EURUSD history; spread observed, calendar/costs unqualified.",
            entry_rules="H1 swing/EMA50; M15 touch, bounce, retest and short reversal; London.",
            exit_rules="Fixed stop, 2R, 16 bars or session end; no trailing/partial exit.",
            portfolio_policy="One EURUSD position; USDJPY disabled; unchanged native risk limits.",
            evaluation_plan="June 1-12 development vs first touch; no holdout or promotion.",
            risk_per_trade_pct="0.10",
            total_open_risk_pct="0.10",
            daily_loss_limit_pct="1",
            authorship="USER",
            provenance="Owner-authorized preregistered implementation study; no model output.",
        )
        identity = uuid5(NAMESPACE_URL, digest(manifest))
        saved = app.strategies.save(
            dict(request_id=str(identity), strategy_id=str(identity), specification=spec)
        )
        app.strategies.freeze(dict(sha256=saved["sha256"]))
        key = app.research.catalog.metadata[0]["id"]
        reg = app.research.select_dataset(
            dict(
                dataset_id=key,
                candidate_sha256=saved["sha256"],
                rules=StructuralRules().model_dump(mode="json"),
                reviewed_mapping=True,
            )
        )
        print(json.dumps(dict(stage="CONFIRMATION_RUNNING")), flush=True)
        primary = wait_result(
            app, app.research.execute(dict(registration_id=reg["id"], partition="training"))
        )
        save(root / "confirmation.json", primary)
        print(json.dumps(dict(stage="FIRST_TOUCH_RUNNING")), flush=True)
        control = wait_result(app, app.research.structural_control(dict(result_id=primary["id"])))
        save(root / "first-touch.json", control)
        results = []
        for item in (primary, control):
            r = item["payload"]["result"]
            setups = r["structural_setups"]["opportunities"]
            results.append(
                dict(
                    arm=r["structural_setups"]["rules"]["arm"],
                    result_id=item["id"],
                    watched=len(setups),
                    states=dict(Counter(s["state"] for s in setups)),
                    transitions=dict(Counter(t["state"] for s in setups for t in s["transitions"])),
                    entries=dict(
                        Counter(s["entry"]["disposition"] for s in setups if s.get("entry"))
                    ),
                    metrics=r["metrics"],
                    net_realized_pnl=r["net_realized_pnl"],
                    commission=r["commission"],
                    integrity_halt=r["integrity_halt"],
                    risk_halt=r.get("risk_halt"),
                    fully_settled=r["fully_settled"],
                    coverage=r["coverage"],
                    audit_streams=r["audit_streams"],
                )
            )
        ids = [
            [s["setup_id"] for s in x["payload"]["result"]["structural_setups"]["opportunities"]]
            for x in (primary, control)
        ]
        report = dict(
            schema="structural-comparison-results/1",
            candidate=saved["sha256"],
            manifest_sha256=digest(manifest),
            matching_opportunity_ids=ids[0] == ids[1],
            results=results,
            source_quality=json.loads((root / "quality.json").read_text()),
            economic_verdict="INSUFFICIENT_EVIDENCE",
            qualified_for_paper=False,
            execution_enabled=False,
        )
        save(root / "comparison.json", report)
        print(
            json.dumps(
                dict(
                    stage="COMPLETE",
                    matching_opportunities=ids[0] == ids[1],
                    results=[
                        {
                            k: r[k]
                            for k in (
                                "arm",
                                "watched",
                                "entries",
                                "net_realized_pnl",
                                "integrity_halt",
                            )
                        }
                        for r in results
                    ],
                )
            ),
            flush=True,
        )
    finally:
        app.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["prepare", "run", "serve"])
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--port", type=int, default=8767)
    args = parser.parse_args()
    if args.mode == "prepare":
        prepare(args.source, args.directory)
    elif args.mode == "run":
        run_study(args.directory)
    else:
        app = open_app(args.directory)
        server = make_server(app, port=args.port, local_workspace=True)
        server.serve_forever()


if __name__ == "__main__":
    main()
