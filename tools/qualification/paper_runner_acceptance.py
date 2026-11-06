"""Bounded synthetic incremental runner exercise; no live sources or campaign."""

import argparse
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from uuid import UUID, uuid5

from fx_talanta.clock import FakeClock
from fx_talanta.evaluation.ledger import Ledger
from fx_talanta.evaluation.runner import Config, Runner, Tick, engine_hash
from tools.fixtures.b01_replay import scenario


def run(destination):
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=False)
    dataset, experiment = scenario()
    config = Config(
        run_id=UUID("c9817026-b583-4a8f-b0e0-1f94250ee938"),
        start=experiment.start,
        deadline=experiment.end,
        provenance="SYNTHETIC",
        symbol=experiment.symbol,
        instrument=dataset.events[0].market.instruments[0],
        history_complete=True,
        policy=experiment.policy,
        costs=experiment.costs,
    )
    clock = FakeClock(config.start)
    (destination / "config.json").write_text(config.model_dump_json(indent=2), encoding="utf-8")
    runner = Runner.create(destination / "runner.sqlite", config, clock)
    with closing(sqlite3.connect(runner.path)) as conn:
        registration_hash = conn.execute("SELECT sha FROM header").fetchone()[0]
    seen = set()
    for sequence, event in enumerate(dataset.events, 1):
        clock.advance(event.available_at - clock.now())
        bars = tuple(b for b in dataset.bars if b.available_at <= clock.now() and b not in seen)
        seen.update(bars)
        tick = Tick(
            event_id=uuid5(config.run_id, str(sequence)),
            sequence=sequence,
            market=event.market,
            bars=bars,
            news="NEUTRAL",
        )
        (destination / f"tick-{sequence}.json").write_text(tick.model_dump_json(), encoding="utf-8")
        # Reopen on every input; no in-memory state is relied upon for recovery.
        runner = Runner(runner.path, clock)
        receipt = runner.admit(tick, registration_hash)
        assert runner.admit(tick, registration_hash)["replayed"]
    runner.stop(registration_hash, "synthetic input exhausted; pending outcomes preserved")
    report = runner.report(registration_hash, (receipt["sequence"], receipt["sha"]))
    export = runner.export(registration_hash, destination / "receipts.sqlite")
    matched = Ledger(destination / "receipts.sqlite", clock).report(export["plan_hash"])
    passed = (
        report["observations"] == 6
        and all(
            a["entries"] == 1 and a["closed_simulated_positions"] == 1 and a["open_positions"] == 0
            for a in report["arms"].values()
        )
        and matched["decisions"] == 18
        and matched["pending_outcomes"] == 3
        and not report["execution_enabled"]
    )
    result = dict(
        schema="paper-runner-synthetic-acceptance/1",
        result="PASS" if passed else "FAIL",
        provenance="SYNTHETIC",
        engine_sha256=engine_hash(),
        runner=report,
        export=export,
        matched=matched,
        host_clock_adjusted=False,
        campaign_started=False,
        full_M5_complete=False,
    )
    (destination / "report.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    result = run(parser.parse_args().output)
    print(
        json.dumps(
            dict(
                result=result["result"],
                observations=result["runner"]["observations"],
                broker_calls=0,
                external_model_calls=0,
                execution_enabled=False,
            )
        )
    )
    if result["result"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
