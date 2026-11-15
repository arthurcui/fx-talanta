"""Offline lifecycle records preserve versions without granting trading authority."""

import sqlite3
from uuid import uuid4

import pytest

from fx_talanta.clock import FakeClock
from fx_talanta.dashboard.app import Dashboard
from fx_talanta.dashboard.demo import AT, demo


def draft(**changes):
    return dict(
        request_id=str(uuid4()),
        strategy_id=str(uuid4()),
        parent=None,
        specification=dict(
            name="Test hypothesis",
            hypothesis="Synthetic research hypothesis only",
            input_policy="Completed bars and verified calendar coverage required",
            entry_rules="Explicit signal rules await executable implementation",
            exit_rules="Protective exits and time-based exit required",
            portfolio_policy="Limit combined signed USD exposure across both pairs",
            evaluation_plan="Register holdout, base and stress costs before testing",
            risk_per_trade_pct="0.10",
            total_open_risk_pct="0.20",
            daily_loss_limit_pct="0.50",
            provenance="Human-authored synthetic test record",
        ),
        **changes,
    )


@pytest.fixture
def app(tmp_path):
    value = Dashboard(demo(), tmp_path, "x" * 40, FakeClock(AT))
    yield value
    value.close()


def test_save_freeze_retry_and_resume_preserve_exact_version(tmp_path):
    app = Dashboard(demo(), tmp_path, "x" * 40, FakeClock(AT))
    request = draft()
    saved = app.strategies.save(request)
    assert app.strategies.save(request) == saved
    frozen = app.strategies.freeze(dict(sha256=saved["sha256"]))
    assert app.strategies.freeze(dict(sha256=saved["sha256"])) == frozen
    assert not frozen["executable"] and not frozen["execution_enabled"]
    assert not frozen["qualified_for_paper"]
    app.close()
    app = Dashboard(demo(), tmp_path, "x" * 40, FakeClock(AT))
    try:
        assert app.strategies.read()["records"] == [frozen]
        revised = dict(request, request_id=str(uuid4()), parent=frozen["sha256"])
        revised["specification"] = dict(request["specification"], name="Revised hypothesis")
        result = app.strategies.save(revised)
        assert result["version"] == 2 and result["state"] == "DRAFT"
        assert app.strategies.read()["records"][1] == frozen
    finally:
        app.close()


def test_request_conflict_stale_parent_and_old_freeze_rejected(app):
    request = draft()
    first = app.strategies.save(request)
    changed = dict(
        request, specification=dict(request["specification"], name="Different hypothesis")
    )
    with pytest.raises(ValueError, match="identity"):
        app.strategies.save(changed)
    second = dict(changed, request_id=str(uuid4()), parent=first["sha256"])
    app.strategies.save(second)
    with pytest.raises(ValueError, match="parent"):
        app.strategies.save(dict(second, request_id=str(uuid4())))
    with pytest.raises(ValueError, match="latest"):
        app.strategies.freeze(dict(sha256=first["sha256"]))


@pytest.mark.parametrize(
    "changes",
    [
        {"pairs": ["EURUSD", "BTCUSD"]},
        {"risk_per_trade_pct": "0.30"},
        {"risk_per_trade_pct": "NaN"},
        {"risk_per_trade_pct": True},
        {"total_open_risk_pct": "101"},
        {"hypothesis": " " * 20},
        {"execution_enabled": True},
        {"authorship": "VERIFIED_AI"},
    ],
)
def test_invalid_scope_risk_or_authority_cannot_be_saved(app, changes):
    request = draft()
    request["specification"].update(changes)
    with pytest.raises(ValueError):
        app.strategies.save(request)
    assert app.strategies.read()["records"] == []


def test_no_network_or_trading_and_immutable_history(app, monkeypatch):
    import socket

    monkeypatch.setattr(socket, "socket", lambda *a, **k: pytest.fail("unexpected network"))
    record = app.strategies.save(draft())
    app.strategies.freeze(dict(sha256=record["sha256"]))
    summary = app.strategies.read()
    assert not summary["execution_enabled"] and summary["active_strategy"] is None
    assert not summary["ai_generation_enabled"] and not summary["backtest_enabled"]
    assert len(summary["milestones"]) == 7 and len(summary["gaps"]) == 5
    for table in ("strategy_drafts", "strategy_freezes"):
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            with app.repo.conn:
                app.repo.conn.execute(f"DELETE FROM {table}")
