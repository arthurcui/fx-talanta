"""Short-lived UTC interval from an already authenticated server response.

The caller must establish server-clock validity, authentication and nonce binding
before calling sync. This module neither authenticates responses nor adjusts a
clock. GetTickCount64 has OS timer granularity, so the fixed 32 ms guard is an
explicit conservative counter assumption; fixture parity does not qualify a host.
"""

MAX_VALUE = 9_000_000_000_000_000
MAX_ERROR_MS = 100
LIFETIME_MS = 5000
TIMER_GUARD_MS = 32
DRIFT_PPM = 100


def _integer(value):
    return type(value) is int and 0 <= value <= MAX_VALUE


class ShadowClock:
    def __init__(self):
        self.valid = False
        self.reason = "CLOCK_UNVERIFIED"
        self._anchor_utc = self._anchor_mono = self._error = 0
        self._last_mono = self._last_utc = -1

    def _reject(self, reason):
        self.valid = False
        self.reason = reason
        return False

    def _estimate(self, mono):
        elapsed = mono - self._anchor_mono
        if not 0 <= elapsed < LIFETIME_MS:
            return None
        uncertainty = self._error + (elapsed * DRIFT_PPM + 999_999) // 1_000_000
        if uncertainty > MAX_ERROR_MS:
            return None
        return self._anchor_utc + elapsed, uncertainty

    def sync(self, server_ms, error_ms, sent_mono, recv_mono):
        """Pin response UTC to local monotonic time; malformed updates invalidate.

        server_ms must be sampled between request send and response receipt.
        RTT accounts for asymmetric network/processing delay without assuming a
        symmetric network. No RTT minimum is subtracted from quote age.
        """
        if not all(_integer(v) for v in (server_ms, error_ms, sent_mono, recv_mono)):
            return self._reject("CLOCK_UNVERIFIED")
        if sent_mono < self._last_mono or recv_mono < sent_mono:
            return self._reject("CLOCK_REGRESSION")
        if server_ms < 1 or server_ms > MAX_VALUE - LIFETIME_MS:
            return self._reject("CLOCK_UNVERIFIED")
        rtt = recv_mono - sent_mono
        if rtt > 2000 or error_ms > MAX_ERROR_MS:
            return self._reject("CLOCK_UNVERIFIED")
        midpoint = server_ms + rtt // 2
        uncertainty = error_ms + (rtt + 1) // 2 + TIMER_GUARD_MS
        if uncertainty > MAX_ERROR_MS:
            return self._reject("CLOCK_UNVERIFIED")
        previous = self._estimate(recv_mono) if self.valid else None
        if previous and (
            midpoint + uncertainty < previous[0] - previous[1]
            or midpoint - uncertainty > previous[0] + previous[1]
        ):
            return self._reject("CLOCK_INTERVAL_DISJOINT")
        if midpoint < self._last_utc:
            return self._reject("CLOCK_REGRESSION")
        self._anchor_utc, self._anchor_mono, self._error = midpoint, recv_mono, uncertainty
        self._last_mono, self._last_utc = recv_mono, midpoint
        self.valid, self.reason = True, "CLOCK_BOUNDED"
        return True

    def now(self, mono):
        """Return (UTC midpoint, error bound), or None. Invalidity is sticky."""
        if not self.valid:
            return None
        if not _integer(mono):
            self._reject("CLOCK_UNVERIFIED")
            return None
        if mono < self._last_mono:
            self._reject("CLOCK_REGRESSION")
            return None
        value = self._estimate(mono)
        if value is None:
            self._reject("CLOCK_EXPIRED")
            return None
        self._last_mono, self._last_utc = mono, value[0]
        return value
