import json
import shutil
import sqlite3
import zipfile
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from fx_talanta.research.acquisition import prepare
from fx_talanta.research.input_calendar import InputCalendar, WeekendClosure
from fx_talanta.research.replay import digest
from fx_talanta.research.spool import file_hash
from fx_talanta.research.structural import StructuralRules, StructuralSignal, contiguous
from fx_talanta.research.tick_index import bars_from_ticks, milliseconds


def date(value):
    return datetime.fromisoformat(value).replace(tzinfo=UTC)


def calendar():
    return InputCalendar(
        symbol="EURUSD",
        index_sha256="a" * 64,
        evidence_sha256="b" * 64,
        valid_from=date("2026-05-24"),
        valid_to=date("2026-06-13"),
        closures=(WeekendClosure(start=date("2026-05-29T22:00"), end=date("2026-05-31T22:00")),),
    )


def test_month_join_aggregates_raw_quotes_and_keeps_prior_index(tmp_path):
    files = {}
    for month, rows in {
        "202605": [
            "20260531 230000119,1.1000,1.1001,0",
            "20260531 233000000,1.1004,1.1005,0",
            "20260531 235950162,1.0998,1.0999,0",
        ],
        "202606": [
            "20260601 000004979,1.1002,1.1003,0",
            "20260601 003000000,1.1008,1.1009,0",
            "20260601 005949532,1.1001,1.1002,0",
            "20260601 010000000,1.1003,1.1004,0",
        ],
    }.items():
        files[month] = tmp_path / (month + ".zip")
        with zipfile.ZipFile(files[month], "w") as archive:
            archive.writestr(f"DAT_ASCII_EURUSD_T_{month}.csv", "\n".join(rows))

    def fetch(symbol, month, destination):
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(files[month], destination)
        return dict(symbol=symbol, month=month, sha256=file_hash(destination))

    root = tmp_path / "history"
    old = root / digest(
        dict(
            symbol="EURUSD",
            start=date("2026-06-01").isoformat(),
            end=date("2026-06-02").isoformat(),
            warm_start=date("2026-05-18").isoformat(),
            version=1,
        )
    )
    old.mkdir(parents=True)
    (old / "ticks.sqlite").write_bytes(b"retained original index")
    (old / "prepared.json").write_text(
        json.dumps(dict(index_sha256=file_hash(old / "ticks.sqlite"), retained="original"))
    )
    prior = file_hash(old / "prepared.json")
    path, report = prepare(
        root, "EURUSD", date("2026-06-01"), date("2026-06-02"), 53, lambda _: None, fetch=fetch
    )
    db = sqlite3.connect(path / "ticks.sqlite")
    try:
        meta = json.loads(db.execute("SELECT value FROM metadata").fetchone()[0])
    finally:
        db.close()
    h1 = {datetime.fromisoformat(b["close_at"]): b for b in meta["bars"] if b["timeframe"] == "H1"}
    a, b = h1[date("2026-06-01T05:00")], h1[date("2026-06-01T06:00")]
    assert [a[k] for k in ("open", "high", "low", "close")] == [
        "1.1000",
        "1.1004",
        "1.0998",
        "1.0998",
    ]
    assert [b[k] for k in ("open", "high", "low", "close")] == [
        "1.1002",
        "1.1008",
        "1.1001",
        "1.1001",
    ]
    m15 = {datetime.fromisoformat(b["close_at"]) for b in meta["bars"] if b["timeframe"] == "M15"}
    assert {date("2026-06-01T05:00"), date("2026-06-01T05:15")} <= m15
    assert report["preparation_version"] == 2
    assert path != old
    assert file_hash(old / "prepared.json") == prior
    assert (
        prepare(
            root, "EURUSD", date("2026-06-01"), date("2026-06-02"), 53, lambda _: None, fetch=fetch
        )[1]
        == report
    )


def test_declared_window_partial_edges_no_fill_and_tie_order():
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE ticks(seq INTEGER,at_ms INTEGER,bid TEXT)")
    data = [
        ("2026-06-01T04:59", "1.1"),
        ("2026-06-01T05:00", "1.2"),
        ("2026-06-01T05:00", "1.3"),
        ("2026-06-01T05:15", "1.4"),
        ("2026-06-01T05:50", "1.5"),
    ]
    db.executemany(
        "INSERT INTO ticks VALUES(?,?,?)",
        [(i, milliseconds(date(t)), v) for i, (t, v) in enumerate(data)],
    )
    bars, receipt = bars_from_ticks(
        db, "EURUSD", date("2026-06-01T04:58"), date("2026-06-01T05:51")
    )
    db.close()
    assert [(b["timeframe"], datetime.fromisoformat(b["close_at"])) for b in bars] == [
        ("M15", date("2026-06-01T05:15")),
        ("M15", date("2026-06-01T05:30")),
    ]
    assert (bars[0]["open"], bars[0]["close"]) == ("1.2", "1.3")
    assert len(receipt["partial_buckets"]) == 4
    assert receipt["quote_rows"] == 5 and not receipt["forward_fill"]


def test_calendar_only_bridges_exact_reviewed_weekend_and_never_weekday_gap():
    c = calendar()
    bars = [
        SimpleNamespace(close_at=x)
        for x in [date("2026-05-29T22:00"), date("2026-05-31T23:00"), date("2026-06-01T00:00")]
    ]
    assert not contiguous(bars, 60)
    assert contiguous(bars, 60, c)
    assert not contiguous(bars[::2], 60, c)  # Lost the reopening bar.
    assert not contiguous([*bars, SimpleNamespace(close_at=date("2026-06-01T02:00"))], 60, c)
    assert not c.permits(date("2026-06-05T22:00"), date("2026-06-07T23:00"), 60)
    with pytest.raises(ValueError):
        WeekendClosure(start=date("2026-05-29T21:00"), end=date("2026-05-31T21:00"))
    with pytest.raises(ValueError):
        WeekendClosure(start=date("2026-06-01T22:00"), end=date("2026-06-03T22:00"))


def test_weekend_history_is_causal_and_missing_intraday_inputs_still_block():
    from test_structural_research import history

    # Move the existing full causal fixture to Monday morning. Its real trading
    # observations before Sunday reopen belong to Friday, with no invented bars.
    shift = timedelta(days=-2)
    rows = []
    for bar in history():
        close = bar.close_at + shift
        if close <= date("2026-05-31T22:00"):
            close -= timedelta(days=2)
        rows.append(
            bar.model_copy(
                update={"close_at": close, "available_at": close + timedelta(milliseconds=250)}
            )
        )
    cutoff = date("2026-06-01T08:00") + timedelta(milliseconds=250)
    strict = StructuralSignal(StructuralRules())
    assert (
        strict(rows, "EURUSD", cutoff, history_complete=True)["reason"] == "GAPPED_OR_STALE_INPUTS"
    )
    signal = StructuralSignal(StructuralRules(), calendar=calendar())
    expected = signal(rows, "EURUSD", cutoff, history_complete=True)
    assert expected["reason"] != "GAPPED_OR_STALE_INPUTS"
    past = [b for b in rows if b.available_at <= cutoff]
    assert (
        StructuralSignal(StructuralRules(), calendar=calendar())(
            past, "EURUSD", cutoff, history_complete=True
        )
        == expected
    )
    missing = [
        b for b in rows if not (b.timeframe == "H1" and b.close_at == date("2026-06-01T07:00"))
    ]
    assert (
        StructuralSignal(StructuralRules(), calendar=calendar())(
            missing, "EURUSD", cutoff, history_complete=True
        )["reason"]
        == "GAPPED_OR_STALE_INPUTS"
    )


def test_calendar_cannot_bind_a_different_index_or_escape_development():
    from test_structural_research import scenario

    from fx_talanta.dashboard.indexed_research import IndexedBundle

    _, experiment = scenario()
    kwargs = dict(
        index_file="ticks.sqlite",
        index_sha256="a" * 64,
        experiment=experiment,
        acquired_history=True,
        development_only=True,
        input_calendar=calendar(),
    )
    assert IndexedBundle(**kwargs).input_calendar == calendar()
    with pytest.raises(ValueError, match="exact development index"):
        IndexedBundle(**dict(kwargs, index_sha256="c" * 64))
    with pytest.raises(ValueError, match="exact development index"):
        IndexedBundle(**dict(kwargs, development_only=False))
