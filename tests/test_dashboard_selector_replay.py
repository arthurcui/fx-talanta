"""Recorded replies exercise the simulation selector boundary without provider calls."""

import json
import socket
import sqlite3
from datetime import timedelta
from uuid import uuid4

import pytest
from test_dashboard_paper_runner import setup, ticks

from fx_talanta.evaluation.runner import Runner, Tick
from fx_talanta.evaluation.selectors import Batch, Profile, Reply, assess
from tools.qualification.runner_selector_acceptance import fixture_batch, run


def prepared(tmp_path):
    profile = Profile(model="fixture-model/1", prompt_hash="b" * 64)
    runner, clock, sha, dataset, config = setup(
        tmp_path, selector="RECORDED_MODEL_RESPONSES", selector_profile=profile
    )
    at, tick = next(ticks(dataset))
    clock.advance(at - clock.now())
    request = runner.prepare_selector(tick, sha)
    return runner, clock, sha, tick, request, profile, dataset


def test_recorded_pipeline_reopen_and_no_network(tmp_path, monkeypatch):
    monkeypatch.setattr(socket, "socket", lambda *a, **k: pytest.fail("network forbidden"))
    result = run(tmp_path / "fixture")
    assert result["result"] == "PASS"
    report = result["report"]["runner"]
    assert report["selector"] == "RECORDED_MODEL_RESPONSES"
    assert report["normalized_inputs"] == 6
    assert not report["full_M5_complete"]
    assert all(
        s["maximum_reported_latency_ms"] == 250 for s in report["recorded_model_summary"].values()
    )


@pytest.mark.parametrize(
    "case,reason",
    [
        ("timeout", "MODEL_TIMEOUT"),
        ("malformed", "MODEL_MALFORMED"),
        ("wrong-model", "MODEL_IDENTITY_MISMATCH"),
        ("wrong-request", "MODEL_REQUEST_MISMATCH"),
        ("candidate", "MODEL_UNSUPPORTED_SELECTION"),
        ("exit", "MODEL_UNSUPPORTED_SELECTION"),
        ("extra-field", "MODEL_MALFORMED"),
        ("late", "MODEL_LATENCY_EXCEEDED"),
    ],
)
def test_bad_replies_are_bounded_holds(tmp_path, case, reason):
    runner, clock, sha, tick, requests, profile, dataset = prepared(tmp_path)
    request = requests["requests"]["AI_NEWS"]
    # Test candidate restrictions independently of whether the first observation signals.
    request["payload"]["allowed_exits"] = ["TIME_EXIT"]
    batch = fixture_batch(requests)
    raw = batch.replies["AI_NEWS"].model_dump()
    if case == "timeout":
        raw["status"] = "TIMEOUT"
    elif case == "malformed":
        raw["response"] = "not json"
    elif case == "wrong-model":
        raw["returned_model"] = "different"
    elif case == "wrong-request":
        raw["request_hash"] = "0" * 64
    elif case == "late":
        raw["completed_at"] = clock.now() + timedelta(milliseconds=1501)
    else:
        content = json.loads(raw["response"])
        if case == "candidate":
            content["candidate_id"] = str(uuid4())
        if case == "exit":
            content["exit_option"] = "FIXED"
        if case == "extra-field":
            content["volume"] = "100"
        raw["response"] = json.dumps(content)
    verdict = assess(
        profile, request, Reply(**raw), clock.now(), clock.now() + timedelta(seconds=2)
    )
    assert not verdict["allowed"] and verdict["reason"] == reason


def test_request_read_only_news_ablation_and_future_reply_rejection(tmp_path):
    runner, clock, sha, tick, requests, profile, dataset = prepared(tmp_path)
    before = runner.path.read_bytes()
    assert requests == runner.prepare_selector(tick, sha)
    assert before == runner.path.read_bytes()
    assert "news" not in requests["requests"]["AI_NO_NEWS"]["payload"]
    assert requests["requests"]["AI_NEWS"]["payload"]["news"] == "NEUTRAL"
    selected = Tick.model_validate(tick.model_dump() | {"model_batch": fixture_batch(requests)})
    with pytest.raises(ValueError, match="future model reply"):
        runner.admit(selected, sha)
    assert runner.report(sha)["observations"] == 0


def test_unknown_cost_retry_and_restart_are_not_free_or_reissued(tmp_path):
    runner, clock, sha, tick, requests, profile, dataset = prepared(tmp_path)
    raw = fixture_batch(requests).model_dump()
    raw["replies"]["AI_NEWS"]["reported_cost_usd"] = None
    batch = Batch.model_validate(raw)
    selected = Tick.model_validate(tick.model_dump() | {"model_batch": batch})
    clock.advance(timedelta(milliseconds=250))
    receipt = runner.admit(selected, sha)
    reopened = Runner(runner.path, clock)
    assert reopened.admit(selected, sha)["replayed"]
    report = reopened.report(sha, (receipt["sequence"], receipt["sha"]))
    assert report["recorded_model_summary"]["AI_NEWS"]["unknown_cost_replies"] == 1
    assert report["recorded_model_summary"]["AI_NEWS"]["recorded_replies"] == 1
    changed = selected.model_dump()
    changed["model_batch"]["replies"]["AI_NEWS"]["reported_cost_usd"] = "1"
    with pytest.raises(ValueError):
        reopened.admit(Tick.model_validate(changed), sha)
    export = reopened.export(sha, tmp_path / "receipts.sqlite")
    assert export["derived_export"]
    with sqlite3.connect(runner.path) as conn:
        record = json.loads(conn.execute("SELECT result FROM ticks").fetchone()[0])
    decisions = [r["payload"] for r in record["receipts"] if r["kind"] == "DECIDE"]
    assert [d["latency_ms"] for d in decisions] == [0, 250, 250]


def test_missing_batch_and_changed_profile_do_not_bypass_mode(tmp_path):
    runner, clock, sha, tick, requests, profile, dataset = prepared(tmp_path)
    with pytest.raises(ValueError, match="selector mode"):
        runner.admit(tick, sha)
    with pytest.raises(ValueError):
        Batch(requested_at=clock.now(), replies={})
    with pytest.raises(ValueError):
        Profile(model="fixture", prompt_hash="a" * 64, max_latency_ms=2001)
    assert runner.report(sha)["observations"] == 0


def test_model_delay_never_relaxes_two_second_quote_rule(tmp_path):
    runner, clock, sha, first, request, profile, dataset = prepared(tmp_path)
    for at, tick in ticks(dataset):
        clock.advance(max(timedelta(0), at - clock.now()))
        requests = runner.prepare_selector(tick, sha)
        selected = Tick.model_validate(
            tick.model_dump() | {"model_batch": fixture_batch(requests, 3000)}
        )
        clock.advance(timedelta(seconds=3))
        runner.admit(selected, sha)
    report = runner.report(sha)
    assert all(
        a["closed_simulated_positions"] == 0 and a["open_positions"] == 0
        for a in report["arms"].values()
    )
    assert report["recorded_model_summary"]["AI_NEWS"]["rejected_or_hold"] == 6
