"""Reviewed parameter-only research kernel. Never executes generated code."""

from datetime import timedelta
from decimal import ROUND_CEILING, Decimal
from typing import Annotated, Literal

from pydantic import Field, model_validator

from fx_talanta.domain.models import FrozenModel
from fx_talanta.research.baseline import ema, visible
from fx_talanta.research.market_sessions import context, entry_window, reference_bars
from fx_talanta.research.replay import digest
from fx_talanta.research.structural import StructuralRules, StructuralSignal


class Rules(FrozenModel):
    family: Literal["TREND_BREAKOUT", "TREND_PULLBACK"]
    trend_period: int = Field(ge=5, le=200, strict=True)
    signal_period: int = Field(ge=2, le=100, strict=True)
    atr_period: int = Field(ge=2, le=50, strict=True)
    stop_atr: Decimal = Field(gt=0, le=5)
    reward_risk: Decimal = Field(gt=0, le=5)
    hold_bars: int = Field(ge=1, le=32, strict=True)
    start_hour_utc: int = Field(ge=0, le=22, strict=True)
    end_hour_utc: int = Field(ge=1, le=23, strict=True)
    calendar_policy: Literal["REQUIRE_MARKET_HEALTH"] = "REQUIRE_MARKET_HEALTH"
    entry_session: Literal[
        "UTC_WINDOW", "TOKYO", "LONDON", "NEW_YORK", "LONDON_NEW_YORK_OVERLAP"
    ] = "UTC_WINDOW"
    reference_window: Literal["ROLLING", "CURRENT_SESSION", "PREVIOUS_COMPLETED_TOKYO"] = "ROLLING"

    @model_validator(mode="after")
    def session(self):
        if self.start_hour_utc >= self.end_hour_utc:
            raise ValueError("same-day UTC session required")
        if self.reference_window != "ROLLING" and self.family != "TREND_BREAKOUT":
            raise ValueError("session ranges require breakout rules")
        if self.reference_window == "CURRENT_SESSION" and self.entry_session == "UTC_WINDOW":
            raise ValueError("current-session range requires a named entry session")
        return self

    def evaluate(self, bars, symbol, cutoff, *, history_complete=False, position_open=False):
        selected, first = visible(bars, symbol, cutoff)
        base = dict(
            action="HOLD",
            as_of=cutoff.isoformat(),
            symbol=symbol,
            input_hash=digest([b.model_dump(mode="json") for b in selected]),
            execution_enabled=False,
            market_session=context(cutoff),
            reference_window=self.reference_window,
        )

        def hold(reason):
            return dict(base, reason=reason)

        if not history_complete:
            return hold("DATASET_COMPLETENESS_UNVERIFIED")
        if position_open:
            return hold("POSITION_ALREADY_OPEN")
        if cutoff.weekday() >= 5 or not self.start_hour_utc <= cutoff.hour < self.end_hour_utc:
            return hold("OUTSIDE_SESSION")
        window = entry_window(self.entry_session, cutoff)
        if self.entry_session != "UTC_WINDOW" and window is None:
            return hold("OUTSIDE_NAMED_SESSION")
        h1 = [b for b in selected if b.timeframe == "H1"]
        m15 = [b for b in selected if b.timeframe == "M15"]
        lookback = self.signal_period if self.reference_window == "ROLLING" else 1
        if len(h1) < self.trend_period + 3 or len(m15) < max(lookback + 1, self.atr_period + 1):
            return hold("INDICATOR_WARMUP")
        signal = m15[-1]
        expires = first[("M15", signal.close_at)] + timedelta(seconds=60)
        if window is not None:
            expires = min(expires, window[1])
        if cutoff >= expires or cutoff - h1[-1].close_at >= timedelta(hours=1):
            return hold("SIGNAL_EXPIRED_OR_HISTORY_STALE")
        values = [b.close for b in h1]
        trend, prior = ema(values, self.trend_period), ema(values[:-3], self.trend_period)
        up, down = values[-1] > trend > prior, values[-1] < trend < prior
        if self.family == "TREND_BREAKOUT":
            preceding = reference_bars(
                self.reference_window, self.entry_session, m15, signal, self.signal_period, cutoff
            )
            if not preceding:
                return hold("REFERENCE_RANGE_INCOMPLETE")
            base["reference_range"] = dict(
                bars=len(preceding),
                start=preceding[0].close_at.isoformat(),
                end=preceding[-1].close_at.isoformat(),
            )
            buy = signal.close > max(b.high for b in preceding)
            sell = signal.close < min(b.low for b in preceding)
        else:
            closes = [b.close for b in m15]
            old, new = ema(closes[:-1], self.signal_period), ema(closes, self.signal_period)
            buy = closes[-2] <= old and closes[-1] > new
            sell = closes[-2] >= old and closes[-1] < new
        side = "BUY" if up and buy else "SELL" if down and sell else None
        if side is None:
            return hold("NO_SIGNAL")
        ranges = [
            max(b.high - b.low, abs(b.high - a.close), abs(b.low - a.close))
            for a, b in zip(m15, m15[1:], strict=False)
        ]
        atr = sum(ranges[-self.atr_period :]) / self.atr_period
        quantum = Decimal("0.00001" if symbol == "EURUSD" else "0.001")
        distance = (atr * self.stop_atr / quantum).to_integral_value(
            rounding=ROUND_CEILING
        ) * quantum
        target = (distance * self.reward_risk / quantum).to_integral_value(
            rounding=ROUND_CEILING
        ) * quantum
        if distance <= 0:
            return hold("ZERO_RISK_DISTANCE")
        end = cutoff.replace(hour=self.end_hour_utc, minute=0, second=0, microsecond=0)
        if window is not None:
            end = min(end, window[1])
        return dict(
            base,
            action="CANDIDATE",
            side=side,
            signal_bar_close=signal.close_at.isoformat(),
            signal_price=str(signal.close),
            expires_at=expires.isoformat(),
            stop_distance=str(distance),
            target_distance=str(target),
            time_exit_at=min(
                end, signal.close_at + timedelta(minutes=15 * self.hold_bars)
            ).isoformat(),
        )


ExecutableRules = Annotated[Rules | StructuralRules, Field(discriminator="family")]


def make_signal(rules):
    return StructuralSignal(rules) if isinstance(rules, StructuralRules) else rules.evaluate
