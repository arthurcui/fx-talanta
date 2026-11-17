"""Full-history catalog replay preserves source binding and at-most-once exposure."""

import json
import shutil
import time
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from test_candidate_research import RULES, specification
from test_session_study import source

from fx_talanta.clock import FakeClock
from fx_talanta.dashboard.app import Dashboard
from fx_talanta.dashboard.demo import AT, demo
from fx_talanta.dashboard.indexed_research import IndexedBundle
from fx_talanta.research.spool import file_hash
from tools.fixtures.b01_replay import scenario


@pytest.fixture
def indexed(tmp_path):
    _, path = source(tmp_path)
    catalog = tmp_path / "catalog"
    catalog.mkdir()
    shutil.copyfile(path, catalog / "eurusd.sqlite")
    _, e = scenario()
    start = datetime(2025, 1, 16, 12, tzinfo=UTC)
    e = e.model_copy(
        update=dict(
            start=start,
            training_end=start + timedelta(hours=1),
            validation_end=start + timedelta(hours=2),
            end=start + timedelta(hours=3),
        )
    )
    b = IndexedBundle(
        index_file="eurusd.sqlite",
        index_sha256=file_hash(catalog / "eurusd.sqlite"),
        experiment=e,
        assume_research_inputs=True,
    )
    (catalog / "eurusd-index.json").write_text(b.model_dump_json())
    app = Dashboard(demo(), tmp_path / "state", "x" * 40, FakeClock(AT), dataset_directory=catalog)
    saved = app.strategies.save(
        dict(request_id=str(uuid4()), strategy_id=str(uuid4()), specification=specification())
    )
    app.strategies.freeze(dict(sha256=saved["sha256"]))
    reg = app.research.select_dataset(
        dict(
            dataset_id=app.research.catalog.metadata[0]["id"],
            candidate_sha256=saved["sha256"],
            rules=RULES,
            reviewed_mapping=True,
        )
    )
    yield app, reg, catalog
    for _ in range(100):
        if not app.research.active_runs:
            break
        time.sleep(0.02)
    app.close()


def completed(app, key):
    for _ in range(100):
        status = app.research.run_status(key)
        if status["status"] != "RUNNING":
            return status
        time.sleep(0.02)
    raise AssertionError("background fixture did not finish")


def test_full_index_background_result_and_duplicate_request(indexed):
    app, reg, _ = indexed
    request = dict(registration_id=reg["id"], partition="training")
    started = app.research.execute(request)
    result = completed(app, started["id"])
    assert result["outcome"]["kind"] == "BACKTEST"
    payload = result["outcome"]["payload"]
    assert payload["result"]["coverage"]["ticks"] == 3
    assert payload["result"]["diagnostics"]["symbol"] == "EURUSD"
    assert payload["result"]["diagnostics"]["duration_seconds"] == 3600
    assert payload["result"]["diagnostics"]["hold_reasons"]["INDICATOR_WARMUP"] > 0
    assert payload["result"]["audit_streams"]["journal"]["rows"] > 0
    assert app.research.execute(request)["outcome"]["id"] == result["outcome"]["id"]
    assert len(list((app.state / "research-runs").iterdir())) == 1
    assert not payload["execution_enabled"]


def test_index_mutation_fails_once_and_cannot_be_forged_by_upload(indexed):
    app, reg, catalog = indexed
    with pytest.raises(ValueError, match="catalog"):
        app.research.register(reg["payload"])
    with (catalog / "eurusd.sqlite").open("ab") as out:
        out.write(b"tamper")
    request = dict(registration_id=reg["id"], partition="training")
    started = app.research.execute(request)
    result = completed(app, started["id"])
    assert result["outcome"]["status"] == "FAILED_NO_RESEND"
    assert app.research.execute(request)["outcome"] == result["outcome"]


def test_interrupted_claim_is_not_restarted(indexed):
    app, reg, _ = indexed
    from fx_talanta.research.replay import digest

    request = dict(registration_id=reg["id"], partition="training")
    key = digest(request)
    with app.repo.conn:
        app.repo.conn.execute(
            "INSERT INTO research_runs VALUES (?,?,NULL)", (key, json.dumps(request))
        )
    assert app.research.execute(request)["status"] == "INTERRUPTED_NO_RESEND"
    assert not app.research.active_runs


def test_single_worker_and_duplicate_admission(indexed, monkeypatch):
    import threading

    from fx_talanta.dashboard import indexed_research

    app, reg, _ = indexed
    original = indexed_research.replay
    release = threading.Event()
    entered = threading.Event()
    calls = []

    def held(*args):
        calls.append(1)
        entered.set()
        assert release.wait(5)
        return original(*args)

    monkeypatch.setattr(indexed_research, "replay", held)
    request = dict(registration_id=reg["id"], partition="training")
    started = app.research.execute(request)
    try:
        assert entered.wait(2)
        assert app.research.execute(request)["id"] == started["id"]
        with pytest.raises(ValueError, match="another historical replay"):
            app.research.execute(dict(request, partition="validation"))
        assert calls == [1]
    finally:
        release.set()
    assert completed(app, started["id"])["outcome"]["kind"] == "BACKTEST"
