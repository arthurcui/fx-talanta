"""Bounded timestamp corroboration using synthetic SDK clocks only."""

from datetime import UTC, datetime, timedelta

import pytest
from test_connected_inputs import NOW, SDK, binding, capture, context

from fx_talanta.connected_shadow.inputs import canonical_hash, normalize
from fx_talanta.observer.mt5 import ObservationFailure
from scripts.connected_capture import corroborate, derived_binding, run, safe_reason


class Timer:
    def __init__(self):
        self.elapsed = 0

    def monotonic(self):
        return self.elapsed

    def now(self):
        return NOW + int(self.elapsed * 1000)

    def sleep(self, seconds):
        self.elapsed += seconds


class AdvancingSDK(SDK):
    def __init__(self, timer):
        super().__init__()
        self.timer = timer
        self.frozen = set()

    def symbol_info_tick(self, symbol):
        tick = super().symbol_info_tick(symbol)
        if symbol not in self.frozen:
            tick.time_msc += int(self.timer.elapsed * 1000)
        return tick


def check(sdk, timer, **kwargs):
    return corroborate(
        sdk,
        binding(),
        15,
        process_check=lambda _: [1],
        now_ms=timer.now,
        monotonic=timer.monotonic,
        sleep=timer.sleep,
        **kwargs,
    )


def test_same_offset_corroboration_is_bounded_and_explicitly_provisional():
    timer = Timer()
    report = check(AdvancingSDK(timer), timer)
    assert report["status"] == "CORROBORATED"
    assert 0 < report["sampling_seconds"] <= 5
    assert not report["timestamp_mapping_qualified"] and not report["entry_eligibility"]
    old = binding()
    at = datetime.fromtimestamp(timer.now() / 1000, UTC)
    result = derived_binding(old, report, at)
    assert result.sdk_time_offset_seconds == old.sdk_time_offset_seconds
    assert result.time_policy_until - result.time_policy_from == timedelta(minutes=15)
    assert result.time_policy_evidence.startswith("PROVISIONAL_CONSISTENCY_ONLY_NOT_BROKER_UTC:")
    assert old.time_policy_from is None  # immutable original was not edited


def test_expired_original_preflight_and_recent_tick_decode_use_separate_scopes():
    from fx_talanta.observer.contracts import Binding
    from fx_talanta.observer.mt5 import SDKClock

    values = binding().model_dump(mode="json")
    values.update(
        time_policy_from="2025-01-01T00:00:00Z",
        time_policy_until="2025-01-01T00:15:00Z",
        sdk_time_offset_seconds=7200,
        time_policy_evidence="Synthetic expired historical mapping",
    )
    original = Binding.model_validate(values)
    timer = Timer()
    sdk = AdvancingSDK(timer)
    sdk.tick_offset = 7200000
    report = corroborate(
        sdk,
        original,
        15,
        process_check=lambda _: [1],
        now_ms=timer.now,
        monotonic=timer.monotonic,
        sleep=timer.sleep,
    )
    assert report["status"] == "CORROBORATED"
    at = datetime.fromtimestamp((timer.now() + 1000) / 1000, UTC)
    with pytest.raises(ObservationFailure):
        SDKClock(original).check(at)
    derived = derived_binding(original, report, at)
    for row in report["rows"]:
        adjusted = SDKClock(derived).decode(row["raw_tick_ms"] / 1000)
        assert int(adjusted.timestamp() * 1000) == row["adjusted_tick_ms"]
        assert adjusted < at  # normal arrival age must not cause policy expiry
    assert derived.time_policy_until - derived.time_policy_from == timedelta(minutes=15)
    assert derived.sdk_time_offset_seconds == original.sdk_time_offset_seconds == 7200
    assert original.model_dump(mode="json") == values
    assert not report["timestamp_mapping_qualified"]


@pytest.mark.parametrize("frozen", [{"EURUSD"}, {"USDJPY"}, {"EURUSD", "USDJPY"}])
def test_each_symbol_must_advance_without_retry(frozen):
    timer = Timer()
    sdk = AdvancingSDK(timer)
    sdk.frozen = frozen
    report = check(sdk, timer)
    assert report["status"] == "BLOCKED"
    assert report["reason"] in {"ADVANCING_TICKS_NOT_OBSERVED", "PINNED_MAPPING_NOT_CORROBORATED"}
    assert timer.elapsed <= 5
    assert sdk.calls.count("initialize") == 1 and sdk.calls.count("shutdown") == 1
    with pytest.raises(ValueError):
        derived_binding(binding(), report, datetime.fromtimestamp(NOW / 1000, UTC))


@pytest.mark.parametrize("offset", [-6000, 1000])
def test_stale_or_future_ticks_cannot_create_new_clock_policy(offset):
    timer = Timer()
    sdk = AdvancingSDK(timer)
    sdk.tick_offset = offset
    report = check(sdk, timer)
    assert report["status"] == "BLOCKED"
    assert report["reason"] == "PINNED_MAPPING_NOT_CORROBORATED"
    assert report["rows"]  # failed observation is preserved
    assert timer.elapsed == 0


def test_original_expiry_reason_is_preserved_and_provisional_capture_cannot_promote():
    from fx_talanta.observer.contracts import invalid

    assert (
        safe_reason(ObservationFailure(invalid("CLOCK_POLICY_EXPIRED"))) == "CLOCK_POLICY_EXPIRED"
    )
    raw = capture()
    raw["timestamp_mapping_qualified"] = False
    raw["capture_sha256"] = canonical_hash({k: v for k, v in raw.items() if k != "capture_sha256"})
    result = normalize(raw, symbol="EURUSD", side="BUY", context=context(raw))
    assert result.snapshot is None and result.missing == ("TIMESTAMP_MAPPING_UNQUALIFIED",)


def test_disabled_trading_and_identity_checks_continue_during_sampling():
    timer = Timer()
    sdk = AdvancingSDK(timer)
    sdk.mutate = True
    report = check(sdk, timer)
    assert report["status"] == "BLOCKED" and report["reason"] == "IDENTITY_MISMATCH"
    assert sdk.calls[-1] == "shutdown"


@pytest.mark.parametrize("passed", [True, False])
def test_one_shot_orchestration_preserves_expired_original_and_never_promotes(
    monkeypatch, tmp_path, passed
):
    import json
    import sys

    from scripts import connected_capture as module

    values = binding().model_dump(mode="json")
    values.update(
        time_policy_from="2025-01-01T00:00:00Z",
        time_policy_until="2025-01-01T00:15:00Z",
        time_policy_evidence="Synthetic historical evidence",
    )
    path = tmp_path / "original.json"
    original = json.dumps(values).encode()
    path.write_bytes(original)
    output = tmp_path / "out"
    output.mkdir()
    timer = Timer()
    preflight = check(AdvancingSDK(timer), timer)
    if not passed:
        preflight.update(status="BLOCKED", reason="ADVANCING_TICKS_NOT_OBSERVED")
    calls = []

    class SyntheticDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls.fromtimestamp((NOW + 1000) / 1000, UTC)

    monkeypatch.setattr(module, "datetime", SyntheticDatetime)
    monkeypatch.setitem(sys.modules, "MetaTrader5", object())
    monkeypatch.setattr(module, "corroborate", lambda *args, **kwargs: preflight)

    def ntp():
        calls.append("NTP")
        return {"passed": True, "error_bound_ms": 10, "synthetic": True}

    def captured(*args, **kwargs):
        calls.append("CAPTURE")
        return capture()

    monkeypatch.setattr(module, "probe", ntp)
    monkeypatch.setattr(module, "capture_once", captured)
    report = run(path, output, "USDCAD")
    assert path.read_bytes() == original and report["original_binding_unchanged"]
    assert not report["timestamp_mapping_qualified"] and not report["entry_eligibility"]
    former = json.loads((output / "original-policy-status.json").read_text())
    assert former["status"] == "CLOCK_POLICY_EXPIRED"
    if passed:
        assert calls == ["NTP", "NTP", "CAPTURE", "NTP"]
        assert report["status"] == "CAPTURED_DATA_HOLD"
        assert "TIMESTAMP_MAPPING_UNQUALIFIED" in report["missing"]["EURUSD"]
        derived = json.loads((output / "derived-binding.private.json").read_text())
        assert derived["sdk_time_offset_seconds"] == values["sdk_time_offset_seconds"]
        assert (output / "private-capture.json").exists()
    else:
        assert calls == ["NTP"] and report["status"] == "BLOCKED"
        assert not (output / "derived-binding.private.json").exists()
