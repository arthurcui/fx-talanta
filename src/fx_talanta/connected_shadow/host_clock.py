"""NTP-corroborated host UTC intervals without changing the operating-system clock.

Wall sampling is bracketed by monotonic readings. Scheduling delay contributes
uncertainty instead of being mislabeled as a host-clock adjustment. This is a
short-lived development measurement, not a continuously synchronized time service.
"""

import math
import threading
import time
from datetime import datetime

MS = 1_000_000
MAX_LIFETIME_NS = 60_000 * MS
STEP_GUARD_NS = 5 * MS


class HostClock:
    def __init__(self, report, *, wall=time.time_ns, monotonic=time.monotonic_ns):
        self.wall, self.monotonic = wall, monotonic
        self._lock = threading.Lock()
        self.invalid_reason = None
        error = report.get("error_bound_ms")
        if (
            report.get("passed") is not True
            or type(error) not in {int, float}
            or not math.isfinite(error)
            or not 0 <= error <= 95
        ):
            raise ValueError("HOST_CLOCK_UNVERIFIED")
        checked = datetime.fromisoformat(report["checked_at"])
        if checked.tzinfo is None or checked.utcoffset() is None:
            raise ValueError("HOST_CLOCK_EVIDENCE_TIMEZONE")
        self.anchor_wall, self.anchor_before, self.anchor_after = self._sample()
        self.anchor_mid = (self.anchor_before + self.anchor_after) // 2
        self.anchor_half = (self.anchor_after - self.anchor_before + 1) // 2
        self.checked_ns = int(checked.timestamp() * 1000) * MS
        self.evidence_age = self.anchor_wall - self.checked_ns
        if not 0 <= self.evidence_age <= 5000 * MS:
            raise ValueError("HOST_CLOCK_EVIDENCE_EXPIRED")
        self.base_error = math.ceil(error) + 5
        self.last_mono = self.anchor_after

    def _sample(self):
        before = self.monotonic()
        wall = self.wall()
        after = self.monotonic()
        if any(type(v) is not int or v < 0 for v in (before, wall, after)) or after < before:
            raise ValueError("HOST_CLOCK_REGRESSION")
        return wall, before, after

    def _fail(self, reason):
        self.invalid_reason = reason
        raise ValueError(reason)

    def read(self):
        with self._lock:
            if self.invalid_reason:
                raise ValueError(self.invalid_reason)
            try:
                wall, before, after = self._sample()
            except ValueError:
                self._fail("HOST_CLOCK_REGRESSION")
            elapsed = after - self.anchor_after
            if before < self.last_mono or elapsed < 0:
                self._fail("HOST_CLOCK_REGRESSION")
            if elapsed + self.evidence_age >= MAX_LIFETIME_NS:
                self._fail("HOST_CLOCK_EVIDENCE_EXPIRED")
            midpoint = (before + after) // 2
            half = (after - before + 1) // 2
            # 100 ppm allowance is independent of the five-ms step guard.
            drift_ns = (elapsed + 9999) // 10000
            residual = abs(wall - self.anchor_wall - (midpoint - self.anchor_mid))
            if residual > STEP_GUARD_NS + self.anchor_half + half + drift_ns:
                self._fail("HOST_CLOCK_CHANGED")
            # At sample completion, actual UTC is in [wall, wall + width] plus
            # the independently measured NTP error and explicit drift allowance.
            estimate_ns = wall + (after - before) // 2
            uncertainty = (
                self.base_error
                + math.ceil((elapsed + self.evidence_age) / (10000 * MS))
                + math.ceil(half / MS)
                + int(bool(estimate_ns % MS))
            )
            if uncertainty > 100:
                self._fail("HOST_CLOCK_SAMPLE_DELAYED" if half else "HOST_CLOCK_UNVERIFIED")
            self.last_mono = after
            return estimate_ns // MS, uncertainty
