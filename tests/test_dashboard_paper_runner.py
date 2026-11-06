"""Incremental simulation and dashboard receipt integration; never broker tests."""

import hashlib
import json
import socket
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from uuid import uuid4

import pytest

from fx_talanta.clock import FakeClock
from fx_talanta.dashboard.app import Dashboard
from fx_talanta.dashboard.demo import demo
from fx_talanta.dashboard.workflow import WorkflowView
from fx_talanta.domain.offline import Fault
from fx_talanta.evaluation.ledger import Ledger
from fx_talanta.evaluation.runner import Config, Engine, Runner, Tick
from tools.fixtures.b01_replay import scenario


def setup(tmp_path, **changes):
    dataset, experiment = scenario()
    config = Config(
        run_id=uuid4(),
        start=experiment.start,
        deadline=experiment.end,
        provenance="SYNTHETIC",
        symbol="EURUSD",
        instrument=dataset.events[0].market.instruments[0],
        history_complete=True,
        policy=experiment.policy,
        costs=experiment.costs,
        **changes,
    )
    clock = FakeClock(config.start)
    runner = Runner.create(tmp_path / "runner.sqlite", config, clock)
    with sqlite3.connect(runner.path) as conn:
        sha = conn.execute("SELECT sha FROM header").fetchone()[0]
    return runner, clock, sha, dataset, config


def ticks(dataset):
    sent = set()
    for sequence, event in enumerate(dataset.events, 1):
        bars = tuple(
            b for b in dataset.bars if b.available_at <= event.available_at and b not in sent
        )
        sent.update(bars)
        yield (
            event.available_at,
            Tick(
                event_id=uuid4(), sequence=sequence, market=event.market, bars=bars, news="NEUTRAL"
            ),
        )


def feed(runner, clock, sha, dataset, *, restart=False):
    receipts = []
    for at, tick in ticks(dataset):
        clock.advance(at - clock.now())
        if restart:
            runner = Runner(runner.path, clock)
        receipts.append(runner.admit(tick, sha))
    return receipts


def test_incremental_decision_risk_execution_outcome_and_dashboard(tmp_path, monkeypatch):
    def no_network(*args, **kwargs):
        pytest.fail("runner attempted network access")

    monkeypatch.setattr(socket, "socket", no_network)
    runner, clock, sha, dataset, config = setup(tmp_path)
    receipt = feed(runner, clock, sha, dataset, restart=True)[-1]
    report = runner.report(sha, (receipt["sequence"], receipt["sha"]))
    assert report["observations"] == 6
    assert all(
        a["entries"] == 1 and a["closed_simulated_positions"] == 1 and not a["open_positions"]
        for a in report["arms"].values()
    )
    assert not report["execution_enabled"] and report["B01"] == "REJECT_FOR_PROMOTION"
    assert report["broker_calls"] == report["external_model_calls"] == 0
    with sqlite3.connect(runner.path) as conn:
        results = [json.loads(r[0]) for r in conn.execute("SELECT result FROM ticks ORDER BY seq")]
    records = [
        r
        for result in results
        for arm in result["arms"].values()
        for item in arm["journal"]
        for r in item["payload"]["records"]
    ]
    kinds = {r["body"]["kind"] for r in records}
    assert {"decision", "risk", "execution", "experience"} <= kinds
    assert all(r["account"]["venue"] == "SIMULATOR" for r in records)
    approved = [r["body"] for r in records if r["body"]["kind"] == "risk" and r["body"]["approved"]]
    assert approved and all(r["evaluation_mode"] == "DETERMINISTIC" for r in approved)
    runner.stop(sha, "fixture exhausted; no manufactured final outcome")
    exported = runner.export(sha, tmp_path / "receipts.sqlite")
    ledger = Ledger(tmp_path / "receipts.sqlite", clock)
    result = ledger.report(exported["plan_hash"])
    assert result["status"] == "CLOSED" and result["decisions"] == 18
    assert result["pending_outcomes"] == 3  # final HOLDs need a subsequent observation
    assert not result["prospective_evidence_verified"]
    # The current dashboard is later than the historical simulation fixture.
    ui_clock = FakeClock(demo().captured_at + timedelta(days=1))
    app = Dashboard(
        demo(),
        tmp_path / "ui",
        "x" * 40,
        ui_clock,
        workflow_view=WorkflowView(dict(journal=str(ledger.path), plan_hash=exported["plan_hash"])),
    )
    try:
        view = app.overview()["matched_workflow"]
        assert view["observations"] == 6 and view["status"] == "CLOSED"
        assert not view["qualified_for_unattended_paper"]
    finally:
        app.close()


def test_news_ablation_and_selector_failure_are_explicit_holds(tmp_path):
    runner, clock, sha, dataset, _ = setup(tmp_path)
    for at, tick in ticks(dataset):
        clock.advance(at - clock.now())
        tick = tick.model_copy(update={"news": "ADVERSE"})
        runner.admit(tick, sha)
    report = runner.report(sha)
    assert report["arms"]["NO_AI"]["entries"] == 1
    assert report["arms"]["AI_NO_NEWS"]["entries"] == 1
    assert report["arms"]["AI_NEWS"]["entries"] == 0
    with sqlite3.connect(runner.path) as conn:
        for row in conn.execute("SELECT result FROM ticks"):
            for receipt in json.loads(row[0])["receipts"]:
                if receipt["kind"] == "DECIDE":
                    value = receipt["payload"]
                    detail = json.loads(value["decision_content"])
                    assert ("news" in detail["selector_input"]) == (value["arm"] == "AI_NEWS")


@pytest.mark.parametrize("failure", ["HOLD", "TIMEOUT", "MALFORMED"])
def test_scripted_model_failure_never_bypasses_baseline_or_risk(tmp_path, failure):
    runner, clock, sha, dataset, _ = setup(tmp_path)
    for at, tick in ticks(dataset):
        clock.advance(at - clock.now())
        runner.admit(tick.model_copy(update={"selector_result": failure}), sha)
    result = runner.report(sha)
    assert result["arms"]["NO_AI"]["entries"] == 1
    assert all(result["arms"][a]["entries"] == 0 for a in ("AI_NEWS", "AI_NO_NEWS"))


def test_stale_original_quotes_cannot_be_refreshed_by_receipt_time(tmp_path):
    runner, clock, sha, dataset, _ = setup(tmp_path)
    for at, tick in ticks(dataset):
        clock.advance(at + timedelta(seconds=3) - clock.now())
        runner.admit(tick, sha)
    result = runner.report(sha)
    assert all(
        a["closed_simulated_positions"] == 0 and a["open_positions"] == 0
        for a in result["arms"].values()
    )
    with sqlite3.connect(runner.path) as conn:
        assert "stale" in "".join(r[0] for r in conn.execute("SELECT result FROM ticks"))


@pytest.mark.parametrize("fault", ["REJECT", "LOST_RESPONSE", "NO_STOP"])
def test_simulator_fault_reconciliation_never_duplicates_entry(tmp_path, fault):
    runner, clock, sha, dataset, _ = setup(tmp_path)
    for at, tick in ticks(dataset):
        clock.advance(at - clock.now())
        if tick.sequence == 3:
            tick = tick.model_copy(update={"fault": Fault(kind=fault)})
        runner.admit(tick, sha)
        Runner(runner.path, clock).admit(tick, sha)
    result = runner.report(sha)
    assert all(a["entries"] == 1 and a["open_positions"] == 0 for a in result["arms"].values())


def test_transaction_crash_rolls_back_and_same_id_retry_is_once(tmp_path, monkeypatch):
    runner, clock, sha, dataset, _ = setup(tmp_path)
    at, tick = next(ticks(dataset))
    clock.advance(at - clock.now())
    original = Engine.step

    def crash(*args):
        original(*args)
        raise RuntimeError("simulated process failure before commit")

    monkeypatch.setattr(Engine, "step", crash)
    with pytest.raises(RuntimeError):
        runner.admit(tick, sha)
    monkeypatch.setattr(Engine, "step", original)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: Runner(runner.path, clock).admit(tick, sha), range(2)))
    assert sorted(r["replayed"] for r in results) == [False, True]
    assert runner.report(sha)["observations"] == 1
    with pytest.raises(ValueError, match="conflicting"):
        runner.admit(tick.model_copy(update={"news": "ADVERSE"}), sha)


def test_deadline_stop_capacity_clock_and_prefix_do_not_reset(tmp_path):
    runner, clock, sha, dataset, config = setup(tmp_path, max_observations=1)
    stream = list(ticks(dataset))
    at, tick = stream[0]
    clock.advance(at - clock.now())
    receipt = runner.admit(tick, sha)
    with pytest.raises(ValueError, match="capacity"):
        runner.admit(stream[1][1], sha)
    assert Runner(runner.path, clock).admit(tick, sha)["replayed"]
    with pytest.raises(ValueError, match="prefix"):
        runner.report(sha, (1, "0" * 64))
    clock.advance(config.deadline - clock.now() + timedelta(seconds=1))
    assert runner.report(sha)["status"] == "WINDOW_EXPIRED"
    runner.stop(sha, "done")
    runner.stop(sha, "done")
    with pytest.raises(ValueError):
        runner.stop(sha, "reset")
    assert runner.report(sha)["status"] == "STOPPED"
    terminal = runner.report(sha)
    assert terminal["receipt_hash"] != receipt["sha"] and terminal["receipt_sequence"] == 2
    assert runner.report(sha, (1, receipt["sha"]))["status"] == "STOPPED"
    with pytest.raises(ValueError, match="clock"):
        Runner(runner.path, FakeClock(config.start)).report(sha)


def test_future_out_of_order_corrupt_and_changed_engine_fail_closed(tmp_path, monkeypatch):
    runner, clock, sha, dataset, _ = setup(tmp_path)
    at, tick = next(ticks(dataset))
    with pytest.raises(ValueError, match="future"):
        runner.admit(tick, sha)
    clock.advance(at - clock.now())
    with pytest.raises(ValueError, match="sequence"):
        runner.admit(tick.model_copy(update={"sequence": 2}), sha)
    runner.admit(tick, sha)
    before = hashlib.sha256(runner.path.read_bytes()).hexdigest()
    monkeypatch.setattr("fx_talanta.evaluation.runner.engine_hash", lambda: "f" * 64)
    with pytest.raises(ValueError, match="engine"):
        runner.report(sha)
    assert hashlib.sha256(runner.path.read_bytes()).hexdigest() == before
    monkeypatch.undo()
    with sqlite3.connect(runner.path) as conn:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("UPDATE ticks SET result='{}'")
        conn.execute("DROP TRIGGER immutable_tick")
        conn.execute("UPDATE ticks SET result='{}'")
    with pytest.raises(ValueError, match="hash"):
        runner.report(sha)


def test_truncated_inputs_do_not_invent_closure_and_export_refuses_overwrite(tmp_path):
    runner, clock, sha, dataset, _ = setup(tmp_path)
    for at, tick in list(ticks(dataset))[:3]:
        clock.advance(at - clock.now())
        runner.admit(tick, sha)
    assert all(a["open_positions"] == 1 for a in runner.report(sha)["arms"].values())
    runner.stop(sha, "input ended")
    assert all(a["open_positions"] == 1 for a in runner.report(sha)["arms"].values())
    output = tmp_path / "export.sqlite"
    runner.export(sha, output)
    original = output.read_bytes()
    with pytest.raises(FileExistsError):
        runner.export(sha, output)
    assert output.read_bytes() == original


def test_profile_never_allows_real_venue_or_external_selector(tmp_path):
    _, _, _, _, config = setup(tmp_path)
    for change in (
        {"venue": "BROKER_DEMO"},
        {"execution_enabled": True},
        {"selector": "OPENAI"},
        {"policy": {**config.policy.model_dump(), "quote_age_seconds": 3}},
    ):
        with pytest.raises(ValueError):
            Config.model_validate({**config.model_dump(), **change})


@pytest.mark.parametrize("flag", ["calendar_ok", "news_ok", "session_open"])
def test_missing_shared_safety_inputs_block_all_arms(tmp_path, flag):
    runner, clock, sha, dataset, _ = setup(tmp_path)
    for at, tick in ticks(dataset):
        clock.advance(at - clock.now())
        tick = tick.model_copy(update={"market": tick.market.model_copy(update={flag: False})})
        runner.admit(tick, sha)
    assert all(
        a["closed_simulated_positions"] == 0 and a["open_positions"] == 0
        for a in runner.report(sha)["arms"].values()
    )


def test_processing_delay_rejects_uncommitted_entry_without_resetting_history(
    tmp_path, monkeypatch
):
    runner, clock, sha, dataset, _ = setup(tmp_path)
    stream = list(ticks(dataset))
    for at, tick in stream[:2]:
        clock.advance(at - clock.now())
        runner.admit(tick, sha)
    original = Engine.step

    def delayed(engine, tick, at):
        result = original(engine, tick, at)
        if tick.sequence == 3:
            clock.advance(timedelta(seconds=3))
        return result

    monkeypatch.setattr(Engine, "step", delayed)
    at, tick = stream[2]
    clock.advance(at - clock.now())
    with pytest.raises(ValueError, match="expired during"):
        runner.admit(tick, sha)
    monkeypatch.setattr(Engine, "step", original)
    assert runner.report(sha)["observations"] == 2
    runner.admit(tick, sha)  # same ID, now stale: admitted as rejected risk, not refreshed.
    assert all(a["open_positions"] == 0 for a in runner.report(sha)["arms"].values())


def test_instrument_drift_deadline_and_future_bars_leave_no_receipt(tmp_path):
    runner, clock, sha, dataset, config = setup(tmp_path)
    at, tick = next(ticks(dataset))
    clock.advance(at - clock.now())
    changed = config.instrument.model_copy(
        update={"maximum_spread": config.instrument.maximum_spread * 100}
    )
    with pytest.raises(ValueError, match="specifications"):
        runner.admit(
            tick.model_copy(
                update={"market": tick.market.model_copy(update={"instruments": (changed,)})}
            ),
            sha,
        )
    future = next(b for b in dataset.bars if b.available_at > clock.now())
    with pytest.raises(ValueError, match="future"):
        runner.admit(tick.model_copy(update={"bars": (future,)}), sha)
    assert runner.report(sha)["observations"] == 0
    clock.advance(config.deadline - clock.now() + timedelta(seconds=1))
    with pytest.raises(ValueError, match="deadline"):
        runner.admit(tick, sha)


def test_qualification_entrypoint_produces_only_synthetic_evidence(tmp_path):
    from tools.qualification.paper_runner_acceptance import run

    result = run(tmp_path / "acceptance")
    assert result["result"] == "PASS" and not result["campaign_started"]
    assert result["runner"]["selector"] == "SCRIPTED_TEST_DOUBLE"
    assert result["matched"]["comparison"]["result"] == "DESCRIPTIVE_OFFLINE_ONLY"


def test_terminal_checkpoint_detects_restoring_pre_stop_copy(tmp_path):
    runner, clock, sha, dataset, _ = setup(tmp_path)
    at, tick = next(ticks(dataset))
    clock.advance(at - clock.now())
    runner.admit(tick, sha)
    original = runner.path.read_bytes()
    runner.stop(sha, "complete")
    final = runner.report(sha)
    runner.path.write_bytes(original)
    with pytest.raises(ValueError, match="prefix"):
        runner.report(sha, (final["receipt_sequence"], final["receipt_hash"]))
    with pytest.raises(ValueError, match="prefix"):
        runner.report(sha, (-1, final["receipt_hash"]))
