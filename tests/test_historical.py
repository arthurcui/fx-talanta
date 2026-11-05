import zipfile
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from fx_talanta.research.historical import import_zip, parse_row
from fx_talanta.research.replay import Dataset, run
from tools.fixtures.b01_replay import scenario

START = datetime(2025, 1, 16, 12, tzinfo=UTC)


def archive(tmp_path, lines, symbol="EURUSD"):
    target = tmp_path / "ticks.zip"
    with zipfile.ZipFile(target, "w") as z:
        z.writestr(f"DAT_ASCII_{symbol}_T_202501.csv", "\n".join(lines))
    return target


@pytest.mark.parametrize("date", ["20250116", "20250716"])
def test_source_timezone_is_fixed_est_even_in_summer(date):
    at, bid, ask = parse_row([date + " 070001250", "1.1", "1.1001", "0"])
    assert (at.hour, at.second, at.microsecond) == (12, 1, 250000)
    assert bid == Decimal("1.1") and ask == Decimal("1.1001")


@pytest.mark.parametrize(
    "row",
    [
        ["20250116 070000", "1", "2", "0"],
        ["20250116 070000000", "2", "1", "0"],
        ["20250116 070000000", "NaN", "2", "0"],
        ["20250116 070000000", "1", "2", "-1"],
    ],
)
def test_invalid_quotes_fail_instead_of_being_dropped(row):
    with pytest.raises(ValueError):
        parse_row(row)


def test_import_keeps_distinct_and_identical_timestamp_ties(tmp_path):
    path = archive(
        tmp_path,
        [
            "20250116 060000000,1.1,1.1001,0",
            "20250116 070000000,1.101,1.1011,0",
            "20250116 070000000,1.102,1.1021,0",
            "20250116 070000000,1.102,1.1021,0",
            "20250116 080000000,1.103,1.1031,0",
        ],
    )
    data, report = import_zip(path, "EURUSD", START, START + timedelta(hours=1))
    assert len(data.events) == 3
    assert [e.source_sequence for e in data.events] == [1, 2, 3]
    assert all(e.available_at == START + timedelta(milliseconds=250) for e in data.events)
    assert all(e.market.quotes[0].at == START for e in data.events)
    assert report["timestamp_ties"] == 2
    assert report["exact_duplicate_rows_retained"] == 1
    assert not data.history_complete
    assert all(not e.market.calendar_ok and not e.market.news_ok for e in data.events)
    assert all(b.close_at <= START + timedelta(hours=1) for b in data.bars)
    closed_h1 = next(b for b in data.bars if b.timeframe == "H1" and b.close_at == START)
    assert closed_h1.close == Decimal("1.1")  # 12:00 ticks belong to the next bar.
    assert closed_h1.available_at == START + timedelta(milliseconds=250)


def test_jpy_conversion_and_research_assumptions_remain_explicit(tmp_path):
    path = archive(tmp_path, ["20250116 070000000,150,150.01,0"], "USDJPY")
    data, report = import_zip(path, "USDJPY", START, START + timedelta(hours=1), assume_inputs=True)
    assert data.events[0].market.conversion["JPY"] == Decimal(1) / Decimal("150.01")
    assert data.history_complete and data.events[0].market.news_ok
    assert report["assumptions"]["research_inputs_assumed"]
    assert not report["assumptions"]["calendar_news_qualified"]
    assert data.provenance == "HISTORICAL_UNQUALIFIED"


def test_out_of_order_source_is_not_silently_sorted(tmp_path):
    path = archive(tmp_path, ["20250116 070001000,1,1.1,0", "20250116 070000000,1,1.1,0"])
    with pytest.raises(ValueError, match="backwards"):
        import_zip(path, "EURUSD", START, START + timedelta(hours=1))


def test_replay_processes_every_sequenced_equal_time_quote():
    data, experiment = scenario()
    original = data.events[2]
    first = original.model_copy(update={"source_sequence": 1})
    second = original.model_copy(update={"source_sequence": 2})
    revised = Dataset.model_validate(
        {**data.model_dump(), "events": data.events[:2] + (first, second) + data.events[3:]}
    )
    result, _ = run(revised, experiment, "training")
    assert len(result["equity_samples"]) == len(revised.events)
    assert len([d for d in result["deals"] if d["action"] == "ENTER"]) == 1
    assert result["fully_settled"]
    with pytest.raises(ValueError, match="source sequences"):
        Dataset.model_validate(
            {**data.model_dump(), "events": data.events[:2] + (second, first) + data.events[3:]}
        )


def test_unsequenced_ties_still_fail():
    data, _ = scenario()
    with pytest.raises(ValueError, match="source sequences"):
        Dataset.model_validate({**data.model_dump(), "events": (data.events[0],) + data.events})
