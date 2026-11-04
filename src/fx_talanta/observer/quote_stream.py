"""Read-only local EA stream decoder; never an execution or entry authority."""

import csv
import math
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class StreamRow:
    symbol: str
    kind: str
    sequence: int
    tick_ms: int
    bid: float
    ask: float
    captured_ms: int
    emitted_ms: int
    utc_seconds: int
    dropped: int
    connected: bool


def decode(line: str, token: str, symbol: str) -> StreamRow:
    fields = next(csv.reader([line]))
    if len(fields) != 13 or fields[:3] != ["quote-stream/1", token, symbol]:
        raise ValueError("stream binding/schema mismatch")
    if fields[3] not in {"INITIAL", "TICK", "HEARTBEAT", "STOP", "STOP_INCOMPLETE"}:
        raise ValueError("unknown stream event")
    row = StreamRow(
        symbol,
        fields[3],
        int(fields[4]),
        int(fields[5]),
        float(fields[6]),
        float(fields[7]),
        int(fields[8]),
        int(fields[9]),
        int(fields[10]),
        int(fields[11]),
        fields[12] == "1",
    )
    if (
        row.sequence < 1
        or row.captured_ms < 0
        or row.emitted_ms < row.captured_ms
        or row.dropped < 0
        or fields[12] not in {"0", "1"}
    ):
        raise ValueError("invalid stream counters")
    if row.kind in {"INITIAL", "TICK"} and (
        row.tick_ms <= 0
        or not math.isfinite(row.bid)
        or not math.isfinite(row.ask)
        or row.bid <= 0
        or row.ask < row.bid
    ):
        raise ValueError("invalid quote")
    return row


class Tail:
    """Bounded partial-line reader; reject replacement, truncation and sequence loss."""

    def __init__(self, path: Path, token: str, symbol: str):
        self.path, self.token, self.symbol = path, token, symbol
        self.file = path.open("rb")
        self.identity = path.stat().st_ino
        self.pending = b""
        self.sequence = 0
        self.dropped = 0

    def read(self) -> list[StreamRow]:
        stat = self.path.stat()
        if stat.st_ino != self.identity or stat.st_size < self.file.tell():
            raise ValueError("stream replaced/truncated")
        self.pending += self.file.read(65536)
        parts = self.pending.split(b"\n")
        self.pending = parts.pop()
        if len(self.pending) > 4096:
            raise ValueError("oversized stream line")
        rows = []
        for part in parts:
            if len(part) > 4096:
                raise ValueError("oversized stream line")
            row = decode(part.decode("utf-8").rstrip("\r"), self.token, self.symbol)
            if row.sequence != self.sequence + 1 or row.dropped < self.dropped:
                raise ValueError("stream sequence/drop counter discontinuity")
            self.sequence, self.dropped = row.sequence, row.dropped
            rows.append(row)
        return rows

    def close(self):
        self.file.close()


def quote_age(tick_ms: int, receipt_epoch: float, offset_seconds: int) -> float:
    return receipt_epoch - (tick_ms / 1000 - offset_seconds)


def entry_fresh(age: float | None) -> bool:
    # Diagnostic metric only. The real risk/entry authority remains unchanged.
    return age is not None and math.isfinite(age) and 0 <= age <= 2


def distribution(values):
    values = sorted(values)
    if not values:
        return {"count": 0}
    return {
        "count": len(values),
        "median": values[len(values) // 2],
        "p95": values[math.ceil(len(values) * 0.95) - 1],
        "max": values[-1],
        "min": values[0],
    }
