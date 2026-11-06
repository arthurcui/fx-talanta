"""Portable stopped evidence and source inspection; all inputs are synthetic."""

import json
from datetime import timedelta

import pytest
from test_dashboard_paper_runner import ticks
from test_dashboard_runner_operations import prepared

from fx_talanta.clock import FakeClock
from fx_talanta.dashboard.app import Dashboard
from fx_talanta.dashboard.demo import demo
from fx_talanta.dashboard.workflow import WorkflowView
from fx_talanta.evaluation.archive import capture, restore, verify


def queued(tmp_path):
    runner, clock, sha, dataset, ops, binding = prepared(tmp_path)
    at, tick = next(ticks(dataset))
    clock.advance(at - clock.now())
    ops.enqueue(tick, binding)
    return runner, clock, ops, binding


def test_portable_stopped_archive_without_originals(tmp_path, monkeypatch):
    import socket

    monkeypatch.setattr(socket, "socket", lambda *a, **k: pytest.fail("network forbidden"))
    runner, clock, ops, binding = queued(tmp_path)
    ops.drain_one(binding)
    ops.stop(binding, "archive fixture")
    original = (runner.path.read_bytes(), ops.path.read_bytes())
    receipt = capture(ops.path, binding, tmp_path / "archive", clock)
    assert original == (runner.path.read_bytes(), ops.path.read_bytes())
    runner.path.rename(tmp_path / "original-runner.sqlite")
    ops.path.rename(tmp_path / "original-source.sqlite")
    result = restore(tmp_path / "archive", receipt["manifest_hash"], tmp_path / "restored")
    assert result["result"] == "VERIFIED" and result["inspection_only"]
    assert not result["current_readiness"] and not result["execution_enabled"]
    assert result["report"]["acknowledged"] == 1
    with pytest.raises(FileExistsError):
        restore(tmp_path / "archive", receipt["manifest_hash"], tmp_path / "restored")


def test_backup_refuses_running_and_interrupted_stop(tmp_path, monkeypatch):
    runner, clock, ops, binding = queued(tmp_path)
    with pytest.raises(ValueError, match="stop"):
        capture(ops.path, binding, tmp_path / "archive", clock)
    assert not (tmp_path / "archive").exists()
    from fx_talanta.evaluation.runner import Runner

    monkeypatch.setattr(Runner, "stop", lambda *a: None)
    ops.stop(binding, "interrupted")
    with pytest.raises(ValueError, match="stop"):
        capture(ops.path, binding, tmp_path / "archive", clock)


@pytest.mark.parametrize(
    "damage", ["source.sqlite", "runner.sqlite", "manifest.json", "wrong-hash", "wal"]
)
def test_archive_tampering_fails_before_restore(tmp_path, damage):
    runner, clock, ops, binding = queued(tmp_path)
    ops.stop(binding, "pending retained")
    archive = tmp_path / "archive"
    receipt = capture(ops.path, binding, archive, clock)
    expected = receipt["manifest_hash"]
    if damage == "wrong-hash":
        expected = "0" * 64
    elif damage == "wal":
        (archive / "runner.sqlite-wal").write_bytes(b"unexpected sidecar")
    else:
        with (archive / damage).open("ab") as stream:
            stream.write(b"damaged")
    with pytest.raises((ValueError, json.JSONDecodeError)):
        restore(archive, expected, tmp_path / "restored")
    assert not (tmp_path / "restored").exists()


def test_pending_and_unacknowledged_commit_preserved_in_archive(tmp_path, monkeypatch):
    runner, clock, ops, binding = queued(tmp_path)
    monkeypatch.setattr(ops, "_acknowledge", lambda *a: (_ for _ in ()).throw(RuntimeError()))
    with pytest.raises(RuntimeError):
        ops.drain_one(binding)
    ops.stop(binding, "preserve uncertain acknowledgement")
    receipt = capture(ops.path, binding, tmp_path / "archive", clock)
    report = verify(tmp_path / "archive", receipt["manifest_hash"])["report"]
    assert report["pending"] == 1 and report["unacknowledged_runner_commit"]
    assert report["acknowledged"] == 0


def test_queue_checkpoint_catches_enqueue_ack_and_stop_rollback(tmp_path):
    runner, clock, ops, binding = queued(tmp_path)
    queued_bytes = ops.path.read_bytes()
    ops.drain_one(binding)
    acknowledged = ops.path.read_bytes()
    cursor = ops.report(binding)["checkpoint"]
    ops.path.write_bytes(queued_bytes)
    with pytest.raises(ValueError, match="checkpoint"):
        ops.report(binding, cursor)
    ops.path.write_bytes(acknowledged)
    ops.stop(binding, "stop")
    cursor = ops.report(binding)["checkpoint"]
    ops.path.write_bytes(acknowledged)
    with pytest.raises(ValueError, match="checkpoint"):
        ops.report(binding, cursor)


def test_operations_dashboard_retains_queue_cursor_and_clears_missing(tmp_path):
    runner, clock, ops, binding = queued(tmp_path)
    before = ops.path.read_bytes()
    ops.drain_one(binding)
    config = dict(journal=str(ops.path), plan_hash=binding, source_kind="OPERATIONS")
    ui_clock = FakeClock(demo().captured_at + timedelta(days=1))

    def app():
        return Dashboard(
            demo(), tmp_path / "ui", "x" * 40, ui_clock, workflow_view=WorkflowView(config)
        )

    ui = app()
    view = ui.overview()["matched_workflow"]
    assert view["source_queue"]["acknowledged"] == 1
    assert view["source_queue"]["producer_liveness"] == "UNVERIFIED"
    assert "checkpoint" not in view["source_queue"]
    assert str(runner.path) not in json.dumps(view)
    ui.close()
    ops.path.write_bytes(before)
    ui = app()
    try:
        assert ui.overview()["matched_workflow"]["status"] == "UNAVAILABLE"
    finally:
        ui.close()
