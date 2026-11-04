"""Synthetic SDK seams; these tests do not connect to any terminal."""

from copy import deepcopy
from types import SimpleNamespace as NS

import pytest

from fx_talanta.connected_shadow.inputs import (
    GROUPS,
    canonical_hash,
    capture_once,
    normalize,
)
from fx_talanta.domain.models import AccountIdentity
from fx_talanta.observer.contracts import Binding
from fx_talanta.observer.mt5 import ObservationFailure
from fx_talanta.safety.risk import evaluate

NOW = 1793743200000


def binding():
    return Binding(
        account=AccountIdentity(
            environment="PAPER",
            venue="BROKER_DEMO",
            broker="synthetic",
            login="123",
            server="TEST-DEMO",
        ),
        source="MT5",
        terminal_path="C:/synthetic/terminal64.exe",
        data_path="C:/synthetic/data",
        expected_build=123,
        expected_currency="CAD",
        expected_company="Synthetic Company",
        expected_margin_mode=2,
        permissions_confirmed=True,
        permission_evidence="Synthetic test only",
    )


class SDK:
    __version__ = "5.0.6231"

    def __init__(self):
        self.calls = []
        self.terminal = NS(
            path="C:/synthetic",
            data_path="C:/synthetic/data",
            build=123,
            connected=True,
            trade_allowed=False,
        )
        self.account = NS(
            login=123,
            server="TEST-DEMO",
            trade_mode=0,
            currency="CAD",
            company="Synthetic Company",
            margin_mode=2,
            balance=10000.0,
            equity=10000.0,
            margin=0.0,
            margin_free=10000.0,
            margin_so_so=50.0,
            margin_so_mode=0,
        )
        self.visible = True
        self.tick_offset = 0
        self.positions = ()
        self.order_rows = ()
        self.mutate = False

    def initialize(self, *args, **kwargs):
        self.calls.append("initialize")
        return True

    def shutdown(self):
        self.calls.append("shutdown")

    def terminal_info(self):
        return self.terminal

    def account_info(self):
        return self.account

    def positions_get(self):
        return self.positions

    def orders_get(self):
        return self.order_rows

    def symbol_info(self, symbol):
        self.calls.append("symbol_info:" + symbol)
        return NS(
            visible=self.visible,
            currency_base=symbol[:3],
            currency_profit=symbol[3:],
            point=0.001 if symbol == "USDJPY" else 0.00001,
            trade_tick_size=0.001 if symbol == "USDJPY" else 0.00001,
            trade_tick_value_loss=0.90604 if symbol == "USDJPY" else 1.35,
            volume_min=0.01,
            volume_max=100.0,
            volume_step=0.01,
            trade_contract_size=100000.0,
            trade_stops_level=10,
            trade_freeze_level=5,
            trade_exemode=2,
            filling_mode=1,
        )

    def symbol_info_tick(self, symbol):
        self.calls.append("symbol_info_tick:" + symbol)
        bid, ask = {"EURUSD": (1.1, 1.1001), "USDJPY": (149.0, 149.01), "USDCAD": (1.35, 1.3502)}[
            symbol
        ]
        if self.mutate:
            self.account.trade_mode = 2
        return NS(bid=bid, ask=ask, time_msc=NOW - 500 + self.tick_offset)

    def order_calc_profit(self, action, symbol, volume, entry, stop):
        self.calls.append("order_calc_profit")
        conversion = 1.35 if symbol == "EURUSD" else 1.35 / entry
        return (stop - entry) * (1 if action == 0 else -1) * 100000 * volume * conversion

    def order_calc_margin(self, action, symbol, volume, entry):
        self.calls.append("order_calc_margin")
        return 100000 * volume * 1.35 / 30

    def order_send(self, *args, **kwargs):
        raise AssertionError("Order mutation reached")

    def symbol_select(self, *args, **kwargs):
        raise AssertionError("Symbol selection reached")

    def login(self, *args, **kwargs):
        raise AssertionError("Login switching reached")


def capture(sdk=None, **kwargs):
    return capture_once(
        sdk or SDK(),
        binding(),
        clock_error_ms=10,
        clock_evidence_sha256="a" * 64,
        conversion_symbol="USDCAD",
        process_check=lambda _: [123],
        now_ms=lambda: NOW,
        **kwargs,
    )


def context(raw):
    return dict(
        account_scope=raw["account_scope"],
        observed_at_ms=NOW - 100,
        valid_until_ms=NOW + 2000,
        values=dict(
            capital="10000",
            maximum_spread="0.01",
            maximum_adverse="0.01",
            request_volume="0.01",
            request_risk="25",
            commission="3",
            slippage="2",
            financing="1",
            commission_currency="CAD",
            day_start="10000",
            day_loss="0",
            cashflows_known=True,
            flags=0,
            occupied_slots=0,
            symbol_occupied=False,
            existing_risk="0",
            existing_gross="0",
            existing_margin="0",
            base_exposure="0",
            quote_exposure="0",
            other_exposure="0",
            stress_loss="0",
            blackout=False,
            session_open=True,
            inputs_ok=True,
        ),
        evidence={name: "e" * 64 for name in GROUPS},
    )


def test_real_fields_and_provenance_without_fabricated_costs_or_baselines():
    sdk = SDK()
    raw = capture(sdk)
    result = normalize(raw, symbol="EURUSD", side="BUY")
    assert result.reason == "DATA_HOLD" and result.snapshot is None
    assert set(result.missing) == {name.upper() for name in GROUPS}
    assert "day_start" not in result.observed_fields and "commission" not in result.observed_fields
    assert result.observed_fields["equity"] == "10000.0"
    assert result.observed_fields["usd_to_account"] == "1.3502"
    assert raw["quotes"]["EURUSD"]["raw_tick_ms"] == NOW - 500
    assert raw["quotes"]["EURUSD"]["age_upper_ms"] == 515
    assert result.provenance["conversion_tick_ms"] == NOW - 500
    assert sdk.calls.count("order_calc_profit") == sdk.calls.count("order_calc_margin") == 4
    assert sdk.calls[-1] == "shutdown"
    assert raw["sdk_calls"]["shutdown"] == 1


@pytest.mark.parametrize("symbol", ["EURUSD", "USDJPY"])
@pytest.mark.parametrize("side", ["BUY", "SELL"])
def test_evidenced_synthetic_context_assembles_real_observation_shape(symbol, side):
    raw = capture()
    result = normalize(raw, symbol=symbol, side=side, context=context(raw))
    assert not result.missing and result.snapshot is not None
    assert result.snapshot.currency == "CAD" and result.snapshot.clock_error_ms == 15
    assert evaluate(result.snapshot)["reason"] == "ACCEPTED"
    assert not result.provenance["qualified_for_trading"]


def test_missing_conversion_is_not_inferred_from_tick_value():
    raw = capture_once(
        SDK(),
        binding(),
        clock_error_ms=10,
        clock_evidence_sha256="a" * 64,
        process_check=lambda _: [123],
        now_ms=lambda: NOW,
    )
    result = normalize(raw, symbol="EURUSD", side="BUY", context=context(raw))
    assert result.snapshot is None and result.missing == ("CAD_CONVERSION",)
    assert "usd_to_account" not in result.observed_fields


@pytest.mark.parametrize(
    "change,reason",
    [
        (
            lambda s: setattr(s.terminal, "trade_allowed", True),
            "ALGORITHMIC_TRADING_MUST_BE_DISABLED",
        ),
        (lambda s: setattr(s, "visible", False), "SYMBOL_NOT_VISIBLE"),
        (lambda s: setattr(s, "mutate", True), "IDENTITY_MISMATCH"),
    ],
)
def test_capture_checks_identity_permissions_and_never_repairs_them(change, reason):
    sdk = SDK()
    change(sdk)
    with pytest.raises(ObservationFailure, match=reason):
        capture(sdk)
    assert sdk.calls[-1] == "shutdown"


def test_expired_or_wrong_scope_context_and_overrides_fail_closed():
    raw = capture()
    for key, value in (("account_scope", "0" * 64), ("valid_until_ms", NOW)):
        ctx = context(raw)
        ctx[key] = value
        with pytest.raises(ValueError, match="CONTEXT_BINDING_OR_TIME"):
            normalize(raw, symbol="EURUSD", side="BUY", context=ctx)
    ctx = context(raw)
    ctx["values"]["bid"] = "2"
    with pytest.raises(ValueError, match="OVERRIDE"):
        normalize(raw, symbol="EURUSD", side="BUY", context=ctx)


def test_stale_ticks_do_not_inherit_healthy_connection_or_clock():
    sdk = SDK()
    sdk.tick_offset = -2000
    raw = capture(sdk)
    result = normalize(raw, symbol="EURUSD", side="BUY", context=context(raw))
    assert evaluate(result.snapshot)["reason"] == "QUOTE_STALE"


def test_capture_tampering_and_missing_evidence_are_rejected():
    raw = capture()
    changed = deepcopy(raw)
    changed["quotes"]["EURUSD"]["bid"] = "2"
    with pytest.raises(ValueError, match="HASH_MISMATCH"):
        normalize(changed, symbol="EURUSD", side="BUY")
    ctx = context(raw)
    ctx["evidence"].pop("costs")
    result = normalize(raw, symbol="EURUSD", side="BUY", context=ctx)
    assert result.snapshot is None and result.missing == ("COSTS",)


def test_actual_margin_cannot_be_omitted_by_context():
    raw = capture()
    raw["account"]["margin"] = "50"
    raw["capture_sha256"] = canonical_hash({k: v for k, v in raw.items() if k != "capture_sha256"})
    with pytest.raises(ValueError, match="MARGIN_UNDERCOUNT"):
        normalize(raw, symbol="EURUSD", side="BUY", context=context(raw))


def test_no_existing_process_or_bad_conversion_scope_never_initializes():
    sdk = SDK()
    with pytest.raises(ObservationFailure, match="RUNNING_TERMINAL_REQUIRED"):
        capture_once(
            sdk,
            binding(),
            clock_error_ms=10,
            clock_evidence_sha256="a" * 64,
            process_check=lambda _: [],
            now_ms=lambda: NOW,
        )
    assert not sdk.calls


def test_clock_changes_and_process_changes_are_not_repaired(monkeypatch):
    ticks = iter((NOW, NOW + 100))
    monkeypatch.setattr("fx_talanta.connected_shadow.inputs.time.monotonic_ns", lambda: 0)
    sdk = SDK()
    with pytest.raises(ObservationFailure, match="HOST_CLOCK_CHANGED"):
        capture_once(
            sdk,
            binding(),
            clock_error_ms=10,
            clock_evidence_sha256="a" * 64,
            process_check=lambda _: [123],
            now_ms=lambda: next(ticks),
        )
    assert sdk.calls[-1] == "shutdown"
    pids = iter(([123], [456]))
    sdk = SDK()
    with pytest.raises(ObservationFailure, match="TERMINAL_PROCESS_CHANGED"):
        capture_once(
            sdk,
            binding(),
            clock_error_ms=10,
            clock_evidence_sha256="a" * 64,
            process_check=lambda _: next(pids),
            now_ms=lambda: NOW,
        )
    assert sdk.calls == ["shutdown"]


def test_exposure_is_captured_and_cannot_be_suppressed_by_a_context():
    sdk = SDK()
    sdk.positions = (
        NS(
            ticket=1,
            symbol="EURUSD",
            type=0,
            volume=0.01,
            sl=1.099,
            tp=1.102,
            price_open=1.1001,
            magic=100,
        ),
    )
    raw = capture(sdk)
    ctx = context(raw)
    with pytest.raises(ValueError, match="EXPOSURE_UNDERCOUNT"):
        normalize(raw, symbol="EURUSD", side="BUY", context=ctx)
    ctx["values"]["occupied_slots"] = 1
    with pytest.raises(ValueError, match="SYMBOL_EXPOSURE_OMITTED"):
        normalize(raw, symbol="EURUSD", side="BUY", context=ctx)


def test_bad_conversion_scope_never_initializes():
    sdk = SDK()
    with pytest.raises(ValueError, match="PINNED_USDCAD_REQUIRED"):
        capture_once(
            sdk,
            binding(),
            clock_error_ms=10,
            clock_evidence_sha256="a" * 64,
            conversion_symbol="AAPL",
            process_check=lambda _: [123],
            now_ms=lambda: NOW,
        )
    assert not sdk.calls
