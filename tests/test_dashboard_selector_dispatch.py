"""Simulation-only dispatch reservations, uncertainty and publication recovery."""

import socket
from datetime import timedelta
from uuid import uuid4

import pytest
from test_dashboard_paper_runner import setup, ticks

from fx_talanta.clock import FakeClock
from fx_talanta.dashboard.app import Dashboard
from fx_talanta.dashboard.demo import demo
from fx_talanta.dashboard.workflow import WorkflowView
from fx_talanta.evaluation.dispatch import Delivery, Dispatcher, Policy
from fx_talanta.evaluation.operations import Binding, Operations
from fx_talanta.evaluation.selectors import Profile
from tools.qualification.runner_selector_acceptance import run


def prepared(tmp_path, **limits):
    runner, clock, sha, dataset, config = setup(
        tmp_path,
        selector="RECORDED_MODEL_RESPONSES",
        selector_profile=Profile(model="fixture-model/1", prompt_hash="b" * 64),
    )
    ops, source = Operations.create(
        tmp_path / "source.sqlite",
        Binding(source_id=uuid4(), runner=str(runner.path), registration_hash=sha),
        clock,
    )
    policy = Policy(
        queue=str(ops.path),
        source_hash=source,
        deadline=config.deadline,
        **(dict(max_calls=12, tokens_per_call=200, max_reserved_tokens=2400) | limits),
    )
    dispatcher, binding = Dispatcher.create(tmp_path / "dispatch.sqlite", policy, clock)
    stream = list(ticks(dataset))
    clock.advance(stream[0][0] - clock.now())
    return runner, clock, sha, ops, source, dispatcher, binding, stream


def hold(request):
    return Delivery(
        status="RESPONSE",
        returned_model="fixture-model/1",
        response='{"action":"HOLD","candidate_id":null,"exit_option":null,"reason":"INSUFFICIENT_EVIDENCE"}',
        input_tokens=100,
        output_tokens=20,
    )


def test_full_dispatch_pipeline_is_simulation_only(tmp_path, monkeypatch):
    monkeypatch.setattr(socket, "socket", lambda *a, **k: pytest.fail("network forbidden"))
    result = run(tmp_path / "fixture", dispatch_mode=True)
    assert result["result"] == "PASS" and result["fixture_transport_calls"] == 12
    summary = result["report"]["model_dispatch"]
    assert summary["reserved_calls"] == 12 and summary["reserved_tokens"] == 2400
    assert summary["completed_replies"] == 12 and summary["unresolved_reserved_calls"] == 0
    assert summary["status"] == "STOPPED" and not summary["transport_verified"]


@pytest.mark.parametrize("after_first", [False, True])
def test_crash_never_resends_or_refunds(tmp_path, after_first):
    _, clock, _, ops, source, dispatcher, binding, stream = prepared(tmp_path)
    calls = []

    def transport(request):
        calls.append(request)
        assert dispatcher.report(binding)["model_dispatch"]["reserved_calls"] == 2
        if not after_first or len(calls) == 2:
            raise KeyboardInterrupt("simulated process death")
        return hold(request)

    with pytest.raises(KeyboardInterrupt):
        dispatcher.dispatch(stream[0][1], binding, transport)
    dispatcher = Dispatcher(dispatcher.path, clock)
    assert (
        dispatcher.dispatch(stream[0][1], binding, lambda r: pytest.fail("resent"))["status"]
        == "OUTCOME_UNKNOWN_NO_RESEND"
    )
    summary = dispatcher.report(binding)["model_dispatch"]
    assert summary["reserved_calls"] == 2 and summary["reserved_tokens"] == 400
    assert summary["unresolved_reserved_calls"] == (1 if after_first else 2)
    assert ops.report(source)["queued"] == 0


def test_exception_preserves_unknown_and_blocks_following_input(tmp_path):
    _, clock, _, _, _, dispatcher, binding, stream = prepared(tmp_path)

    def fail(request):
        raise RuntimeError("private transport detail")

    assert dispatcher.dispatch(stream[0][1], binding, fail)["status"] == "OUTCOME_UNKNOWN_NO_RESEND"
    clock.advance(stream[1][0] - clock.now())
    assert (
        dispatcher.dispatch(stream[1][1], binding, hold)["status"] == "UNRESOLVED_PREVIOUS_DISPATCH"
    )
    assert b"private transport detail" not in dispatcher.path.read_bytes()


def test_publication_checkpoint_crash_recovers_without_transport(tmp_path, monkeypatch):
    runner, clock, sha, ops, source, dispatcher, binding, stream = prepared(tmp_path)
    append = dispatcher._append

    def crash(expected, kind, event, payload):
        if kind == "PUBLISHED":
            raise RuntimeError("lost checkpoint")
        return append(expected, kind, event, payload)

    monkeypatch.setattr(dispatcher, "_append", crash)
    with pytest.raises(RuntimeError):
        dispatcher.dispatch(stream[0][1], binding, hold)
    assert ops.report(source)["queued"] == 1
    dispatcher = Dispatcher(dispatcher.path, clock)
    assert dispatcher.dispatch(stream[0][1], binding, lambda r: pytest.fail("resent"))["replayed"]
    ops.drain_one(source)
    assert runner.report(sha)["observations"] == 1
    assert dispatcher.report(binding)["model_dispatch"]["reserved_calls"] == 2


@pytest.mark.parametrize("limit", [dict(max_calls=2), dict(max_reserved_tokens=400)])
def test_pair_budget_is_cumulative_and_cannot_reset(tmp_path, limit):
    _, clock, _, ops, source, dispatcher, binding, stream = prepared(tmp_path, **limit)
    dispatcher.dispatch(stream[0][1], binding, hold)
    ops.drain_one(source)
    clock.advance(stream[1][0] - clock.now())
    reopened = Dispatcher(dispatcher.path, clock)
    assert (
        reopened.dispatch(stream[1][1], binding, lambda r: pytest.fail("budget bypass"))["status"]
        == "BUDGET_EXHAUSTED"
    )
    assert reopened.report(binding)["model_dispatch"]["reserved_calls"] == 2
    with pytest.raises(ValueError, match="binding"):
        reopened.report("0" * 64)


def test_overage_is_retained_and_stops_second_call(tmp_path):
    _, _, _, ops, source, dispatcher, binding, stream = prepared(tmp_path)
    calls = []

    def over(request):
        calls.append(request)
        return Delivery(status="ERROR", input_tokens=201, reported_cost_usd="0.2")

    assert dispatcher.dispatch(stream[0][1], binding, over)["status"] == "TOKEN_LIMIT_EXCEEDED"
    summary = dispatcher.report(binding)["model_dispatch"]
    assert len(calls) == 1 and summary["completed_replies"] == 1
    assert summary["known_reported_cost_usd"] == "0.2" and summary["unknown_cost_calls"] == 1
    assert ops.report(source)["queued"] == 0


def test_deadline_crossing_stops_remaining_transport(tmp_path):
    _, clock, _, ops, source, dispatcher, binding, stream = prepared(tmp_path)
    calls = []

    def slow(request):
        calls.append(request)
        clock.advance(timedelta(days=1))
        return hold(request)

    assert (
        dispatcher.dispatch(stream[0][1], binding, slow)["status"] == "DISPATCH_EXPIRED_NO_RESEND"
    )
    assert len(calls) == 1 and dispatcher.report(binding)["model_dispatch"]["status"] == "EXPIRED"
    assert ops.report(source)["queued"] == 0


def test_stop_and_concurrent_dispatch_cannot_send(tmp_path):
    _, clock, _, _, _, dispatcher, binding, stream = prepared(tmp_path)

    def concurrent(request):
        with pytest.raises(OSError):
            Dispatcher(dispatcher.path, clock).dispatch(
                stream[0][1], binding, lambda r: pytest.fail("concurrent send")
            )
        return hold(request)

    dispatcher.dispatch(stream[0][1], binding, concurrent)
    dispatcher.stop(binding)
    dispatcher.stop(binding)
    with pytest.raises(ValueError, match="stopped"):
        dispatcher.dispatch(stream[0][1], binding, lambda r: pytest.fail("stopped send"))


def test_dashboard_persists_dispatch_rollback_checkpoint(tmp_path):
    _, clock, _, _, _, dispatcher, binding, stream = prepared(tmp_path)
    before = dispatcher.path.read_bytes()

    def fail(request):
        raise RuntimeError()

    dispatcher.dispatch(stream[0][1], binding, fail)
    config = dict(journal=str(dispatcher.path), plan_hash=binding, source_kind="DISPATCH")
    ui_clock = FakeClock(demo().captured_at + timedelta(days=1))

    def app():
        return Dashboard(
            demo(), tmp_path / "ui", "x" * 40, ui_clock, workflow_view=WorkflowView(config)
        )

    ui = app()
    assert (
        ui.overview()["matched_workflow"]["source_queue"]["model_dispatch"][
            "unresolved_reserved_calls"
        ]
        == 2
    )
    ui.close()
    dispatcher.path.write_bytes(before)
    ui = app()
    try:
        assert ui.overview()["matched_workflow"]["status"] == "UNAVAILABLE"
    finally:
        ui.close()


def test_stopped_source_cannot_consume_dispatch_budget(tmp_path):
    _, _, _, ops, source, dispatcher, binding, stream = prepared(tmp_path)
    ops.stop(source, "stop before dispatch")
    with pytest.raises(ValueError, match="source"):
        dispatcher.dispatch(stream[0][1], binding, lambda r: pytest.fail("sent after stop"))
    assert dispatcher.report(binding)["model_dispatch"]["reserved_calls"] == 0


def test_wrong_normalized_source_cannot_consume_dispatch_budget(tmp_path):
    from test_dashboard_input_adapter import envelope

    from fx_talanta.evaluation.inputs import normalize

    _, clock, _, _, _, dispatcher, binding, stream = prepared(tmp_path)
    wrong = normalize(envelope(stream[0][1], clock.now(), uuid4()), clock.now())
    with pytest.raises(ValueError, match="source identity"):
        dispatcher.dispatch(wrong, binding, lambda r: pytest.fail("sent wrong source"))
    assert dispatcher.report(binding)["model_dispatch"]["reserved_calls"] == 0


def test_second_dispatcher_cannot_reset_unresolved_source_budget(tmp_path):
    _, clock, _, _, _, dispatcher, binding, stream = prepared(tmp_path)

    def fail(request):
        raise RuntimeError()

    dispatcher.dispatch(stream[0][1], binding, fail)
    with dispatcher.connect() as conn:
        policy = dispatcher.load(conn, binding)[0]
    with pytest.raises(FileExistsError):
        Dispatcher.create(tmp_path / "reset.sqlite", policy, clock)
    assert not (tmp_path / "reset.sqlite").exists()
    clone = tmp_path / "copy.sqlite"
    clone.write_bytes(dispatcher.path.read_bytes())
    with pytest.raises(ValueError, match="binding"):
        Dispatcher(clone, clock).report(binding)
