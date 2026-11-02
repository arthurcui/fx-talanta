from datetime import UTC, datetime, timedelta
from typing import Protocol

from fx_talanta.domain.models import utc


class Clock(Protocol):
    def now(self) -> datetime: ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class FakeClock:
    def __init__(self, now: datetime):
        self._now = utc(now)

    def now(self) -> datetime:
        return self._now

    def advance(self, delta: timedelta) -> None:
        if delta < timedelta(0):
            raise ValueError("fixture clock cannot move backwards")
        self._now += delta
