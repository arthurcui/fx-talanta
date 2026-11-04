import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import test_mt5
from test_mt5 import NOW, FakeSDK

spec = importlib.util.spec_from_file_location(
    "capture_forex_diagnostics",
    Path(__file__).resolve().parents[1] / "tools/qualification/capture_forex_diagnostics.py",
)
diagnostic = importlib.util.module_from_spec(spec)
spec.loader.exec_module(diagnostic)


@pytest.fixture
def demo_binding():
    return test_mt5.demo_binding.__wrapped__()


@pytest.mark.parametrize("history", [False, True])
def test_diagnostic_isolates_history_and_excludes_prices(
    monkeypatch, tmp_path, demo_binding, history
):
    module = FakeSDK()
    module.COPY_TICKS_ALL = 0
    calls = []

    def ticks(symbol, start, count, flags):
        calls.append(symbol)
        assert history and count == 5000 and flags == 0
        return [{"time_msc": int(NOW.timestamp() * 1000)}]

    module.copy_ticks_from = ticks
    monkeypatch.setitem(sys.modules, "MetaTrader5", module)
    elapsed = [0]
    monkeypatch.setattr(
        diagnostic,
        "time",
        SimpleNamespace(
            monotonic=lambda: elapsed[0],
            sleep=lambda seconds: elapsed.__setitem__(0, elapsed[0] + seconds),
        ),
    )
    binding = tmp_path / "binding.json"
    binding.write_text(demo_binding.model_dump_json())
    diagnostic.capture(binding, tmp_path, 3, history)
    rows = [json.loads(line) for line in (tmp_path / "samples.jsonl").read_text().splitlines()]
    assert len(rows) == (1 if history else 3)
    assert calls == (list(demo_binding.symbols) if history else [])
    assert all(row["connected"] for row in rows)
    assert all("bid" not in tick and "ask" not in tick for row in rows for tick in row["ticks"])
    assert "account" not in (tmp_path / "samples.jsonl").read_text()
    assert module.calls[-1] == ("shutdown",)


def test_identity_change_aborts_capture(monkeypatch, tmp_path, demo_binding):
    module = FakeSDK()
    module.switch_during_quotes = True
    monkeypatch.setitem(sys.modules, "MetaTrader5", module)
    binding = tmp_path / "binding.json"
    binding.write_text(demo_binding.model_dump_json())
    with pytest.raises(Exception, match="IDENTITY_MISMATCH"):
        diagnostic.capture(binding, tmp_path, 3)
    assert not (tmp_path / "samples.jsonl").read_text()
    assert module.calls[-1] == ("shutdown",)


def test_worker_failure_redacts_native_details(monkeypatch, tmp_path):
    def failed(*args):
        raise ValueError("private account diagnostics")

    monkeypatch.setattr(diagnostic, "capture", failed)
    diagnostic.worker("unused", tmp_path, 60, False)
    text = (tmp_path / "worker-result.json").read_text()
    assert json.loads(text)["status"] == "FAILED"
    assert "private account" not in text
