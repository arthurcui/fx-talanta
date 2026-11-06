"""Synthetic source-to-runner operating evidence; never starts an external collector."""

import argparse
import json
import sqlite3
from contextlib import closing
from datetime import timedelta
from pathlib import Path
from uuid import UUID, uuid5

from fx_talanta.clock import FakeClock
from fx_talanta.evaluation.inputs import Envelope, SafetyEvidence
from fx_talanta.evaluation.operations import Binding, Operations
from fx_talanta.evaluation.runner import Config, Runner, Tick, engine_hash
from tools.fixtures.b01_replay import scenario


def run(destination, normalized=False):
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=False)
    dataset, experiment = scenario()
    config = Config(
        run_id=UUID("7271101e-8d10-4385-8197-620a101223df"),
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
    runner = Runner.create(destination / "runner.sqlite", config, clock)
    with closing(sqlite3.connect(runner.path)) as conn:
        registration = conn.execute("SELECT sha FROM header").fetchone()[0]
    operations, binding = Operations.create(
        destination / "source.sqlite",
        Binding(
            source_id=uuid5(config.run_id, "source"),
            runner=str(runner.path.resolve()),
            registration_hash=registration,
        ),
        clock,
    )
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
        source = None
        if normalized:
            safety = SafetyEvidence(
                state="CLEAR",
                currencies=("EUR", "USD"),
                available_at=clock.now(),
                expires_at=clock.now() + timedelta(minutes=1),
                reference_hash="a" * 64,
            )
            source = Envelope(
                source_id=uuid5(config.run_id, "source"),
                event_id=tick.event_id,
                sequence=sequence,
                provenance="SYNTHETIC",
                channel="FIXTURE",
                received_at=clock.now(),
                market=tick.market,
                bars=tick.bars,
                calendar=safety,
                news=safety,
                news_content="NEUTRAL",
            )
            operations.enqueue_envelope(source, binding)
        else:
            operations.enqueue(tick, binding)
        operations = Operations(operations.path, clock)
        operations.drain_one(binding)
        assert (
            operations.enqueue_envelope(source, binding)
            if source
            else operations.enqueue(tick, binding)
        )["replayed"]
    operations.stop(binding, "synthetic operating acceptance complete")
    report = operations.report(binding)
    passed = (
        report["queued"] == report["acknowledged"] == 6
        and report["pending"] == 0
        and report["runner"]["normalized_inputs"] == (6 if normalized else 0)
        and all(
            a["closed_simulated_positions"] == 1 and a["open_positions"] == 0
            for a in report["runner"]["arms"].values()
        )
    )
    result = dict(
        schema="runner-operations-synthetic/1",
        result="PASS" if passed else "FAIL",
        engine_sha256=engine_hash(),
        report=report,
        broker_calls=0,
        external_model_calls=0,
        campaign_started=False,
        full_M5_complete=False,
    )
    (destination / "report.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    (destination / "view.json").write_text(
        json.dumps(
            dict(source_kind="RUNNER", journal=str(runner.path.resolve()), plan_hash=registration)
        ),
        encoding="utf-8",
    )
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--normalized-inputs", action="store_true")
    args = parser.parse_args()
    result = run(args.output, args.normalized_inputs)
    print(
        json.dumps(dict(result=result["result"], execution_enabled=False, campaign_started=False))
    )
    if result["result"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
