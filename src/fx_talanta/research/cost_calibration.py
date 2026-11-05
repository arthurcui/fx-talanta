"""Explicit cost conventions for research preparation, not an execution cost feed.

Legacy replay costs remain unchanged. Published-current commission scenarios and
date-specific financing require separate provenance before use in historical replay.
"""

from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo


def positive(value):
    if not isinstance(value, Decimal) or not value.is_finite() or value <= 0:
        raise ValueError("finite positive Decimal required")
    return value


def commission(base_units, base_to_usd, usd_per_100k, usd_to_account):
    """One leg, without currency rounding; each leg needs its own dated FX rates."""
    if not isinstance(usd_per_100k, Decimal) or not usd_per_100k.is_finite():
        raise ValueError("finite Decimal commission required")
    if usd_per_100k < 0:
        raise ValueError("negative commission schedule")
    return (
        positive(base_units)
        * positive(base_to_usd)
        / Decimal(100000)
        * usd_per_100k
        * positive(usd_to_account)
    )


def forex_rollovers(opened, closed, *, holiday_multipliers):
    """FOREX 17:00 New York weekday convention; NOT a historical rate attestation.

    Caller must supply a reviewed holiday override map (an empty map is an explicit
    assertion of no exceptions). Rates and multipliers are pair/date dependent.
    Exact-cutoff fills need broker sequencing evidence and are rejected here.
    """
    if opened.utcoffset() is None or closed.utcoffset() is None or closed < opened:
        raise ValueError("ordered aware times required")
    if holiday_multipliers is None:
        raise ValueError("reviewed holiday calendar required")
    zone = ZoneInfo("America/New_York")
    start, end = opened.astimezone(zone), closed.astimezone(zone)
    for endpoint in (start, end):
        if (endpoint.hour, endpoint.minute, endpoint.second, endpoint.microsecond) == (17, 0, 0, 0):
            raise ValueError("exact-cutoff fill requires sequencing evidence")
    events = []
    day = start.date()
    while day <= end.date():
        cutoff = datetime(day.year, day.month, day.day, 17, tzinfo=zone)
        if start < cutoff < end and day.weekday() < 5:
            multiplier = holiday_multipliers.get(day, 3 if day.weekday() == 2 else 1)
            if isinstance(multiplier, bool) or not isinstance(multiplier, int) or multiplier < 0:
                raise ValueError("nonnegative integer rollover multiplier required")
            events.append((day, multiplier))
        day += timedelta(days=1)
    return events


def financing(lots, events, signed_daily_rates):
    """Signed account-currency cashflow; rates already selected for pair and side.

    Positive is credit, negative debit. A missing rate is never interpreted as zero.
    No rates are needed when the position crosses no rollover event.
    """
    positive(lots)
    total = Decimal(0)
    for day, multiplier in events:
        rate = signed_daily_rates[day]
        if not isinstance(rate, Decimal) or not rate.is_finite():
            raise ValueError("finite signed daily rate required")
        total += lots * rate * multiplier
    return total
