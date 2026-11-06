"""Local simulation operating lifecycle; no broker, model or source connection."""

import json
import socket
import sqlite3
from datetime import timedelta
from uuid import uuid4

import pytest
from test_dashboard_paper_runner import setup, ticks

from fx_talanta.clock import FakeClock
from fx_talanta.dashboard.app import Dashboard
from fx_talanta.dashboard.demo import demo
from fx_talanta.dashboard.workflow import WorkflowConfig, WorkflowView
from fx_talanta.evaluation.operations import Binding, Operations
from fx_talanta.evaluation.runner import Runner


def prepared(tmp_path):
    runner, clock, sha, dataset, config = setup(tmp_path)
    ops, binding = Operations.create(
        tmp_path / "queue.sqlite",
        Binding(source_id=uuid4(), runner=str(runner.path), registration_hash=sha),
        clock,
    )
    return runner, clock, sha, dataset, ops, binding


def test_queue_restart_and_direct_dashboard_lifecycle(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("network forbidden")

    monkeypatch.setattr(socket, "socket", forbidden)
    runner, clock, sha, dataset, ops, binding = prepared(tmp_path)
    ui_clock = FakeClock(demo().captured_at + timedelta(days=1))
    view_config = dict(journal=str(runner.path), plan_hash=sha, source_kind="RUNNER")
    app = Dashboard(
        demo(), tmp_path / "ui", "x" * 40, ui_clock, workflow_view=WorkflowView(view_config)
    )
    try:
        for at, tick in ticks(dataset):
            clock.advance(at - clock.now())
            ops.enqueue(tick, binding)
            ops = Operations(ops.path, clock)
            assert ops.drain_one(binding)["status"] == "ACKNOWLEDGED"
            assert ops.enqueue(tick, binding)["replayed"]
            view = app.overview()["matched_workflow"]
            assert view["source_kind"] == "RUNNER" and view["observations"] == tick.sequence
            assert str(runner.path) not in json.dumps(view)
        assert ops.drain_one(binding)["status"] == "EMPTY"
        ops.stop(binding, "fixture done")
        report = ops.report(binding)
        assert report["pending"] == 0 and report["acknowledged"] == 6
        assert report["status"] == "SEALED" and not report["source_qualified"]
        assert report["runner"]["status"] == "STOPPED"
        assert all(
            a["closed_simulated_positions"] == 1 and not a["open_positions"]
            for a in report["runner"]["arms"].values()
        )
        assert app.overview()["matched_workflow"]["status"] == "STOPPED"
    finally:
        app.close()


def test_lost_ack_reconciles_exact_input_without_new_transition(tmp_path, monkeypatch):
    runner, clock, sha, dataset, ops, binding = prepared(tmp_path)
    at, tick = next(ticks(dataset))
    clock.advance(at - clock.now())
    ops.enqueue(tick, binding)

    def crash(*args):
        raise RuntimeError("lost acknowledgement after committed simulator transition")

    monkeypatch.setattr(ops, "_acknowledge", crash)
    with pytest.raises(RuntimeError):
        ops.drain_one(binding)
    report = ops.report(binding)
    assert report["unacknowledged_runner_commit"] and report["pending"] == 1
    head = runner.report(sha)["receipt_hash"]
    resumed = Operations(ops.path, clock)
    assert resumed.drain_one(binding)["replayed"]
    assert runner.report(sha)["receipt_hash"] == head
    assert resumed.report(binding)["acknowledged"] == 1


def test_stop_is_durable_before_runner_stop_and_retry_does_not_reopen(tmp_path, monkeypatch):
    runner, clock, sha, dataset, ops, binding = prepared(tmp_path)
    original = Runner.stop

    def crash(*args):
        raise RuntimeError("between seal and stop")

    monkeypatch.setattr(Runner, "stop", crash)
    with pytest.raises(RuntimeError):
        ops.stop(binding, "owner stop")
    at, tick = next(ticks(dataset))
    clock.advance(at - clock.now())
    with pytest.raises(ValueError, match="sealed"):
        ops.enqueue(tick, binding)
    monkeypatch.setattr(Runner, "stop", original)
    ops.stop(binding, "owner stop")
    assert ops.report(binding)["runner"]["status"] == "STOPPED"
    with pytest.raises(ValueError):
        ops.stop(binding, "changed reason")


def test_delayed_queue_never_retimes_quotes(tmp_path):
    runner, clock, sha, dataset, ops, binding = prepared(tmp_path)
    for at, tick in ticks(dataset):
        clock.advance(at + timedelta(seconds=3) - clock.now())
        ops.enqueue(tick, binding)
        ops.drain_one(binding)
    report = ops.report(binding)
    assert all(
        a["closed_simulated_positions"] == 0 and not a["open_positions"]
        for a in report["runner"]["arms"].values()
    )


def test_unrelated_direct_runner_input_cannot_be_adopted(tmp_path):
    runner, clock, sha, dataset, ops, binding = prepared(tmp_path)
    at, tick = next(ticks(dataset))
    clock.advance(at - clock.now())
    ops.enqueue(tick, binding)
    runner.admit(tick.model_copy(update={"news": "ADVERSE"}), sha)
    with pytest.raises(ValueError, match="does not match"):
        ops.report(binding)
    with pytest.raises(ValueError):
        ops.drain_one(binding)


def test_ack_and_runner_rollback_detected(tmp_path):
    runner, clock, sha, dataset, ops, binding = prepared(tmp_path)
    before = runner.path.read_bytes()
    at, tick = next(ticks(dataset))
    clock.advance(at - clock.now())
    ops.enqueue(tick, binding)
    ops.drain_one(binding)
    good = runner.path.read_bytes()
    runner.path.write_bytes(before)
    with pytest.raises(ValueError):
        ops.report(binding)
    runner.path.write_bytes(good)
    with sqlite3.connect(ops.path) as conn:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("UPDATE acknowledgements SET runner_sha='bad'")
        conn.execute("DROP TRIGGER forbid_acknowledgements_UPDATE")
        conn.execute("UPDATE acknowledgements SET runner_sha='bad'")
    with pytest.raises(ValueError):
        ops.report(binding)


def test_wrong_source_future_sequence_and_copy_bypass_rejected(tmp_path):
    runner, clock, sha, dataset, ops, binding = prepared(tmp_path)
    at, tick = next(ticks(dataset))
    with pytest.raises(ValueError, match="future"):
        ops.enqueue(tick, binding)
    clock.advance(at - clock.now())
    for invalid in (
        tick.model_copy(update={"sequence": True}),
        tick.model_copy(update={"sequence": 2}),
    ):
        with pytest.raises(ValueError):
            ops.enqueue(invalid, binding)
    with pytest.raises(ValueError, match="binding"):
        ops.enqueue(tick, "0" * 64)
    assert ops.report(binding)["queued"] == 0


def test_direct_dashboard_retains_terminal_checkpoint_and_clears_missing_source(tmp_path):
    runner, clock, sha, dataset, ops, binding = prepared(tmp_path)
    before = runner.path.read_bytes()
    ops.stop(binding, "done")
    terminal = runner.path.read_bytes()
    config = dict(journal=str(runner.path), plan_hash=sha, source_kind="RUNNER")
    ui_clock = FakeClock(demo().captured_at + timedelta(days=1))
    app = Dashboard(demo(), tmp_path / "ui", "x" * 40, ui_clock, workflow_view=WorkflowView(config))
    assert app.overview()["matched_workflow"]["status"] == "STOPPED"
    app.close()
    runner.path.write_bytes(before)
    app = Dashboard(demo(), tmp_path / "ui", "x" * 40, ui_clock, workflow_view=WorkflowView(config))
    try:
        assert app.overview()["matched_workflow"]["status"] == "UNAVAILABLE"
        runner.path.write_bytes(terminal)
        assert app.overview()["matched_workflow"]["status"] == "STOPPED"
        runner.path.rename(tmp_path / "offline.sqlite")
        assert app.overview()["matched_workflow"]["status"] == "UNAVAILABLE"
    finally:
        app.close()


def test_legacy_workflow_binding_serialization_is_unchanged():
    legacy = dict(journal="fixture.sqlite", plan_hash="a" * 64)
    assert WorkflowConfig(**legacy).model_dump(mode="json") == legacy


def test_source_capacity_and_pending_inputs_survive_stop(tmp_path):
    runner, clock, sha, dataset, config = setup(tmp_path, max_observations=1)
    ops, binding = Operations.create(
        tmp_path / "queue.sqlite",
        Binding(source_id=uuid4(), runner=str(runner.path), registration_hash=sha, capacity=1),
        clock,
    )
    stream = list(ticks(dataset))
    at, tick = stream[0]
    clock.advance(at - clock.now())
    ops.enqueue(tick, binding)
    assert ops.report(binding)["status"] == "CAPACITY_REACHED"
    with pytest.raises(ValueError):
        ops.enqueue(stream[1][1], binding)
    ops.stop(binding, "keep pending evidence")
    assert ops.report(binding)["pending"] == 1
    assert runner.report(sha)["observations"] == 0
