from datetime import UTC, datetime

import pytest

from fx_talanta.connected_shadow.host_clock import HostClock

NOW = 1_767_614_400_000
MS = 1_000_000


def report(error=10):
    return dict(
        passed=True,
        error_bound_ms=error,
        checked_at=datetime.fromtimestamp(NOW / 1000, UTC).isoformat(),
    )


def test_bracketed_scheduling_delay_increases_error_without_false_clock_step():
    # Wall is sampled at the beginning of a 20ms scheduling gap during both
    # initialization and the next read. Actual UTC at the read's end is NOW+120.
    wall = iter((NOW * MS, (NOW + 100) * MS))
    mono = iter((0, 20 * MS, 100 * MS, 120 * MS))
    clock = HostClock(report(), wall=lambda: next(wall), monotonic=lambda: next(mono))
    value, error = clock.read()
    assert value == NOW + 110
    assert error == 26
    assert value - error <= NOW + 120 <= value + error


def test_oversized_sample_is_delayed_not_evidence_of_clock_change():
    wall = iter((NOW * MS, (NOW + 100) * MS))
    mono = iter((0, 0, 100 * MS, 300 * MS))
    clock = HostClock(report(), wall=lambda: next(wall), monotonic=lambda: next(mono))
    with pytest.raises(ValueError, match="SAMPLE_DELAYED"):
        clock.read()


def test_clock_step_and_monotonic_regression_are_sticky():
    wall, mono = [NOW * MS], [0]
    clock = HostClock(report(), wall=lambda: wall[0], monotonic=lambda: mono[0])
    assert clock.read() == (NOW, 15)
    wall[0] += 7 * MS
    with pytest.raises(ValueError, match="CHANGED"):
        clock.read()
    wall[0] -= 7 * MS
    with pytest.raises(ValueError, match="CHANGED"):
        clock.read()  # Fresh independent NTP evidence is required to reinitialize.
    clock = HostClock(report(), wall=lambda: wall[0], monotonic=lambda: mono[0])
    wall[0] += 10 * MS
    mono[0] += 10 * MS
    clock.read()
    mono[0] -= 1
    with pytest.raises(ValueError, match="REGRESSION"):
        clock.read()


def test_expiry_counts_evidence_age_and_requires_aware_fresh_passed_evidence():
    wall, mono = [(NOW + 4000) * MS], [0]
    clock = HostClock(report(), wall=lambda: wall[0], monotonic=lambda: mono[0])
    assert clock.read()[1] == 16
    wall[0] += 56000 * MS
    mono[0] += 56000 * MS
    with pytest.raises(ValueError, match="EXPIRED"):
        clock.read()
    for bad in (report() | {"passed": "yes"}, report(float("nan")), report(True), report(96)):
        with pytest.raises(ValueError, match="UNVERIFIED"):
            HostClock(bad)
    with pytest.raises(ValueError, match="TIMEZONE"):
        HostClock(report() | {"checked_at": "2026-01-05T12:00:00"})


def test_fractional_millisecond_quantization_is_included():
    clock = HostClock(report(), wall=lambda: NOW * MS + 900000, monotonic=lambda: 0)
    assert clock.read() == (NOW, 17)  # Evidence age drift and sub-ms rounding both count.
