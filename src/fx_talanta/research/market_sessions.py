"""Versioned research session conventions, not exchange hours or liquidity guarantees."""

from datetime import UTC, datetime, time, timedelta
from functools import lru_cache
from importlib.resources import files
from zoneinfo import ZoneInfo

import tzdata

VERSION = "fx-sessions/1"
DEFINITIONS = {
    "TOKYO": ("Asia/Tokyo", 9, 18),
    "LONDON": ("Europe/London", 8, 17),
    "NEW_YORK": ("America/New_York", 8, 17),
}


@lru_cache
def zone(name):
    # Always use the packaged, pinned tzdb on Windows and Linux alike.
    with files("tzdata.zoneinfo").joinpath(*name.split("/")).open("rb") as stream:
        return ZoneInfo.from_file(stream, key=name)


def bounds(name, at):
    tzname, start, end = DEFINITIONS[name]
    local = at.astimezone(zone(tzname))
    begin = datetime.combine(local.date(), time(start), zone(tzname))
    finish = datetime.combine(local.date(), time(end), zone(tzname))
    return begin.astimezone(UTC), finish.astimezone(UTC)


def context(at):
    if at.tzinfo is None:
        raise ValueError("timezone-aware session timestamp required")
    active, minutes = [], {}
    for name in DEFINITIONS:
        start, end = bounds(name, at)
        if start.weekday() < 5 and start <= at < end:
            active.append(name)
            minutes[name] = int((at - start).total_seconds() // 60)
    return dict(
        version=VERSION,
        tzdata=tzdata.__version__,
        active=active,
        regime="+".join(active) or "OFF_SESSION",
        minutes_since_open=minutes,
    )


def entry_window(selection, at):
    c = context(at)
    if selection == "UTC_WINDOW":
        return None
    names = ["LONDON", "NEW_YORK"] if selection == "LONDON_NEW_YORK_OVERLAP" else [selection]
    if not all(name in c["active"] for name in names):
        return None
    windows = [bounds(name, at) for name in names]
    return max(w[0] for w in windows), min(w[1] for w in windows)


def reference_bars(mode, selection, bars, signal, period, at):
    preceding = [b for b in bars if b.close_at < signal.close_at]
    if mode == "ROLLING":
        chosen = preceding[-period:]
        return chosen if len(chosen) == period else []
    if mode == "CURRENT_SESSION":
        window = entry_window(selection, at)
        if window is None:
            return []
        start, end = window[0], signal.close_at - timedelta(minutes=15)
        chosen = [b for b in preceding if start < b.close_at <= end]
        return chosen if chosen and complete(chosen, start, end) else []
    # Only the latest fully completed Tokyo session; never a partial or weekend range.
    start, end = bounds("TOKYO", at)
    if end > signal.close_at - timedelta(minutes=15):
        start, end = bounds("TOKYO", at - timedelta(days=1))
    if start.weekday() >= 5 or at - end > timedelta(hours=24):
        return []
    chosen = [b for b in preceding if start < b.close_at <= end]
    return chosen if complete(chosen, start, end) else []


def complete(bars, start, end):
    expected = int((end - start).total_seconds() // 900)
    return (
        expected > 0
        and len(bars) == expected
        and all(b.close_at == start + timedelta(minutes=15 * (i + 1)) for i, b in enumerate(bars))
    )
