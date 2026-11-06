"""Typed source adapter acceptance with synthetic inputs and no external calls."""

import socket
import sqlite3
from datetime import timedelta
from uuid import uuid4

import pytest
from test_dashboard_paper_runner import ticks
from test_dashboard_runner_operations import prepared

from fx_talanta.evaluation.inputs import Envelope, SafetyEvidence, normalize
from fx_talanta.evaluation.operations import Operations
from fx_talanta.evaluation.runner import Tick


def envelope(tick, at, source_id, **changes):
    safety = SafetyEvidence(
        state="CLEAR",
        currencies=("EUR", "USD"),
        available_at=at,
        expires_at=at + timedelta(minutes=1),
        reference_hash="a" * 64,
    )
    data = dict(
        source_id=source_id,
        event_id=tick.event_id,
        sequence=tick.sequence,
        provenance="SYNTHETIC",
        channel="FIXTURE",
        received_at=at,
        market=tick.market,
        bars=tick.bars,
        calendar=safety,
        news=safety,
        news_content="NEUTRAL",
    )
    return Envelope(**(data | changes))


def test_normalized_source_through_all_arms_restart_and_evidence(tmp_path, monkeypatch):
    monkeypatch.setattr(socket, "socket", lambda *a, **k: pytest.fail("network forbidden"))
    runner, clock, sha, dataset, ops, binding = prepared(tmp_path)
    with ops.connect() as conn:
        source_id = ops.load(conn, binding)[0].source_id
    for at, tick in ticks(dataset):
        clock.advance(at - clock.now())
        source = envelope(tick, at, source_id)
        ops.enqueue_envelope(source, binding)
        ops = Operations(ops.path, clock)
        ops.drain_one(binding)
        assert ops.enqueue_envelope(source, binding)["replayed"]
    report = runner.report(sha)
    assert report["normalized_inputs"] == 6 and report["input_channels"] == ["FIXTURE"]
    assert all(a["closed_simulated_positions"] == 1 for a in report["arms"].values())
    assert report["full_M5_complete"] is False
    with sqlite3.connect(runner.path) as conn:
        tick = Tick.model_validate_json(
            conn.execute("SELECT payload FROM ticks LIMIT 1").fetchone()[0]
        )
        assert tick.market.quotes == tick.source_record.market.quotes
        assert tick.source_record.calendar.reference_hash == "a" * 64


@pytest.mark.parametrize("change", ["missing", "coverage", "expired", "blocked", "no-content"])
def test_incomplete_safety_fails_closed_without_retiming(tmp_path, change):
    runner, clock, sha, dataset, ops, binding = prepared(tmp_path)
    at, tick = next(ticks(dataset))
    source = envelope(tick, at, uuid4())
    data = source.model_dump()
    if change == "missing":
        data["calendar"] = None
    elif change == "coverage":
        data["calendar"]["currencies"] = ["USD"]
    elif change == "expired":
        data["calendar"]["available_at"] = at - timedelta(minutes=2)
        data["calendar"]["expires_at"] = at
    elif change == "blocked":
        data["calendar"]["state"] = "BLOCKED"
    else:
        data["news_content"] = "UNAVAILABLE"
    result = normalize(data, at)
    assert not result.market.calendar_ok or not result.market.news_ok
    assert result.market.at == tick.market.at and result.market.quotes == tick.market.quotes


def test_calendar_expires_in_queue_before_fresh_quote_is_admitted(tmp_path):
    runner, clock, sha, dataset, ops, binding = prepared(tmp_path)
    with ops.connect() as conn:
        source_id = ops.load(conn, binding)[0].source_id
    for at, tick in ticks(dataset):
        clock.advance(at - clock.now())
        source = envelope(tick, at, source_id)
        source = Envelope.model_validate(
            source.model_dump()
            | {
                "calendar": source.calendar.model_dump()
                | {"expires_at": at + timedelta(milliseconds=500)}
            }
        )
        ops.enqueue_envelope(source, binding)
        clock.advance(timedelta(seconds=1))
        ops.drain_one(binding)
    report = runner.report(sha)
    assert all(
        a["closed_simulated_positions"] == 0 and a["open_positions"] == 0
        for a in report["arms"].values()
    )
    with sqlite3.connect(runner.path) as conn:
        content = " ".join(row[0] for row in conn.execute("SELECT result FROM ticks"))
    assert "required input coverage" in content


def test_retry_keeps_first_normalization_and_changed_content_rejects(tmp_path):
    runner, clock, sha, dataset, ops, binding = prepared(tmp_path)
    with ops.connect() as conn:
        source_id = ops.load(conn, binding)[0].source_id
    at, tick = next(ticks(dataset))
    clock.advance(at - clock.now())
    source = envelope(tick, at, source_id)
    original = ops.enqueue_envelope(source, binding)
    clock.advance(timedelta(seconds=5))
    assert ops.enqueue_envelope(source, binding)["source_sha"] == original["source_sha"]
    with pytest.raises(ValueError, match="conflicting"):
        ops.enqueue_envelope(source.model_copy(update={"news_content": "ADVERSE"}), binding)


def test_wrong_identity_and_mixed_mode_rejected(tmp_path):
    runner, clock, sha, dataset, ops, binding = prepared(tmp_path)
    stream = list(ticks(dataset))
    at, tick = stream[0]
    clock.advance(at - clock.now())
    with pytest.raises(ValueError, match="identity"):
        ops.enqueue_envelope(envelope(tick, at, uuid4()), binding)
    with ops.connect() as conn:
        source_id = ops.load(conn, binding)[0].source_id
    ops.enqueue_envelope(envelope(tick, at, source_id), binding)
    at, tick = stream[1]
    clock.advance(at - clock.now())
    with pytest.raises(ValueError, match="mode"):
        ops.enqueue(tick, binding)
    with pytest.raises(ValueError, match="channel"):
        ops.enqueue_envelope(envelope(tick, at, source_id, channel="MCP"), binding)


def test_tampered_normalization_and_future_input_rejected(tmp_path):
    runner, clock, sha, dataset, ops, binding = prepared(tmp_path)
    at, tick = next(ticks(dataset))
    source = envelope(tick, at, uuid4(), calendar=None)
    with pytest.raises(ValueError):
        normalize(source, at - timedelta(seconds=1))
    normalized = normalize(source, at)
    raw = normalized.model_dump()
    raw["market"]["calendar_ok"] = True
    with pytest.raises(ValueError, match="preserved"):
        Tick.model_validate(raw)
    with pytest.raises(ValueError):
        normalize(source.model_copy(update={"sequence": True}), at)
    raw = source.model_dump()
    raw["received_at"] = at - timedelta(seconds=1)
    with pytest.raises(ValueError, match="unavailable"):
        Envelope.model_validate(raw)


def test_provenance_mismatch_preserves_pending_source(tmp_path):
    runner, clock, sha, dataset, ops, binding = prepared(tmp_path)
    with ops.connect() as conn:
        source_id = ops.load(conn, binding)[0].source_id
    at, tick = next(ticks(dataset))
    clock.advance(at - clock.now())
    ops.enqueue_envelope(envelope(tick, at, source_id, provenance="RECORDED_OFFLINE"), binding)
    with pytest.raises(ValueError, match="provenance"):
        ops.drain_one(binding)
    assert ops.report(binding)["pending"] == 1
    assert runner.report(sha)["observations"] == 0


def test_jpy_coverage_is_required_and_original_safety_cannot_be_widened(tmp_path):
    _, _, _, dataset, _, _ = prepared(tmp_path)
    at, tick = next(ticks(dataset))
    raw = envelope(tick, at, uuid4()).model_dump()
    raw["bars"] = ()
    raw["market"]["quotes"][0]["symbol"] = "USDJPY"
    instrument = raw["market"]["instruments"][0]
    instrument.update(symbol="USDJPY", base="USD", quote="JPY")
    raw["market"]["conversion"]["JPY"] = "0.01"
    assert not normalize(raw, at).market.calendar_ok
    raw["calendar"]["currencies"] = ("USD", "JPY")
    raw["news"]["currencies"] = ("USD", "JPY")
    assert normalize(raw, at).market.calendar_ok
    raw["market"].update(calendar_ok=False, news_ok=False, session_open=False, event_blackout=True)
    result = normalize(raw, at)
    assert not result.market.calendar_ok and not result.market.news_ok
    assert not result.market.session_open and result.market.event_blackout


def test_future_normalization_cannot_enter_queue(tmp_path):
    runner, clock, sha, dataset, ops, binding = prepared(tmp_path)
    with ops.connect() as conn:
        source_id = ops.load(conn, binding)[0].source_id
    at, tick = next(ticks(dataset))
    clock.advance(at - clock.now())
    source = normalize(envelope(tick, at, source_id), at + timedelta(seconds=1))
    with pytest.raises(ValueError, match="future source normalization"):
        ops.enqueue(source, binding)
