"""Read-only broker observations and honest, possibly incomplete safety inputs.

The SDK seam never supplies cost calibration, provider coverage, mandates or a
reconciled loss ledger. Missing facts produce DATA_HOLD with no SafetyInput;
there are no fixture defaults or invented zero fees/baselines. Captures contain
private account identifiers/prices and must not be printed or committed.
"""

import hashlib
import json
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal

from fx_talanta.acceptance.probe import ProbeSDK, running_pids
from fx_talanta.domain.models import AccountIdentity
from fx_talanta.observer.contracts import Binding
from fx_talanta.observer.mt5 import ObservationFailure, SDKClock, validate_terminal
from fx_talanta.safety.risk import SafetyInput
from fx_talanta.shadow.work import scope_for

D = Decimal
GROUPS = {
    "mandate": {"capital", "maximum_spread", "maximum_adverse", "request_volume", "request_risk"},
    "costs": {"commission", "slippage", "financing", "commission_currency"},
    "baseline_and_exposure": {
        "day_start",
        "day_loss",
        "cashflows_known",
        "flags",
        "occupied_slots",
        "symbol_occupied",
        "existing_risk",
        "existing_gross",
        "existing_margin",
        "base_exposure",
        "quote_exposure",
        "other_exposure",
        "stress_loss",
    },
    "session": {"blackout", "session_open"},
    "providers": {"inputs_ok"},
}
CONTEXT_FIELDS = set().union(*GROUPS.values())


def canonical_hash(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def decimal(value, *, positive=False):
    if isinstance(value, bool):
        raise ObservationFailure("INVALID_NUMBER")
    result = D(str(value))
    if not result.is_finite() or (result <= 0 if positive else result < 0):
        raise ObservationFailure("INVALID_NUMBER")
    return result


def clock_time_ms():
    return time.time_ns() // 1_000_000


def _positions(rows, pending=False):
    if len(rows) > 2000:
        raise ObservationFailure("EXPOSURE_CAPTURE_LIMIT")
    fields = (
        "ticket",
        "symbol",
        "type",
        "volume_current" if pending else "volume",
        "sl",
        "tp",
        "price_open",
        "magic",
    )
    return sorted(
        ({k: str(getattr(row, k)) for k in fields} for row in rows), key=lambda row: row["ticket"]
    )


def _quote(api, symbol, clock):
    info, tick = api.call("symbol_info", symbol), api.call("symbol_info_tick", symbol)
    if not info.visible:
        raise ObservationFailure("SYMBOL_NOT_VISIBLE")
    bid, ask = decimal(tick.bid, positive=True), decimal(tick.ask, positive=True)
    if ask < bid or isinstance(tick.time_msc, bool) or tick.time_msc <= 0:
        raise ObservationFailure("INVALID_QUOTE")
    return info, dict(
        broker_symbol=symbol,
        bid=str(bid),
        ask=str(ask),
        raw_tick_ms=int(tick.time_msc),
        tick_ms=int(clock.decode(tick.time_msc / 1000).timestamp() * 1000),
    )


def capture_once(
    module,
    binding,
    *,
    clock_error_ms,
    clock_evidence_sha256,
    conversion_symbol=None,
    process_check=running_pids,
    now_ms=clock_time_ms,
):
    """One bounded demo read; caller supervises this in a short-lived child process.

    NTP validation is the caller's responsibility. Only an already-running pinned
    terminal is used, with global algorithmic trading disabled. MT5 initialize
    still has a process-check race; this is not an atomic terminal lifecycle lock.
    USDCAD must be explicitly named and already visible; no symbol is selected.
    """
    binding = Binding.model_validate(binding.model_dump(mode="json"))
    binding.require_permissions()
    if (
        binding.source != "MT5"
        or len(binding.symbols) != 2
        or [s[:6] for s in binding.symbols] != ["EURUSD", "USDJPY"]
    ):
        raise ValueError("PINNED_FOREX_DEMO_REQUIRED")
    if module.__version__ != binding.sdk_version:
        raise ObservationFailure("SDK_MISMATCH")
    if (
        type(clock_error_ms) is not int
        or not 0 <= clock_error_ms <= 1000000
        or not re.fullmatch(r"[0-9a-f]{64}", clock_evidence_sha256)
    ):
        raise ValueError("EXPLICIT_CLOCK_EVIDENCE_REQUIRED")
    if conversion_symbol is not None and not re.fullmatch(
        r"USDCAD[A-Za-z0-9._-]{0,20}", conversion_symbol
    ):
        raise ValueError("PINNED_USDCAD_REQUIRED")
    started, monotonic_start = now_ms(), time.monotonic_ns()
    clock = SDKClock(binding)
    clock.check(datetime.fromtimestamp(started / 1000, UTC))
    pids = process_check(binding)
    if len(pids) != 1:
        raise ObservationFailure("RUNNING_TERMINAL_REQUIRED")
    symbols = (*binding.symbols, *((conversion_symbol,) if conversion_symbol else ()))
    api = ProbeSDK(module, symbols)
    try:
        if process_check(binding) != pids:
            raise ObservationFailure("TERMINAL_PROCESS_CHANGED")
        if not api.call("initialize", binding.terminal_path, timeout=5000):
            raise ObservationFailure("DISCONNECTED")
        terminal, account = validate_terminal(api, binding)
        if getattr(terminal, "trade_allowed", None) is not False:
            raise ObservationFailure("ALGORITHMIC_TRADING_MUST_BE_DISABLED")
        before = (_positions(api.call("positions_get")), _positions(api.call("orders_get"), True))
        quotes, specifications, calculations = {}, {}, {}
        for symbol in binding.symbols:
            info, quote = _quote(api, symbol, clock)
            canonical = symbol[:6]
            if (info.currency_base, info.currency_profit) != (canonical[:3], canonical[3:]):
                raise ObservationFailure("SYMBOL_CURRENCY_MISMATCH")
            fields = (
                "point",
                "volume_min",
                "volume_max",
                "volume_step",
                "trade_contract_size",
                "trade_tick_size",
                "trade_tick_value_loss",
            )
            spec = {k: str(decimal(getattr(info, k), positive=True)) for k in fields}
            for field in (
                "trade_stops_level",
                "trade_freeze_level",
                "trade_exemode",
                "filling_mode",
            ):
                spec[field] = int(getattr(info, field))
                if spec[field] < 0:
                    raise ObservationFailure("INVALID_SPECIFICATION")
            quotes[canonical], specifications[canonical] = quote, spec
            tick_size, minimum = D(spec["trade_tick_size"]), D(spec["volume_min"])
            distance = max(
                D(spec["trade_stops_level"]) * D(spec["point"]) + 2 * tick_size, 20 * tick_size
            )
            distance = (distance / tick_size).to_integral_value(rounding=ROUND_CEILING) * tick_size
            calculations[canonical] = {}
            for action, side in ((0, "BUY"), (1, "SELL")):
                entry = D(quote["ask"] if side == "BUY" else quote["bid"])
                stop = D(quote["bid"]) - distance if side == "BUY" else D(quote["ask"]) + distance
                stop = (stop / tick_size).to_integral_value(
                    rounding=ROUND_FLOOR if side == "BUY" else ROUND_CEILING
                ) * tick_size
                if stop <= 0:
                    raise ObservationFailure("INVALID_SPECIFICATION")
                profit = D(
                    str(
                        api.call(
                            "order_calc_profit",
                            action,
                            symbol,
                            float(minimum),
                            float(entry),
                            float(stop),
                        )
                    )
                )
                margin = decimal(
                    api.call("order_calc_margin", action, symbol, float(minimum), float(entry)),
                    positive=True,
                )
                if not profit.is_finite() or profit >= 0:
                    raise ObservationFailure("INVALID_CALCULATION")
                calculations[canonical][side] = dict(
                    stop=str(stop),
                    entry=str(entry),
                    volume=str(minimum),
                    stop_profit_account=str(profit),
                    margin_account=str(margin),
                    loss_per_lot_account=str(-profit / minimum),
                    margin_per_lot_account=str(margin / minimum),
                    fees_included=False,
                    standalone_margin=True,
                )
        conversion = None
        if conversion_symbol is not None:
            info, conversion = _quote(api, conversion_symbol, clock)
            if (info.currency_base, info.currency_profit) != ("USD", "CAD"):
                raise ObservationFailure("CONVERSION_CURRENCY_MISMATCH")
            conversion["selected"] = "ask"
            conversion["rule"] = "CONSERVATIVE_USD_LIABILITY_IN_CAD"
        terminal, account = validate_terminal(api, binding)
        if getattr(terminal, "trade_allowed", None) is not False:
            raise ObservationFailure("ALGORITHMIC_TRADING_MUST_BE_DISABLED")
        after = (_positions(api.call("positions_get")), _positions(api.call("orders_get"), True))
        if after != before:
            raise ObservationFailure("EXTERNAL_ACCOUNT_CHANGE")
        if process_check(binding) != pids:
            raise ObservationFailure("TERMINAL_PROCESS_CHANGED")
        finished = now_ms()
        elapsed_ms = (time.monotonic_ns() - monotonic_start) / 1_000_000
        if abs(finished - started - elapsed_ms) > 5:
            raise ObservationFailure("HOST_CLOCK_CHANGED")
        if not 0 <= finished - started <= 10000:
            raise ObservationFailure("CAPTURE_DEADLINE")
        clock.check(datetime.fromtimestamp(finished / 1000, UTC))
        account_data = {
            k: str(decimal(getattr(account, k), positive=k in {"equity", "balance"}))
            for k in ("balance", "equity", "margin", "margin_free", "margin_so_so")
        }
        account_data["currency"] = account.currency
        account_data["stopout_mode"] = int(account.margin_so_mode)
        for quote in (*quotes.values(), *((conversion,) if conversion else ())):
            quote["age_ms"] = finished - quote["tick_ms"]
            quote["age_upper_ms"] = quote["age_ms"] + clock_error_ms + 5
        result = dict(
            schema="connected-shadow-inputs/1",
            account_identity=binding.account.model_dump(mode="json"),
            account_scope=scope_for(binding.account),
            binding_sha256=binding.fingerprint(),
            measured_at_ms=finished,
            capture_elapsed_ms=finished - started,
            clock_error_ms=clock_error_ms + 5,
            clock_evidence_sha256=clock_evidence_sha256,
            sdk_time_offset_seconds=binding.sdk_time_offset_seconds,
            time_policy_evidence=binding.time_policy_evidence,
            account=account_data,
            quotes=quotes,
            specifications=specifications,
            calculations=calculations,
            conversion=conversion,
            positions=after[0],
            orders=after[1],
            sdk_calls=dict(api.calls),
            execution_enabled=False,
            qualified_for_trading=False,
        )
    finally:
        api.call("shutdown")
    result["sdk_calls"] = dict(api.calls)
    result["capture_sha256"] = canonical_hash(result)
    return result


@dataclass(frozen=True)
class NormalizedInput:
    snapshot: SafetyInput | None
    observed_fields: dict
    missing: tuple[str, ...]
    provenance: dict

    @property
    def reason(self):
        return "DATA_HOLD" if self.missing else "INPUTS_ASSEMBLED_NOT_QUALIFIED"


def normalize(capture, *, symbol, side, context=None):
    """Join observations with explicitly evidenced operational context, never defaults.

    Context is a trusted backend artifact, not model/user wire input. It must
    carry matching account_scope, observed_at_ms/valid_until_ms, values, and one
    SHA-256 evidence reference per GROUPS entry. References prove linkage only;
    the caller remains responsible for validating those underlying artifacts.
    """
    expected = capture.get("capture_sha256")
    if expected != canonical_hash({k: v for k, v in capture.items() if k != "capture_sha256"}):
        raise ValueError("CAPTURE_HASH_MISMATCH")
    account = AccountIdentity.model_validate(capture["account_identity"])
    if (
        account.venue != "BROKER_DEMO"
        or capture["account_scope"] != scope_for(account)
        or capture["execution_enabled"] is not False
    ):
        raise ValueError("CAPTURE_BINDING_MISMATCH")
    if symbol not in {"EURUSD", "USDJPY"} or side not in {"BUY", "SELL"}:
        raise ValueError("UNSUPPORTED_SHADOW_ANALYSIS")
    now = capture["measured_at_ms"]
    quote, spec, calc = (
        capture["quotes"][symbol],
        capture["specifications"][symbol],
        capture["calculations"][symbol][side],
    )
    acct, missing = capture["account"], []
    if capture.get("timestamp_mapping_qualified") is False or str(
        capture.get("time_policy_evidence", "")
    ).startswith("PROVISIONAL_CONSISTENCY_ONLY"):
        missing.append("TIMESTAMP_MAPPING_UNQUALIFIED")
    observed = dict(
        measured_at_ms=now,
        symbol=symbol,
        side=side,
        currency=acct["currency"],
        bid=quote["bid"],
        ask=quote["ask"],
        stop=calc["stop"],
        benchmark=calc["entry"],
        quote_age_ms=now - quote["tick_ms"],
        clock_error_ms=capture["clock_error_ms"],
        equity=acct["equity"],
        contract=spec["trade_contract_size"],
        tick_size=spec["trade_tick_size"],
        tick_value_loss=spec["trade_tick_value_loss"],
        broker_loss_per_lot=calc["loss_per_lot_account"],
        broker_margin_per_lot=calc["margin_per_lot_account"],
        minimum=spec["volume_min"],
        step=spec["volume_step"],
        maximum=spec["volume_max"],
    )
    conversion = capture["conversion"]
    if acct["currency"] == "USD":
        usd, conversion_age = D(1), observed["quote_age_ms"]
    elif acct["currency"] == "CAD" and conversion:
        usd = D(conversion["ask"])
        conversion_age = max(observed["quote_age_ms"], now - conversion["tick_ms"])
    else:
        usd, conversion_age = None, None
        missing.append("CAD_CONVERSION" if acct["currency"] == "CAD" else "ACCOUNT_CURRENCY")
    if usd is not None:
        observed.update(
            usd_to_account=usd,
            conversion_age_ms=conversion_age,
            base_to_account=D(quote["bid"]) * usd if symbol == "EURUSD" else usd,
            quote_to_account=usd if symbol == "EURUSD" else usd / D(quote["bid"]),
        )
    if acct["stopout_mode"] == 0 and D(acct["margin_so_so"]) > 0:
        observed["stopout_ratio"] = D(acct["margin_so_so"]) / 100
    else:
        missing.append("PERCENT_STOP_OUT_MODEL")
    values = {}
    if context is not None:
        if (
            set(context)
            != {"account_scope", "observed_at_ms", "valid_until_ms", "values", "evidence"}
            or context["account_scope"] != capture["account_scope"]
            or not 0 <= context["observed_at_ms"] <= now < context["valid_until_ms"]
            or context["valid_until_ms"] - context["observed_at_ms"] > 60000
        ):
            raise ValueError("OPERATIONAL_CONTEXT_BINDING_OR_TIME")
        values = dict(context["values"])
        if set(values) - CONTEXT_FIELDS:
            raise ValueError("OBSERVED_INPUT_OVERRIDE_FORBIDDEN")
    for group, fields in GROUPS.items():
        reference = context["evidence"].get(group, "") if context else ""
        if not re.fullmatch(r"[0-9a-f]{64}", reference) or not fields <= values.keys():
            missing.append(group.upper())
    if not missing:
        if values["occupied_slots"] < len(capture["positions"]) + len(capture["orders"]):
            raise ValueError("EXPOSURE_UNDERCOUNT")
        if (
            any(
                row["symbol"] == quote["broker_symbol"]
                for row in (*capture["positions"], *capture["orders"])
            )
            and not values["symbol_occupied"]
        ):
            raise ValueError("SYMBOL_EXPOSURE_OMITTED")
        if D(values["existing_margin"]) < D(acct["margin"]):
            raise ValueError("MARGIN_UNDERCOUNT")
        observed["cost_to_account"] = usd if values["commission_currency"] == "USD" else D(1)
        observed["expires_in_ms"] = min(60000, context["valid_until_ms"] - now)
        snapshot = SafetyInput.model_validate(observed | values)
    else:
        snapshot = None
    return NormalizedInput(
        snapshot,
        {k: str(v) if isinstance(v, D) else v for k, v in observed.items()},
        tuple(missing),
        dict(
            account_scope=capture["account_scope"],
            capture_sha256=expected,
            clock_evidence_sha256=capture["clock_evidence_sha256"],
            conversion_tick_ms=conversion["tick_ms"] if conversion else None,
            operational_evidence=context["evidence"] if context else {},
            execution_enabled=False,
            qualified_for_trading=False,
        ),
    )
