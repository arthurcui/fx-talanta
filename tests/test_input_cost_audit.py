import json
import sqlite3
from collections import Counter
from datetime import UTC, date, datetime
from decimal import Decimal as D

import pytest

from fx_talanta.research.cost_calibration import commission, financing, forex_rollovers
from tools.qualification.input_cost_audit import audit, distribution, retained_fees, weekend_seconds


def test_usd_notional_per_leg_and_account_conversion():
    assert commission(D(100000), D("1.1"), D(7), D(1)) == D("7.7")
    assert commission(D(100000), D(1), D(7), D(1)) == D(7)
    assert commission(D(100000), D("1.1"), D("2.5"), D(1)) == D("2.75")
    assert commission(D(100000), D("1.2"), D(7), D("1.4")) == D("11.76")
    with pytest.raises(ValueError):
        commission(D(100000), D(1), D(7), None)


def test_rollover_uses_cutoff_not_elapsed_days_and_signed_rates():
    opened = datetime(2025, 1, 8, 21, 59, tzinfo=UTC)
    closed = datetime(2025, 1, 8, 22, 1, tzinfo=UTC)
    events = forex_rollovers(opened, closed, holiday_multipliers={})
    assert events == [(date(2025, 1, 8), 3)]
    assert financing(D("0.1"), events, {date(2025, 1, 8): D("-5")}) == D("-1.5")
    assert financing(D("0.1"), events, {date(2025, 1, 8): D("5")}) == D("1.5")
    with pytest.raises(KeyError):
        financing(D("0.1"), events, {})
    with pytest.raises(ValueError):
        forex_rollovers(opened, closed, holiday_multipliers=None)
    assert forex_rollovers(opened, opened, holiday_multipliers={}) == []


def test_dst_and_holiday_override_and_cutoff_ambiguity():
    start = datetime(2025, 7, 9, 20, 59, tzinfo=UTC)
    end = datetime(2025, 7, 9, 21, 1, tzinfo=UTC)
    assert forex_rollovers(start, end, holiday_multipliers={date(2025, 7, 9): 4}) == [
        (date(2025, 7, 9), 4)
    ]
    with pytest.raises(ValueError):
        forex_rollovers(start, end.replace(minute=0), holiday_multipliers={})


def test_proxy_splits_weekend_from_unexplained_gap():
    start = datetime(2025, 1, 3, 21, tzinfo=UTC)
    end = datetime(2025, 1, 5, 23, tzinfo=UTC)
    assert weekend_seconds(start, end) == 48 * 3600
    assert (end - start).total_seconds() - weekend_seconds(start, end) == 7200


def test_tick_weighted_nearest_rank_quantiles():
    result = distribution(Counter({D(1): 98, D(20): 2}))
    assert result["p95"] == "1"
    assert result["p99"] == "20"
    with pytest.raises(ValueError):
        distribution(Counter())


def test_retained_fee_population_is_demo_unique_and_sanitized(tmp_path):
    path = tmp_path / "saved.json"
    deal = {
        "type": 0,
        "entry": 0,
        "ticket": 123,
        "symbol": "EURUSD.",
        "volume": 0.01,
        "commission": -1,
        "swap": 0,
        "fee": 0,
    }
    data = {
        "account": {"trade_mode": 0, "currency": "CAD", "login": "private"},
        "deals": [deal, {"type": 2}],
    }
    path.write_text(json.dumps(data))
    result = retained_fees(path)
    assert result["deal_count"] == 1
    assert result["charges"]["commission"] == "-1"
    assert "private" not in json.dumps(result)
    data["deals"].append(deal)
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        retained_fees(path)
    data["account"]["trade_mode"] = 2
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        retained_fees(path)


def test_actual_sqlite_audit_keeps_ties_and_rejects_crossed_quote(tmp_path):
    path = tmp_path / "ticks.sqlite"
    at = int(datetime(2025, 1, 2, tzinfo=UTC).timestamp() * 1000)
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE ticks(seq INTEGER, at_ms INTEGER, bid TEXT, ask TEXT)")
        db.execute("CREATE TABLE metadata(value TEXT)")
        db.execute(
            "INSERT INTO metadata VALUES (?)",
            (
                json.dumps(
                    {
                        "rows": 2,
                        "archive_sha256": "fixture",
                        "status": "COMPLETE",
                        "symbol": "EURUSD",
                    }
                ),
            ),
        )
        db.executemany(
            "INSERT INTO ticks VALUES(?,?,?,?)",
            [(0, at, "1.1", "1.1002"), (1, at, "1.1", "1.1002")],
        )
    result = audit(path, "EURUSD")
    assert result["timestamp_ties"] == result["adjacent_duplicate_rows"] == 1
    assert result["unchanged_after_read"]
    with sqlite3.connect(path) as db:
        db.execute("UPDATE ticks SET ask='1.0' WHERE seq=1")
    with pytest.raises(ValueError):
        audit(path, "EURUSD")
