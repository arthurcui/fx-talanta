"""Causal, stateful EURUSD setup detector. No broker or execution authority.

Create one detector per replay. Rebuild by replaying ordered arrivals; never share
mutable detector state between arms, runs or partitions.
"""

from datetime import datetime, timedelta
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from typing import Literal

from fx_talanta.domain.models import FrozenModel
from fx_talanta.research.baseline import ema, visible
from fx_talanta.research.market_sessions import context, entry_window
from fx_talanta.research.replay import digest

D = Decimal
TERMINAL = {"CONFIRMED", "INVALIDATED", "EXPIRED", "DATA_BLOCKED"}


class StructuralRules(FrozenModel):
    # The first implementation is one preregistered hypothesis, not a parameter search.
    family: Literal["STRUCTURAL_PULLBACK"] = "STRUCTURAL_PULLBACK"
    arm: Literal["RETEST_CONFIRMATION", "FIRST_TOUCH"] = "RETEST_CONFIRMATION"
    trend_period: Literal[50] = 50
    atr_period: Literal[14] = 14
    swing_bars: Literal[2] = 2
    level_hours: Literal[8] = 8
    zone_atr: Literal["0.25"] = "0.25"
    stop_buffer_atr: Literal["0.25"] = "0.25"
    confirmation_bars: Literal[8] = 8
    reward_risk: Literal[2] = 2
    hold_bars: Literal[16] = 16
    entry_session: Literal["LONDON"] = "LONDON"
    calendar_policy: Literal["REQUIRE_MARKET_HEALTH"] = "REQUIRE_MARKET_HEALTH"
    lifecycle_policy: Literal["FINITE_TARGET_90_PERCENT"] = "FINITE_TARGET_90_PERCENT"


def contiguous(bars, minutes):
    return all(
        b.close_at - a.close_at == timedelta(minutes=minutes)
        for a, b in zip(bars, bars[1:], strict=False)
    )


def encoded(bars):
    return [b.model_dump(mode="json") for b in bars]


class StructuralSignal:
    def __init__(self, rules):
        self.rules = rules
        self.setups = []
        self.active = None
        self.levels = set()
        self.consumed = {}
        self.last_bar = None
        self.last_cutoff = None
        self.data_blocked = False
        self.last_candidate = None

    def transition(self, setup, state, at, reason):
        setup["state"] = state
        setup["transitions"].append(dict(at=at.isoformat(), state=state, reason=reason))

    def __call__(self, bars, symbol, cutoff, *, history_complete=False, position_open=False):
        if symbol != "EURUSD":
            raise ValueError("structural study supports EURUSD only")
        if self.last_cutoff and cutoff < self.last_cutoff:
            raise ValueError("setup arrivals must be monotonic")
        self.last_cutoff = cutoff
        selected, first = visible(bars, symbol, cutoff)
        base = dict(
            action="HOLD",
            as_of=cutoff.isoformat(),
            symbol=symbol,
            input_hash=digest(encoded(selected)),
            execution_enabled=False,
            market_session=context(cutoff),
            family=self.rules.family,
            arm=self.rules.arm,
        )

        def hold(reason):
            return dict(base, reason=reason)

        for b in selected:
            key = (b.timeframe, b.close_at)
            if key in self.consumed and self.consumed[key] != b:
                self.data_blocked = True
        if self.data_blocked or not history_complete:
            if self.active and self.active["state"] not in TERMINAL:
                self.transition(self.active, "DATA_BLOCKED", cutoff, "REVISED_OR_INCOMPLETE_INPUTS")
            return hold("REVISED_OR_INCOMPLETE_INPUTS")
        self.consumed.update({(b.timeframe, b.close_at): b for b in selected})
        h1 = [b for b in selected if b.timeframe == "H1"]
        m15 = [b for b in selected if b.timeframe == "M15"]
        if not m15:
            return hold("INDICATOR_WARMUP")
        bar = m15[-1]
        if self.last_bar == bar.close_at:
            return hold("ALREADY_PROCESSED_BAR")
        prior_bar, self.last_bar = self.last_bar, bar.close_at
        s = self.active
        if s and s["state"] not in TERMINAL:
            s["m15"].append(bar.model_dump(mode="json"))
        if (
            len(h1) < 53
            or len(m15) < 15
            or not contiguous(h1[-53:], 60)
            or not contiguous(m15[-15:], 15)
            or cutoff - h1[-1].close_at >= timedelta(hours=1)
            or cutoff >= first[("M15", bar.close_at)] + timedelta(seconds=60)
            or (
                s
                and s["state"] not in TERMINAL
                and prior_bar
                and bar.close_at - prior_bar != timedelta(minutes=15)
            )
        ):
            if s and s["state"] not in TERMINAL:
                self.transition(s, "DATA_BLOCKED", cutoff, "GAPPED_OR_STALE_INPUTS")
            return hold("GAPPED_OR_STALE_INPUTS")
        window = entry_window(self.rules.entry_session, cutoff)
        values = [b.close for b in h1]
        now_ema, old_ema = ema(values, 50), ema(values[:-3], 50)
        side = (
            "BUY"
            if values[-1] > now_ema > old_ema
            else ("SELL" if values[-1] < now_ema < old_ema else None)
        )
        if s and s["state"] not in TERMINAL:
            if cutoff >= datetime.fromisoformat(s["expires_at"]) or window is None:
                self.transition(s, "EXPIRED", cutoff, "SETUP_OR_SESSION_DEADLINE")
            elif side != s["side"]:
                self.transition(s, "INVALIDATED", cutoff, "H1_TREND_LOST")
        if window is None or side is None:
            return hold("OUTSIDE_SESSION" if window is None else "NO_H1_TREND")
        if not s or s["state"] in TERMINAL:
            s = self.watch(h1, m15, side, cutoff, window, now_ema, old_ema)
            if s is None:
                return hold("NO_UNUSED_CONFIRMED_LEVEL")
            return hold("LEVEL_WATCHED_BEFORE_TOUCH")
        if bar.close_at - timedelta(minutes=15) < datetime.fromisoformat(s["known_at"]):
            return hold("LEVEL_NOT_KNOWN_BEFORE_BAR")
        low, high, stop = D(s["zone_low"]), D(s["zone_high"]), D(s["stop"])
        buy = s["side"] == "BUY"
        if (buy and bar.low <= stop) or (not buy and bar.high >= stop):
            self.transition(s, "INVALIDATED", cutoff, "STRUCTURAL_STOP_CROSSED")
            return hold("STRUCTURAL_STOP_CROSSED")
        touching = bar.low <= high and bar.high >= low
        away = bar.close > high if buy else bar.close < low
        if s["state"] == "LEVEL_KNOWN" and touching:
            if not s["departed"]:
                return hold("WAIT_FOR_DEPARTURE")
            ranges = [b.high - b.low for b in m15[-4:]]
            s["weakening"] = sum(ranges[-2:]) <= sum(ranges[:2])
            s["range_comparison"] = dict(recent=str(sum(ranges[-2:])), prior=str(sum(ranges[:2])))
            s["expires_at"] = min(
                datetime.fromisoformat(s["expires_at"]),
                bar.close_at + timedelta(minutes=15 * self.rules.confirmation_bars),
            ).isoformat()
            self.transition(s, "TOUCHED", cutoff, "FIRST_TOUCH_CLOSED")
            if self.rules.arm == "FIRST_TOUCH":
                return self.candidate(base, s, bar, cutoff, first, window, position_open)
        elif s["state"] == "TOUCHED" and away:
            self.transition(s, "BOUNCED", cutoff, "LATER_CLOSE_OUTSIDE_ZONE")
        elif s["state"] == "BOUNCED" and touching:
            s["retest_high"], s["retest_low"] = str(bar.high), str(bar.low)
            self.transition(s, "RETESTED", cutoff, "LATER_RETEST_HELD_STOP")
        elif s["state"] == "RETESTED":
            reversal = (
                (bar.close > bar.open and bar.close > D(s["retest_high"]))
                if buy
                else (bar.close < bar.open and bar.close < D(s["retest_low"]))
            )
            if reversal and bar.high - bar.low <= D(s["atr"]):
                if not s["weakening"]:
                    self.transition(s, "INVALIDATED", cutoff, "PULLBACK_NOT_WEAKENING")
                    return hold("PULLBACK_NOT_WEAKENING")
                self.transition(s, "CONFIRMED", cutoff, "SHORT_REVERSAL_CLOSED_PAST_RETEST")
                if self.rules.arm == "RETEST_CONFIRMATION":
                    return self.candidate(base, s, bar, cutoff, first, window, position_open)
        if s["state"] == "LEVEL_KNOWN" and away:
            s["departed"] = True
        return hold("WAIT_" + s["state"])

    def watch(self, h1, m15, side, cutoff, window, trend, prior):
        buy = side == "BUY"
        levels = []
        for i in range(2, len(h1) - 2):
            b = h1[i]
            neighbors = h1[i - 2 : i] + h1[i + 1 : i + 3]
            pivot = (
                b.low < min(x.low for x in neighbors)
                if buy
                else (b.high > max(x.high for x in neighbors))
            )
            identity = (side, b.close_at)
            if (
                pivot
                and contiguous(h1[i - 2 : i + 3], 60)
                and identity not in self.levels
                and cutoff < b.close_at + timedelta(hours=self.rules.level_hours)
            ):
                levels.append((i, identity))
        if not levels:
            return None
        i, identity = levels[-1]
        pivot = h1[i]
        ranges = [
            max(b.high - b.low, abs(b.high - a.close), abs(b.low - a.close))
            for a, b in zip(m15[-15:-1], m15[-14:], strict=True)
        ]
        atr = sum(ranges) / 14
        if atr <= 0:
            return None
        level = pivot.low if buy else pivot.high
        low, high = level - atr * D(self.rules.zone_atr), level + atr * D(self.rules.zone_atr)
        stop = (
            low - atr * D(self.rules.stop_buffer_atr)
            if buy
            else (high + atr * D(self.rules.stop_buffer_atr))
        )
        stop = stop.quantize(D("0.00001"), rounding=ROUND_FLOOR if buy else ROUND_CEILING)
        setup = dict(
            setup_id=digest(
                dict(level=pivot.model_dump(mode="json"), side=side, known_at=cutoff.isoformat())
            ),
            side=side,
            level=str(level),
            zone_low=str(low),
            zone_high=str(high),
            stop=str(stop),
            atr=str(atr),
            known_at=cutoff.isoformat(),
            pivot_close=pivot.close_at.isoformat(),
            pivot_confirmed_at=max(b.available_at for b in h1[i - 2 : i + 3]).isoformat(),
            expires_at=min(
                pivot.close_at + timedelta(hours=self.rules.level_hours), window[1]
            ).isoformat(),
            trend=dict(ema=str(trend), prior_ema=str(prior), period=50),
            departed=m15[-1].close > high if buy else m15[-1].close < low,
            h1=encoded(h1[-16:]),
            m15=encoded(m15[-32:]),
            transitions=[],
            entry=None,
        )
        self.levels.add(identity)
        self.setups.append(setup)
        self.active = setup
        self.transition(setup, "LEVEL_KNOWN", cutoff, "CONFIRMED_H1_SWING_AND_TREND")
        return setup

    def candidate(self, base, setup, bar, cutoff, first, window, occupied):
        setup["entry"] = dict(
            at=cutoff.isoformat(),
            arm=self.rules.arm,
            disposition="POSITION_ALREADY_OPEN" if occupied else "PENDING_QUOTE",
        )
        if occupied:
            return dict(base, reason="POSITION_ALREADY_OPEN", setup_id=setup["setup_id"])
        expires = min(first[("M15", bar.close_at)] + timedelta(seconds=60), window[1])
        candidate = dict(
            base,
            action="CANDIDATE",
            setup_id=setup["setup_id"],
            side=setup["side"],
            signal_bar_close=bar.close_at.isoformat(),
            signal_price=str(bar.close),
            expires_at=expires.isoformat(),
            structural_stop=setup["stop"],
            reward_risk=str(self.rules.reward_risk),
            lifecycle_guard=self.rules.lifecycle_policy,
            time_exit_at=min(
                window[1], bar.close_at + timedelta(minutes=15 * self.rules.hold_bars)
            ).isoformat(),
        )
        self.last_candidate = candidate
        return candidate

    def entry_outcome(self, setup_id, **evidence):
        setup = next(s for s in self.setups if s["setup_id"] == setup_id)
        setup["entry"].update(evidence)

    def finish(self, end):
        if self.active and self.active["state"] not in TERMINAL:
            self.transition(self.active, "EXPIRED", end, "END_OF_STUDY_WINDOW")
        return dict(
            schema="structural-setups/1",
            rules=self.rules.model_dump(mode="json"),
            opportunities=self.setups,
            execution_enabled=False,
            economic_verdict="INSUFFICIENT_EVIDENCE",
        )
