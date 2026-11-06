"""Synthetic recorded-response integration; never contacts a model or broker."""

import argparse
import json
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid5

from fx_talanta.clock import FakeClock
from fx_talanta.evaluation.inputs import Envelope, SafetyEvidence, normalize
from fx_talanta.evaluation.operations import Binding, Operations
from fx_talanta.evaluation.runner import Config, Runner, Tick, engine_hash
from fx_talanta.evaluation.selectors import Batch, Profile
from tools.fixtures.b01_replay import scenario


def fixture_batch(prepared, milliseconds=250):
    at = datetime.fromisoformat(prepared["requested_at"])
    replies = {}
    for arm, request in prepared["requests"].items():
        can_select = bool(request["payload"]["allowed_exits"])
        selection = dict(
            action="SELECT" if can_select else "HOLD",
            candidate_id=request["payload"]["candidate_id"] if can_select else None,
            exit_option="TIME_EXIT" if can_select else None,
            reason="CANDIDATE_SELECTED" if can_select else "INSUFFICIENT_EVIDENCE",
        )
        replies[arm] = dict(
            request_hash=request["request_hash"],
            returned_model="fixture-model/1",
            completed_at=at + timedelta(milliseconds=milliseconds),
            status="RESPONSE",
            response=json.dumps(selection),
            input_tokens=100,
            output_tokens=20,
            reported_cost_usd="0.0001",
        )
    return Batch(requested_at=at, replies=replies)


def run(destination):
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=False)
    dataset, experiment = scenario()
    config = Config(
        run_id=UUID("71287e63-247c-4606-9ae6-2bcdb3f5a974"),
        start=experiment.start,
        deadline=experiment.end,
        provenance="SYNTHETIC",
        selector="RECORDED_MODEL_RESPONSES",
        selector_profile=Profile(model="fixture-model/1", prompt_hash="b" * 64),
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
    source_id = uuid5(config.run_id, "source")
    ops, binding = Operations.create(
        destination / "source.sqlite",
        Binding(
            source_id=source_id,
            runner=str(runner.path.resolve()),
            registration_hash=registration,
        ),
        clock,
    )
    sent = set()
    for sequence, event in enumerate(dataset.events, 1):
        clock.advance(event.available_at - clock.now())
        bars = tuple(b for b in dataset.bars if b.available_at <= clock.now() and b not in sent)
        sent.update(bars)
        evidence = SafetyEvidence(
            state="CLEAR",
            currencies=("EUR", "USD"),
            available_at=clock.now(),
            expires_at=clock.now() + timedelta(minutes=1),
            reference_hash="a" * 64,
        )
        tick = normalize(
            Envelope(
                source_id=source_id,
                event_id=uuid5(config.run_id, str(sequence)),
                sequence=sequence,
                provenance="SYNTHETIC",
                channel="FIXTURE",
                received_at=clock.now(),
                market=event.market,
                bars=bars,
                calendar=evidence,
                news=evidence,
                news_content="NEUTRAL",
            ),
            clock.now(),
        )
        original = runner.path.read_bytes()
        prepared = runner.prepare_selector(tick, registration)
        assert original == runner.path.read_bytes()
        assert "news" not in prepared["requests"]["AI_NO_NEWS"]["payload"]
        batch = fixture_batch(prepared)
        clock.advance(timedelta(milliseconds=250))
        tick = Tick.model_validate(tick.model_dump() | {"model_batch": batch.model_dump()})
        ops.enqueue(tick, binding)
        ops = Operations(ops.path, clock)
        ops.drain_one(binding)
        assert ops.enqueue(tick, binding)["replayed"]
    ops.stop(binding, "recorded selector synthetic acceptance complete")
    report = ops.report(binding)
    passed = (
        report["acknowledged"] == 6
        and all(a["closed_simulated_positions"] == 1 for a in report["runner"]["arms"].values())
        and all(
            s["recorded_replies"] == 6 and s["known_reported_cost_usd"] == "0.0006"
            for s in report["runner"]["recorded_model_summary"].values()
        )
    )
    result = dict(
        schema="recorded-selector-synthetic/1",
        result="PASS" if passed else "FAIL",
        engine_sha256=engine_hash(),
        report=report,
        broker_calls=0,
        external_model_calls=0,
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
        json.dumps(dict(result=result["result"], external_model_calls=0, execution_enabled=False))
    )
    if result["result"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
