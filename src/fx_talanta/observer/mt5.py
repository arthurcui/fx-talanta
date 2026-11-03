"""Windows-only SDK adapter; no credentials, login switching or order methods.

Imported lazily inside the supervised child. The allowlist prevents accidental
calls; broker-issued investor credentials remain the actual privilege boundary.
"""

import ntpath
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from fx_talanta.domain.models import (
    ObservedBar,
    ObservedItem,
    ObservedSymbol,
    ObservedTick,
    TerminalSnapshot,
)
from fx_talanta.observer.contracts import Binding, invalid, windows_path

READ_METHODS = frozenset(
    {
        "initialize",
        "shutdown",
        "terminal_info",
        "account_info",
        "symbol_info",
        "symbol_info_tick",
        "copy_rates_from_pos",
        "positions_get",
        "orders_get",
        "history_orders_get",
        "history_deals_get",
        "history_orders_total",
        "history_deals_total",
    }
)


class ObservationFailure(Exception):
    def __init__(self, reason):
        self.reason = reason
        super().__init__(reason)


class ReadOnlySDK:
    def __init__(self, module):
        self._module = module

    def call(self, method, *args, **kwargs):
        if method not in READ_METHODS:
            raise ValueError("method is outside the observation allowlist")
        result = getattr(self._module, method)(*args, **kwargs)
        if result is None and method != "shutdown":
            raise ObservationFailure("READER_FAILED")
        return result


def number(value):
    # The SDK supplies binary floats; record their decimal string representation.
    return Decimal(str(value))


def timestamp(value):
    return datetime.fromtimestamp(int(value), UTC)


class SDKClock:
    """Explicit, short-lived server-wall-clock mapping; never infer from stale ticks."""

    def __init__(self, binding):
        self.binding = binding
        self.offset = timedelta(seconds=binding.sdk_time_offset_seconds)

    def check(self, utc_time):
        if self.binding.time_policy_from is not None and not (
            self.binding.time_policy_from <= utc_time < self.binding.time_policy_until
        ):
            raise ObservationFailure(invalid("CLOCK_POLICY_EXPIRED", stage="READER"))
        return utc_time

    def decode(self, seconds):
        return self.check(datetime.fromtimestamp(float(seconds), UTC) - self.offset)

    def encode(self, utc_time):
        return self.check(utc_time) + self.offset


def validate_terminal(api, binding):
    terminal, account = api.call("terminal_info"), api.call("account_info")
    if (
        account.trade_mode != 0
        or str(account.login) != binding.account.login
        or account.server != binding.account.server
    ):
        raise ObservationFailure("IDENTITY_MISMATCH")
    if windows_path(terminal.path) != windows_path(
        ntpath.dirname(binding.terminal_path)
    ) or windows_path(terminal.data_path) != windows_path(binding.data_path):
        raise ObservationFailure("PATH_MISMATCH")
    if terminal.build != binding.expected_build:
        raise ObservationFailure("BUILD_CHANGED")
    if account.company != binding.expected_company:
        raise ObservationFailure("COMPANY_MISMATCH")
    if account.margin_mode != binding.expected_margin_mode:
        raise ObservationFailure("MODE_MISMATCH")
    if account.currency != binding.expected_currency:
        raise ObservationFailure("CURRENCY_MISMATCH")
    if not terminal.connected:
        raise ObservationFailure("DISCONNECTED")
    return terminal, account


def item(row, kind, clock=None):
    decode = clock.decode if clock else timestamp
    is_deal = kind == "deals"
    code = int(row.type)
    buy = {0} if is_deal or kind == "positions" else {0, 2, 4, 6}
    sell = {1} if is_deal or kind == "positions" else {1, 3, 5, 7}
    at = row.time if is_deal or kind == "positions" else row.time_setup
    return ObservedItem(
        ticket=str(row.ticket),
        symbol=row.symbol,
        side="BUY" if code in buy else "SELL" if code in sell else "OTHER",
        volume=number(row.volume if is_deal or kind == "positions" else row.volume_current),
        price=number(row.price if is_deal else row.price_open),
        at=decode(at),
        type_code=code,
        profit=number(getattr(row, "profit", 0)),
        commission=number(getattr(row, "commission", 0)),
        swap=number(getattr(row, "swap", 0)),
        fee=number(getattr(row, "fee", 0)),
        stop_loss=number(getattr(row, "sl", 0)),
        take_profit=number(getattr(row, "tp", 0)),
        position_id=str(getattr(row, "position_id", getattr(row, "identifier", row.ticket))),
        order_id=str(row.order) if hasattr(row, "order") else None,
        initial_volume=number(row.volume_initial) if hasattr(row, "volume_initial") else None,
        done_at=decode(row.time_done) if getattr(row, "time_done", 0) else None,
        state_code=getattr(row, "state", None),
        entry_code=getattr(row, "entry", None),
        reason_code=getattr(row, "reason", None),
        magic=getattr(row, "magic", None),
    )


def history(api, binding, kind, start, end):
    clock = SDKClock(binding)
    query_start, query_end = clock.encode(start), clock.encode(end)
    count_method, get_method = f"history_{kind}_total", f"history_{kind}_get"
    before = api.call(count_method, query_start, query_end)
    if not 0 <= before <= 2000:
        raise ObservationFailure("MISSING_DATA")
    seen = {}
    cursor = start
    while cursor < end:
        validate_terminal(api, binding)
        stop = min(cursor + timedelta(hours=1), end)
        batch = api.call(get_method, clock.encode(cursor), clock.encode(stop))
        if len(batch) > 2000:
            raise ObservationFailure("MISSING_DATA")
        for row in batch:
            value = item(row, kind, clock)
            # History orders can have a setup time before this window and a later
            # completion time; the SDK selects them by its own documented history query.
            if kind == "deals" and not start <= value.at <= end:
                raise ObservationFailure(invalid("HISTORY_RANGE", stage="READER"))
            if value.ticket in seen and seen[value.ticket] != value:
                raise ObservationFailure("MISSING_DATA")
            seen[value.ticket] = value
        if len(seen) > 2000:
            raise ObservationFailure("MISSING_DATA")
        cursor = stop
    after = api.call(count_method, query_start, query_end)
    if before != after or len(seen) != after:
        raise ObservationFailure("MISSING_DATA")
    return tuple(sorted(seen.values(), key=lambda value: (value.at, value.ticket)))


def read_snapshot(module, binding, now, *, finished_at=None):
    """Pure SDK seam for fake-module tests; production entry is MT5Reader."""
    binding = Binding.model_validate(binding.model_dump(mode="json"))
    binding.require_permissions()
    if binding.source != "MT5":
        raise ValueError("MT5 adapter cannot write simulator evidence")
    if module.__version__ != binding.sdk_version:
        raise ObservationFailure("SDK_MISMATCH")
    api = ReadOnlySDK(module)
    clock = SDKClock(binding)
    clock.check(now)
    clock.check(now - timedelta(hours=binding.history_hours))
    try:
        if not api.call(
            "initialize",
            binding.terminal_path,
            timeout=max(1, int(binding.call_timeout_seconds * 1000)),
        ):
            raise ObservationFailure("DISCONNECTED")
        terminal, account = validate_terminal(api, binding)
        symbols, ticks, bars = [], [], []
        for symbol in binding.symbols:
            validate_terminal(api, binding)
            info = api.call("symbol_info", symbol)
            if not info.visible:
                raise ObservationFailure("MISSING_DATA")  # operator selects in Market Watch
            symbols.append(
                ObservedSymbol(
                    symbol=symbol,
                    digits=info.digits,
                    volume_min=number(info.volume_min),
                    volume_step=number(info.volume_step),
                    point=number(info.point),
                )
            )
            tick = api.call("symbol_info_tick", symbol)
            ticks.append(
                ObservedTick(
                    symbol=symbol,
                    at=clock.decode(tick.time_msc / 1000),
                    bid=number(tick.bid),
                    ask=number(tick.ask),
                )
            )
            for period, timeframe in ((900, module.TIMEFRAME_M15), (3600, module.TIMEFRAME_H1)):
                rates = api.call("copy_rates_from_pos", symbol, timeframe, 1, 2)
                if len(rates) != 2:
                    raise ObservationFailure("MISSING_DATA")
                for rate in rates:
                    bars.append(
                        ObservedBar(
                            symbol=symbol,
                            opened_at=clock.decode(rate["time"]),
                            period_seconds=period,
                            open=number(rate["open"]),
                            high=number(rate["high"]),
                            low=number(rate["low"]),
                            close=number(rate["close"]),
                        )
                    )
        positions = tuple(item(row, "positions", clock) for row in api.call("positions_get"))
        orders = tuple(item(row, "orders", clock) for row in api.call("orders_get"))
        end = now.replace(microsecond=0)
        start = end - timedelta(hours=binding.history_hours)
        deals = history(api, binding, "deals", start, end)
        history_orders = history(api, binding, "orders", start, end)
        validate_terminal(api, binding)
        observed_at = clock.check(finished_at or datetime.now(UTC))
        return TerminalSnapshot(
            sdk_time_offset_seconds=binding.sdk_time_offset_seconds,
            time_policy_from=binding.time_policy_from,
            time_policy_until=binding.time_policy_until,
            time_policy_evidence=binding.time_policy_evidence,
            account_before=binding.account,
            account_after=binding.account,
            terminal_path=binding.terminal_path,
            data_path=terminal.data_path,
            build=terminal.build,
            currency=account.currency,
            connected=True,
            observed_at=observed_at,
            history_from=start,
            history_to=end,
            history_complete=True,
            symbols=tuple(symbols),
            ticks=tuple(ticks),
            bars=tuple(bars),
            positions=positions,
            orders=orders,
            deals=deals,
            history_orders=history_orders,
            company=account.company,
            margin_mode=account.margin_mode,
            balance=number(account.balance),
            equity=number(account.equity),
        )
    finally:
        api.call("shutdown")


@dataclass(frozen=True)
class MT5Reader:
    def __call__(self, binding, now):
        binding.require_permissions()  # no import, process launch or IPC before this gate
        if sys.platform != "win32":
            raise ValueError("the MT5 reader requires Windows")
        import MetaTrader5

        return read_snapshot(MetaTrader5, binding, now)
