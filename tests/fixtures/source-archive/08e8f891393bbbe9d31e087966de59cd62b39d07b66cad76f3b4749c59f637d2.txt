"""One supervised, no-order broker capture with provisional timestamp consistency.

The original binding is never edited. Advancing ticks corroborate its existing
offset only; neither ticks nor unauthenticated NTP prove broker-authoritative UTC.
Run this child with an external 60-second deadline. All raw artifacts are private.
"""

import argparse
import hashlib
import json
import math
import re
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fx_talanta.acceptance.clock_probe import probe
from fx_talanta.acceptance.probe import ProbeSDK, running_pids, write_json
from fx_talanta.connected_shadow.inputs import canonical_hash, capture_once, normalize
from fx_talanta.observer.contracts import Binding
from fx_talanta.observer.mt5 import ObservationFailure, SDKClock, validate_terminal

ROOT = Path(__file__).resolve().parents[1]


def safe_reason(error):
    value = getattr(error, "reason", "")
    if getattr(value, "diagnostic", None) is not None:
        value = value.diagnostic.rule
    return (
        value
        if isinstance(value, str) and re.fullmatch(r"[A-Z_]{1,64}", value)
        else type(error).__name__
    )


def corroborate(
    module,
    binding,
    host_bound_ms,
    *,
    process_check=running_pids,
    now_ms=lambda: time.time_ns() // 1_000_000,
    monotonic=time.monotonic,
    sleep=time.sleep,
    emit=lambda row: None,
):
    """One at-most-five-second sampling attempt using the unchanged pinned offset."""
    binding.require_permissions()
    if binding.source != "MT5" or [s[:6] for s in binding.symbols] != ["EURUSD", "USDJPY"]:
        raise ValueError("two pinned forex demo symbols required")
    if module.__version__ != binding.sdk_version:
        raise ObservationFailure("SDK_MISMATCH")
    if type(host_bound_ms) is not int or not 0 <= host_bound_ms <= 100:
        raise ObservationFailure("CLOCK_UNVERIFIED")
    pids = process_check(binding)
    if len(pids) != 1:
        raise ObservationFailure("RUNNING_TERMINAL_REQUIRED")
    api = ProbeSDK(module, binding.symbols)
    rows, reason = [], None
    start = end = None
    try:
        if process_check(binding) != pids:
            raise ObservationFailure("TERMINAL_PROCESS_CHANGED")
        if not api.call("initialize", binding.terminal_path, timeout=5000):
            raise ObservationFailure("DISCONNECTED")
        terminal, _ = validate_terminal(api, binding)
        if getattr(terminal, "trade_allowed", None) is not False:
            raise ObservationFailure("ALGORITHMIC_TRADING_MUST_BE_DISABLED")
        start, wall_start = monotonic(), now_ms()
        for _ in range(20):
            if monotonic() - start >= 5:
                break
            if process_check(binding) != pids:
                raise ObservationFailure("TERMINAL_PROCESS_CHANGED")
            for symbol in binding.symbols:
                terminal, _ = validate_terminal(api, binding)
                if getattr(terminal, "trade_allowed", None) is not False:
                    raise ObservationFailure("ALGORITHMIC_TRADING_MUST_BE_DISABLED")
                info, tick = api.call("symbol_info", symbol), api.call("symbol_info_tick", symbol)
                if not info.visible:
                    raise ObservationFailure("SYMBOL_NOT_VISIBLE")
                if (
                    not all(math.isfinite(x) and x > 0 for x in (tick.time_msc, tick.bid, tick.ask))
                    or tick.ask < tick.bid
                ):
                    raise ObservationFailure("INVALID_QUOTE")
                received, elapsed = now_ms(), monotonic() - start
                row = dict(
                    symbol=symbol[:6],
                    raw_tick_ms=int(tick.time_msc),
                    received_at_ms=received,
                    adjusted_tick_ms=int(tick.time_msc) - binding.sdk_time_offset_seconds * 1000,
                )
                row["age_ms"] = received - row["adjusted_tick_ms"]
                rows.append(row)
                emit(row)
                if abs(received - wall_start - elapsed * 1000) > 5:
                    raise ObservationFailure("HOST_CLOCK_CHANGED")
                if not host_bound_ms <= row["age_ms"] <= 5000 - host_bound_ms:
                    raise ObservationFailure("PINNED_MAPPING_NOT_CORROBORATED")
                if elapsed > 5:
                    raise ObservationFailure("PREFLIGHT_DEADLINE")
            if all(
                len({r["raw_tick_ms"] for r in rows if r["symbol"] == s}) >= 2
                for s in ("EURUSD", "USDJPY")
            ):
                break
            sleep(min(0.25, max(0, 5 - (monotonic() - start))))
        end = monotonic()
        terminal, _ = validate_terminal(api, binding)
        if getattr(terminal, "trade_allowed", None) is not False:
            raise ObservationFailure("ALGORITHMIC_TRADING_MUST_BE_DISABLED")
        if process_check(binding) != pids:
            raise ObservationFailure("TERMINAL_PROCESS_CHANGED")
        for symbol in ("EURUSD", "USDJPY"):
            times = [r["raw_tick_ms"] for r in rows if r["symbol"] == symbol]
            if len(set(times)) < 2 or any(b < a for a, b in zip(times, times[1:], strict=False)):
                raise ObservationFailure("ADVANCING_TICKS_NOT_OBSERVED")
    except Exception as error:
        reason = safe_reason(error)
    finally:
        api.call("shutdown")
    return dict(
        status="CORROBORATED" if reason is None else "BLOCKED",
        reason=reason,
        existing_offset_seconds=binding.sdk_time_offset_seconds,
        rows=rows,
        sampling_seconds=None if start is None or end is None else end - start,
        sdk_calls=dict(api.calls),
        host_error_bound_ms=host_bound_ms,
        timestamp_mapping_qualified=False,
        entry_eligibility=False,
        scope=(
            "Provisional consistency check; no inference/change of pinned offset "
            "or broker UTC qualification"
        ),
    )


def derived_binding(original, report, at):
    if (
        report["status"] != "CORROBORATED"
        or report["existing_offset_seconds"] != original.sdk_time_offset_seconds
    ):
        raise ValueError("successful unchanged-offset consistency evidence required")
    # A tick can legitimately predate the instant we finish corroboration. Start
    # this NEW provisional interval at the beginning of the already-checked
    # five-second observation window, not after its ticks. This does not change
    # the pinned offset or age: all rows still face the same strict freshness
    # checks, and the total interval remains exactly 15 minutes.
    rows = report["rows"]
    if not rows or max(r["received_at_ms"] for r in rows) > int(at.timestamp() * 1000):
        raise ValueError("preflight receipt times must precede binding creation")
    window_start = datetime.fromtimestamp(min(r["received_at_ms"] for r in rows) / 1000, UTC)
    window_start -= timedelta(seconds=5)
    window_end = window_start + timedelta(minutes=15)
    if not window_start <= at < window_end:
        raise ValueError("provisional observation interval is no longer current")
    evidence = canonical_hash(report)
    values = original.model_dump(mode="json")
    values.update(
        time_policy_from=window_start.isoformat(),
        time_policy_until=window_end.isoformat(),
        time_policy_evidence="PROVISIONAL_CONSISTENCY_ONLY_NOT_BROKER_UTC:" + evidence,
    )
    return Binding.model_validate(values)


def run(binding_path, output, conversion_symbol=None):
    original_bytes = binding_path.read_bytes()
    original = Binding.model_validate_json(original_bytes)
    report = dict(
        status="BLOCKED",
        phase="ORIGINAL_POLICY",
        execution_enabled=False,
        entry_eligibility=False,
        timestamp_mapping_qualified=False,
        campaign_started=False,
        original_binding_sha256=hashlib.sha256(original_bytes).hexdigest(),
    )
    # Preserve the former policy's actual refusal rather than silently replacing it.
    try:
        SDKClock(original).check(datetime.now(UTC))
        former = "CURRENT"
    except ObservationFailure as error:
        former = safe_reason(error)
    write_json(
        output / "original-policy-status.json",
        dict(
            status=former,
            original_binding_sha256=report["original_binding_sha256"],
            time_policy_from=original.time_policy_from.isoformat()
            if original.time_policy_from
            else None,
            time_policy_until=original.time_policy_until.isoformat()
            if original.time_policy_until
            else None,
            offset_seconds=original.sdk_time_offset_seconds,
        ),
    )
    try:
        report["phase"] = "CLOCK_BEFORE"
        before = probe()
        write_json(output / "clock-before.json", before)
        if not before["passed"] or before["error_bound_ms"] > 95:
            raise ObservationFailure("CLOCK_UNVERIFIED")
        import MetaTrader5 as mt5

        with (output / "private-preflight.jsonl").open(
            "x", encoding="utf-8", newline="\n"
        ) as stream:

            def emit(row):
                stream.write(json.dumps(row, allow_nan=False) + "\n")
                stream.flush()

            report["phase"] = "OFFSET_CORROBORATION"
            preflight = corroborate(
                mt5, original, math.ceil(before["error_bound_ms"]) + 5, emit=emit
            )
        write_json(output / "preflight.json", preflight)
        if preflight["status"] != "CORROBORATED":
            raise ObservationFailure(preflight["reason"])
        report["phase"] = "CLOCK_AFTER_PREFLIGHT"
        corroborated_clock = probe()
        write_json(output / "clock-after-preflight.json", corroborated_clock)
        bound = max(before["error_bound_ms"], corroborated_clock["error_bound_ms"])
        if (
            not corroborated_clock["passed"]
            or bound > 95
            or any(
                not math.ceil(bound) + 5 <= row["age_ms"] <= 5000 - math.ceil(bound) - 5
                for row in preflight["rows"]
            )
        ):
            raise ObservationFailure("FINAL_MAPPING_OR_CLOCK_CHECK")
        report["phase"] = "DERIVED_PROVISIONAL_BINDING"
        pinned = derived_binding(original, preflight, datetime.now(UTC))
        write_json(output / "derived-binding.private.json", pinned.model_dump(mode="json"))
        report["phase"] = "BROKER_INPUT_CAPTURE"
        raw = capture_once(
            mt5,
            pinned,
            clock_error_ms=math.ceil(bound),
            clock_evidence_sha256=canonical_hash(corroborated_clock),
            conversion_symbol=conversion_symbol,
        )
        write_json(output / "private-capture-initial.json", raw)
        report["phase"] = "CLOCK_AFTER_CAPTURE"
        after = probe()
        write_json(output / "clock-after-capture.json", after)
        bound = max(bound, after["error_bound_ms"])
        if not after["passed"] or bound > 95:
            raise ObservationFailure("FINAL_CLOCK_CHECK")
        rows = preflight["rows"] + list(raw["quotes"].values())
        if raw["conversion"] is not None:
            rows.append(raw["conversion"])
        if any(
            not math.ceil(bound) + 5 <= row["age_ms"] <= 5000 - math.ceil(bound) - 5 for row in rows
        ):
            raise ObservationFailure("FINAL_MAPPING_OR_CLOCK_CHECK")
        raw["clock_error_ms"] = math.ceil(bound) + 5
        raw["clock_evidence_sha256"] = canonical_hash(
            dict(before=before, after_preflight=corroborated_clock, after_capture=after)
        )
        for quote in (
            *raw["quotes"].values(),
            *((raw["conversion"],) if raw["conversion"] else ()),
        ):
            quote["age_upper_ms"] = quote["age_ms"] + raw["clock_error_ms"]
        raw["timestamp_mapping_qualified"] = False
        raw["capture_sha256"] = canonical_hash(
            {k: v for k, v in raw.items() if k != "capture_sha256"}
        )
        write_json(output / "private-capture.json", raw)
        report["phase"] = "NORMALIZATION"
        normalized = {}
        for symbol in ("EURUSD", "USDJPY"):
            item = normalize(raw, symbol=symbol, side="BUY")
            normalized[symbol] = dict(
                observed_fields=item.observed_fields,
                missing=item.missing,
                provenance=item.provenance,
                reason=item.reason,
                snapshot=None,
            )
        write_json(output / "private-normalized.json", normalized)
        report.update(
            status="CAPTURED_DATA_HOLD",
            phase="COMPLETE",
            host_error_bound_ms=raw["clock_error_ms"],
            sample_counts={s: sum(r["symbol"] == s for r in preflight["rows"]) for s in normalized},
            missing={s: row["missing"] for s, row in normalized.items()},
        )
    except Exception as error:
        report["reason"] = safe_reason(error)
    finally:
        report["original_binding_unchanged"] = binding_path.read_bytes() == original_bytes
        if not report["original_binding_unchanged"]:
            report.update(status="BLOCKED", reason="ORIGINAL_BINDING_CHANGED")
        write_json(output / "report.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binding", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--conversion-symbol")
    args = parser.parse_args()
    folder = args.output.resolve()
    private = (ROOT / ".local").resolve()
    if not folder.is_relative_to(private) or folder == private:
        parser.error("use a NEW directory inside this checkout's .local")
    folder.mkdir(parents=True, exist_ok=False)
    print(json.dumps(run(args.binding, folder, args.conversion_symbol), allow_nan=False))


if __name__ == "__main__":
    main()
