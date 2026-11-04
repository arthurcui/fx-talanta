from pathlib import Path

import pytest

from fx_talanta.observer.quote_stream import Tail, decode, entry_fresh, quote_age


def row(seq=1, kind="TICK", **changes):
    fields = [
        "quote-stream/1",
        "test-token",
        "EURUSD.",
        kind,
        str(seq),
        "1793736000000",
        "1.1",
        "1.1001",
        "100",
        "125",
        "1793728800",
        "0",
        "1",
    ]
    for key, value in changes.items():
        fields[int(key.removeprefix("f"))] = str(value)
    return ",".join(fields) + "\r\n"


def test_partial_lines_are_not_published(tmp_path):
    path = tmp_path / "stream.csv"
    payload = row().encode()
    path.write_bytes(payload[:-3])
    tail = Tail(path, "test-token", "EURUSD.")
    try:
        assert tail.read() == []
        with path.open("ab") as writer:
            writer.write(payload[-3:])
        assert tail.read()[0].sequence == 1
        assert tail.read() == []
    finally:
        tail.close()


@pytest.mark.parametrize(
    "change",
    [
        {"f0": "other-schema"},
        {"f1": "other-run"},
        {"f2": "USDJPY."},
        {"f6": "nan"},
        {"f7": "inf"},
        {"f7": "1.0"},
        {"f9": "99"},
        {"f11": "-1"},
        {"f12": "yes"},
        {"f5": "0"},
    ],
)
def test_bad_binding_quote_or_counters_are_rejected(change):
    with pytest.raises(ValueError):
        decode(row(**change), "test-token", "EURUSD.")


def test_sequence_gap_and_truncation_are_rejected(tmp_path):
    path = tmp_path / "stream.csv"
    path.write_text(row())
    tail = Tail(path, "test-token", "EURUSD.")
    try:
        tail.read()
        with path.open("a") as writer:
            writer.write(row(seq=3))
        with pytest.raises(ValueError, match="sequence"):
            tail.read()
        path.write_bytes(b"")
        with pytest.raises(ValueError, match="truncated"):
            tail.read()
    finally:
        tail.close()


def test_heartbeat_is_not_a_quote():
    value = decode(row(kind="HEARTBEAT", f5=0, f6=0, f7=0), "test-token", "EURUSD.")
    assert value.kind == "HEARTBEAT" and value.tick_ms == 0


def test_original_tick_clock_and_entry_ceiling_are_preserved():
    assert quote_age(1793736000000, 1793728802, 7200) == 2
    assert entry_fresh(2)
    assert not entry_fresh(2.000001)
    assert not entry_fresh(-0.001)
    assert not entry_fresh(None)
    assert not entry_fresh(float("nan"))


def test_publisher_contains_no_trading_or_network_interface():
    source = (Path(__file__).parents[1] / "mql5/readonly/QuoteStream.mq5").read_text()
    for forbidden in ("OrderSend", "CTrade", "WebRequest", "Socket", "#import"):
        assert forbidden not in source
    assert "!TerminalInfoInteger(TERMINAL_TRADE_ALLOWED)" in source
    assert "ACCOUNT_TRADE_MODE_DEMO" in source


def test_incomplete_stop_is_explicit_and_not_a_quote(tmp_path):
    path = tmp_path / "stream.csv"
    path.write_text(row(kind="STOP_INCOMPLETE", f5=0, f6=0, f7=0, f11=7))
    tail = Tail(path, "test-token", "EURUSD.")
    try:
        stopped = tail.read()[0]
        assert stopped.kind == "STOP_INCOMPLETE"
        assert stopped.dropped == 7
        assert stopped.tick_ms == 0
    finally:
        tail.close()
