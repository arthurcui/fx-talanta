import pytest

from fx_talanta.connected_shadow.clock import ShadowClock

STAMP = 1_800_000_000_000


def test_authenticated_time_interval_includes_rtt_and_counter_granularity():
    c = ShadowClock()
    assert c.now(1) is None
    assert c.sync(STAMP, 10, 1000, 1021)
    assert c.now(1021) == (STAMP + 10, 53)
    assert c.now(1022) == (STAMP + 11, 54)
    # It covers either extreme of asymmetric request/response delay.
    center, error = c.now(1022)
    assert center - error <= STAMP - 10 + 1
    assert center + error >= STAMP + 10 + 21 + 1


def test_exact_error_and_lifetime_boundaries_do_not_extend():
    c = ShadowClock()
    assert c.sync(STAMP, 68, 100, 100)
    assert c.now(100) == (STAMP, 100)
    assert c.now(101) is None  # Drift allowance breaches 100 ms.
    assert c.reason == "CLOCK_EXPIRED"
    assert c.sync(STAMP + 1, 10, 101, 101)
    assert c.now(5100) == (STAMP + 5000, 43)
    assert c.now(5101) is None
    assert c.now(200) is None  # Expiry does not revive on a smaller supplied time.


@pytest.mark.parametrize(
    "values",
    [
        (STAMP, 69, 1, 1),
        (STAMP, 0, 1, 138),
        (STAMP, 0, 1, 2002),
        (STAMP, -1, 1, 1),
        (STAMP, 0, 2, 1),
        (STAMP, 0, -1, 1),
        (0, 0, 1, 1),
        (9_000_000_000_000_000, 0, 1, 1),
        (STAMP, True, 1, 1),
        (STAMP, 0, 1.0, 1),
    ],
)
def test_invalid_sync_clears_previous_clock(values):
    c = ShadowClock()
    assert c.sync(STAMP, 0, 0, 0)
    assert not c.sync(*values)
    assert c.now(1) is None


def test_regressing_counter_and_overlapping_resync():
    c = ShadowClock()
    assert c.sync(STAMP, 10, 100, 120)
    assert c.now(200) == (STAMP + 90, 53)
    assert not c.sync(STAMP + 100, 10, 199, 201)
    assert c.reason == "CLOCK_REGRESSION"
    assert c.sync(STAMP + 100, 10, 200, 220)
    assert c.now(220) == (STAMP + 110, 52)
    assert c.now(219) is None
    assert c.reason == "CLOCK_REGRESSION"


def test_disjoint_server_time_update_invalidates_clock():
    c = ShadowClock()
    assert c.sync(STAMP, 10, 100, 120)
    assert not c.sync(STAMP + 10_000, 10, 200, 220)
    assert c.reason == "CLOCK_INTERVAL_DISJOINT"
    assert c.now(220) is None


def test_repeated_sync_never_reduces_observed_utc():
    c = ShadowClock()
    assert c.sync(STAMP, 10, 100, 120)
    assert c.now(200) == (STAMP + 90, 53)
    assert not c.sync(STAMP + 80, 10, 200, 200)
    assert c.reason == "CLOCK_REGRESSION"
