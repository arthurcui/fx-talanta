"""Deterministic comparison orchestration; no terminal, SDK, subprocess or clocks."""

import json
import queue
from types import SimpleNamespace

from fx_talanta.observer.quote_stream import StreamRow
from tools.qualification import compare_quote_stream as comparison


def test_warmup_parent_arrival_boundary_and_shutdown_duration(tmp_path, monkeypatch):
    clock = [0.0]
    stopped = [False]
    binding = SimpleNamespace(symbols=("EURUSD",), sdk_time_offset_seconds=0)
    monkeypatch.setattr(
        comparison, "Binding", SimpleNamespace(model_validate_json=lambda _: binding)
    )
    monkeypatch.setattr(comparison, "SDKClock", lambda _: SimpleNamespace(check=lambda _: None))
    monkeypatch.setattr(comparison, "uptime", lambda: 100000 + int(clock[0] * 1000))
    monkeypatch.setattr(
        comparison,
        "time",
        SimpleNamespace(
            monotonic=lambda: clock[0],
            time=lambda: 1000 + clock[0],
            sleep=lambda _: clock.__setitem__(0, clock[0] + 10),
        ),
    )

    def row(kind, tick):
        return StreamRow("EURUSD", kind, 1, tick, 1.0, 1.1, 100000, 100000, 1000, 0, True)

    class Tail:
        dropped = 0

        def __init__(self, *_):
            self.reads = 0

        def read(self):
            self.reads += 1
            if self.reads == 1:
                return [row("INITIAL", 999000), row("HEARTBEAT", 0)]
            if self.reads == 3:
                return [row("TICK", 999002), row("HEARTBEAT", 0)]
            return []

        def close(self):
            pass

    def polled(tick):
        return {
            "kind": "POLL",
            "read_seconds": 0.01,
            "rows": [
                {
                    "symbol": "EURUSD",
                    "tick_ms": tick,
                    "bid": 1.0,
                    "ask": 1.1,
                    "receipt_ms": 777,
                    "epoch": 999,
                }
            ],
        }

    class Queue:
        def __init__(self):
            self.items = [polled(999000), polled(999002)]

        def get(self, timeout):
            return polled(999001)

        def get_nowait(self):
            if self.items:
                return self.items.pop(0)
            raise queue.Empty

    worker = SimpleNamespace(
        start=lambda: None,
        is_alive=lambda: not stopped[0],
        join=lambda _: clock.__setitem__(0, clock[0] + 3),
        terminate=lambda: None,
    )
    stop = SimpleNamespace(set=lambda: stopped.__setitem__(0, True))
    monkeypatch.setattr(comparison, "Tail", Tail)
    monkeypatch.setattr(
        comparison.mp,
        "get_context",
        lambda _: SimpleNamespace(
            Queue=lambda _: Queue(), Event=lambda: stop, Process=lambda **_: worker
        ),
    )
    private_binding = tmp_path / "binding.json"
    private_binding.write_text("{}")
    output = tmp_path / "result"
    comparison.run(
        SimpleNamespace(
            seconds=10, binding=private_binding, output=output, stream_dir=tmp_path, token="fixture"
        )
    )
    report = json.loads((output / "summary.json").read_text())
    symbol = report["symbols"]["EURUSD"]
    assert report["collection_seconds"] == 10
    assert report["total_seconds_including_shutdown"] == 13
    assert symbol["ea_unique_quotes"] == symbol["poll_unique_quotes"] == 1
    assert symbol["matched_poll_minus_ea_receipt_ms"]["median"] == 0
    events = [json.loads(line) for line in (output / "events.jsonl").read_text().splitlines()]
    poll = next(event for event in events if event["path"] == "POLL")
    assert poll["ingested_ms"] == 100000 and poll["rows"][0]["receipt_ms"] == 777
    assert report["entry_ceiling_seconds"] == 2 and report["qualification"] is False
