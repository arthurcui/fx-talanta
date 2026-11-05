from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from fx_talanta.research.baseline import Bar, evaluate

AT = datetime(2026, 11, 5, 12, tzinfo=UTC)


def bars():
    result = []
    for i in range(200):
        price = Decimal("1.0") + Decimal(i) / 10000
        at = AT - timedelta(hours=199 - i)
        result.append(
            Bar(
                symbol="EURUSD",
                timeframe="H1",
                close_at=at,
                available_at=at,
                revision=1,
                open=price,
                high=price,
                low=price,
                close=price,
            )
        )
    for i in range(21):
        at = AT - timedelta(minutes=(20 - i) * 15)
        result.append(
            Bar(
                symbol="EURUSD",
                timeframe="M15",
                close_at=at,
                available_at=at,
                revision=1,
                open="1",
                high="1.03" if i == 20 else "1.01",
                low="0.99",
                close="1.02" if i == 20 else "1",
            )
        )
    return result


def test_breakout_excludes_signal_bar_and_preserves_disabled_authority():
    result = evaluate(bars(), "EURUSD", AT, history_complete=True)
    assert result["side"] == "BUY" and result["action"] == "CANDIDATE"
    assert not result["execution_enabled"]
    assert Decimal(result["target_distance"]) == 2 * Decimal(result["stop_distance"])
    assert datetime.fromisoformat(result["time_exit_at"]) == AT + timedelta(hours=4)


def test_future_bar_and_unavailable_revision_cannot_change_decision():
    original = bars()
    expected = evaluate(original, "EURUSD", AT, history_complete=True)
    revised = original[-1].model_copy(
        update={"revision": 2, "available_at": AT + timedelta(seconds=1)}
    )
    future = original[-1].model_copy(
        update={"close_at": AT + timedelta(minutes=15), "available_at": AT + timedelta(minutes=15)}
    )
    assert evaluate([*original, revised, future], "EURUSD", AT, history_complete=True) == expected


def test_revision_never_refreshes_signal_expiry():
    original = bars()
    revised = original[-1].model_copy(
        update={"revision": 2, "available_at": AT + timedelta(seconds=59)}
    )
    result = evaluate(
        [*original, revised], "EURUSD", AT + timedelta(seconds=60), history_complete=True
    )
    assert result["reason"] == "SIGNAL_EXPIRED"


def test_missing_history_and_position_hold():
    assert evaluate(bars(), "EURUSD", AT)["reason"] == "DATASET_COMPLETENESS_UNVERIFIED"
    assert (
        evaluate(bars(), "EURUSD", AT, history_complete=True, position_open=True)["reason"]
        == "POSITION_ALREADY_OPEN"
    )
    assert evaluate(bars()[1:], "EURUSD", AT, history_complete=True)["reason"] == "INDICATOR_WARMUP"


def test_duplicate_revision_conflict_rejected():
    original = bars()
    conflict = original[-1].model_copy(update={"close": Decimal("1.01")})
    with pytest.raises(ValueError, match="conflicting"):
        evaluate([*original, conflict], "EURUSD", AT, history_complete=True)


def test_strict_breakout_and_deterministic_input_order():
    original = bars()
    expected = evaluate(original, "EURUSD", AT, history_complete=True)
    assert evaluate(list(reversed(original)), "EURUSD", AT, history_complete=True) == expected
    original[-1] = original[-1].model_copy(update={"close": Decimal("1.01")})
    assert evaluate(original, "EURUSD", AT, history_complete=True)["reason"] == "NO_BREAKOUT"


def test_mirrored_market_produces_short_candidate():
    pivot = Decimal("2.1")
    mirrored = [
        b.model_copy(
            update={
                "open": pivot - b.open,
                "close": pivot - b.close,
                "high": pivot - b.low,
                "low": pivot - b.high,
            }
        )
        for b in bars()
    ]
    result = evaluate(mirrored, "EURUSD", AT, history_complete=True)
    assert result["side"] == "SELL"
    assert Decimal(result["stop_distance"]) / Decimal("0.00001") % 1 == 0


def test_session_and_incomplete_revision_history():
    assert (
        evaluate(bars(), "EURUSD", AT.replace(hour=23, minute=45), history_complete=True)["reason"]
        == "OUTSIDE_PREREGISTERED_SESSION"
    )
    original = bars()
    original[-1] = original[-1].model_copy(update={"revision": 2})
    with pytest.raises(ValueError, match="history incomplete"):
        evaluate(original, "EURUSD", AT, history_complete=True)
