"""B01 research signal kernel. No broker, order, model or network dependencies."""

from datetime import timedelta
from decimal import ROUND_CEILING, Decimal, localcontext
from hashlib import sha256
from typing import Literal

from pydantic import Field, model_validator

from fx_talanta.domain.models import Amount, FrozenModel, Timestamp, utc

VERSION = "B01-research/1"


class Bar(FrozenModel):
    symbol: Literal["EURUSD", "USDJPY"]
    timeframe: Literal["M15", "H1"]
    close_at: Timestamp
    available_at: Timestamp
    revision: int = Field(ge=1)
    open: Amount = Field(gt=0)
    high: Amount = Field(gt=0)
    low: Amount = Field(gt=0)
    close: Amount = Field(gt=0)

    @model_validator(mode="after")
    def valid(self):
        if not self.low <= min(self.open, self.close) <= max(self.open, self.close) <= self.high:
            raise ValueError("invalid OHLC")
        if self.available_at < self.close_at:
            raise ValueError("completed bar unavailable before close")
        minutes = 15 if self.timeframe == "M15" else 60
        if self.close_at.second or self.close_at.microsecond or self.close_at.minute % minutes:
            raise ValueError("bar close must align to timeframe")
        return self


def visible(bars, symbol, at):
    versions = {}
    for bar in bars:
        if bar.symbol != symbol or bar.available_at > at or bar.close_at > at:
            continue
        key = (bar.timeframe, bar.close_at)
        rows = versions.setdefault(key, {})
        if bar.revision in rows and rows[bar.revision] != bar:
            raise ValueError("conflicting immutable bar revision")
        rows[bar.revision] = bar
    selected, original_availability = [], {}
    for key, rows in sorted(versions.items()):
        revisions = sorted(rows)
        if revisions != list(range(1, revisions[-1] + 1)):
            raise ValueError("bar revision history incomplete")
        times = [rows[r].available_at for r in revisions]
        if times != sorted(times):
            raise ValueError("bar revision arrival order invalid")
        selected.append(rows[revisions[-1]])
        original_availability[key] = times[0]
    return selected, original_availability


def ema(values, period):
    result = sum(values[:period]) / Decimal(period)
    alpha = Decimal(2) / Decimal(period + 1)
    for value in values[period:]:
        result += alpha * (value - result)
    return result


def evaluate(bars, symbol, cutoff, *, history_complete=False, position_open=False):
    """Return a research candidate, never an executable intent.

    The caller must attest dataset completeness against its recorded session
    calendar; the kernel cannot infer missing trading sessions from OHLC alone.
    """
    if symbol not in {"EURUSD", "USDJPY"}:
        raise ValueError("unsupported symbol")
    at = utc(cutoff)
    selected, first = visible(bars, symbol, at)
    base = {
        "strategy": VERSION,
        "symbol": symbol,
        "as_of": at.isoformat(),
        "input_hash": sha256("\n".join(b.model_dump_json() for b in selected).encode()).hexdigest(),
        "execution_enabled": False,
        "action": "HOLD",
        "session": "UTC_WEEKDAY_0000_2345",
    }

    def hold(reason):
        return {**base, "reason": reason}

    if not history_complete:
        return hold("DATASET_COMPLETENESS_UNVERIFIED")
    if position_open:
        return hold("POSITION_ALREADY_OPEN")
    end = at.replace(hour=23, minute=45, second=0, microsecond=0)
    if at.weekday() >= 5 or at >= end:
        return hold("OUTSIDE_PREREGISTERED_SESSION")
    h1 = [b for b in selected if b.timeframe == "H1"]
    m15 = [b for b in selected if b.timeframe == "M15"]
    if len(h1) < 200 or len(m15) < 21:
        return hold("INDICATOR_WARMUP")
    signal = m15[-1]
    expires = first[("M15", signal.close_at)] + timedelta(seconds=60)
    if at >= expires:
        return hold("SIGNAL_EXPIRED")
    # Completeness attestation does not excuse a missing latest closed H1 bar.
    if at - h1[-1].close_at >= timedelta(hours=1):
        return hold("H1_HISTORY_STALE")
    with localcontext() as context:
        context.prec = 34
        values = [b.close for b in h1]
        fast, slow = ema(values, 50), ema(values, 200)
        preceding = m15[-21:-1]  # Never include the breakout bar in its threshold.
        side = (
            "BUY"
            if fast > slow and signal.close > max(b.high for b in preceding)
            else "SELL"
            if fast < slow and signal.close < min(b.low for b in preceding)
            else None
        )
        if side is None:
            return hold("NO_BREAKOUT")
        ranges = [
            max(b.high - b.low, abs(b.high - previous.close), abs(b.low - previous.close))
            for previous, b in zip(m15, m15[1:], strict=False)
        ]
        atr = sum(ranges[:14]) / Decimal(14)
        for value in ranges[14:]:
            atr = (atr * Decimal(13) + value) / Decimal(14)
        quantum = Decimal("0.00001" if symbol == "EURUSD" else "0.001")
        distance = (atr * Decimal("1.5") / quantum).to_integral_value(
            rounding=ROUND_CEILING
        ) * quantum
        if distance <= 0:
            return hold("ZERO_RISK_DISTANCE")
        return {
            **base,
            "action": "CANDIDATE",
            "side": side,
            "signal_bar_close": signal.close_at.isoformat(),
            "signal_price": str(signal.close),
            "signal_available_at": first[("M15", signal.close_at)].isoformat(),
            "expires_at": expires.isoformat(),
            "ema50": str(fast),
            "ema200": str(slow),
            "atr14": str(atr),
            "stop_distance": str(distance),
            "target_distance": str(distance * 2),
            "time_exit_at": min(signal.close_at + timedelta(minutes=15 * 16), end).isoformat(),
        }
