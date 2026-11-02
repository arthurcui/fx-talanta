from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace as NS
from uuid import uuid4

import psycopg
import pytest
from psycopg.types.json import Jsonb

from fx_talanta.clock import FakeClock
from fx_talanta.domain.models import AccountIdentity, Environment, Record, TerminalObservation
from fx_talanta.observer.contracts import Binding
from fx_talanta.observer.fixtures import FixtureReader
from fx_talanta.observer.mt5 import MT5Reader, ObservationFailure, ReadOnlySDK, read_snapshot
from fx_talanta.observer.supervisor import Observer, assess
from fx_talanta.storage.archive import (
    export_archive,
    read_archive,
    release_restore,
    restore_archive,
)
from fx_talanta.storage.bootstrap import bootstrap
from fx_talanta.storage.repository import Repository

NOW = datetime(2026, 1, 5, 12, tzinfo=UTC)


@pytest.fixture
def demo_binding():
    return Binding(
        account=AccountIdentity(
            environment="PAPER",
            venue="BROKER_DEMO",
            broker="test-only-dealer",
            server="TEST-DEMO",
            login="12345",
        ),
        source="MT5",
        terminal_path="C:/test/terminal64.exe",
        data_path="C:/test/data",
        expected_build=123,
        expected_currency="USD",
        expected_company="Test Company",
        expected_margin_mode=2,
        permissions_confirmed=True,
        permission_evidence="synthetic test permission; not a real dealer approval",
    )


class FakeSDK:
    __version__ = "5.0.6231"
    TIMEFRAME_M15, TIMEFRAME_H1 = 15, 16385

    def __init__(self):
        self.calls = []
        self.account = NS(
            login=12345,
            trade_mode=0,
            server="TEST-DEMO",
            currency="USD",
            company="Test Company",
            margin_mode=2,
            balance=10000.0,
            equity=10000.0,
        )
        self.terminal = NS(path="C:/test", data_path="C:/test/data", build=123, connected=True)
        self.none_positions = False
        self.switch_during_quotes = False
        self.count = 0

    def initialize(self, path, **kwargs):
        self.calls.append(("initialize", path, kwargs))
        return True

    def shutdown(self):
        self.calls.append(("shutdown",))

    def account_info(self):
        return self.account

    def terminal_info(self):
        return self.terminal

    def symbol_info(self, symbol):
        return NS(visible=True, digits=5, volume_min=0.01, volume_step=0.01, point=0.00001)

    def symbol_info_tick(self, symbol):
        if self.switch_during_quotes:
            self.account.trade_mode = 2
        return NS(time_msc=int(NOW.timestamp() * 1000), bid=1.10, ask=1.1001)

    def copy_rates_from_pos(self, symbol, timeframe, start, count):
        assert start == 1 and count == 2
        period = 900 if timeframe == self.TIMEFRAME_M15 else 3600
        return [
            dict(
                time=int((NOW - timedelta(seconds=period * n)).timestamp()),
                open=1.1,
                high=1.2,
                low=1.0,
                close=1.1,
            )
            for n in (2, 1)
        ]

    def positions_get(self):
        return None if self.none_positions else ()

    def orders_get(self):
        return ()

    def history_deals_get(self, start, end):
        return ()

    def history_orders_get(self, start, end):
        return ()

    def history_deals_total(self, start, end):
        return self.count

    def history_orders_total(self, start, end):
        return 0

    def order_send(self, *args, **kwargs):
        raise AssertionError("order mutation reached")

    def login(self, *args, **kwargs):
        raise AssertionError("account switching reached")


def snapshot(binding, sdk=None):
    return read_snapshot(sdk or FakeSDK(), binding, NOW, finished_at=NOW)


def test_read_only_snapshot_and_no_credentials(demo_binding):
    sdk = FakeSDK()
    result = snapshot(demo_binding, sdk)
    assert assess(result, demo_binding, NOW) == "CURRENT"
    assert result.account_before == result.account_after == demo_binding.account
    assert result.history_complete and result.positions == result.deals == ()
    assert result.balance == 10000 and len(result.bars) == 8
    assert set(sdk.calls[0][2]) == {"timeout"}
    assert sdk.calls[-1] == ("shutdown",)
    for name in ("login", "order_send", "symbol_select", "market_book_add"):
        with pytest.raises(ValueError, match="allowlist"):
            ReadOnlySDK(sdk).call(name)


@pytest.mark.parametrize(
    "field,value,reason",
    [
        ("login", 999, "IDENTITY_MISMATCH"),
        ("server", "TEST-LIVE", "IDENTITY_MISMATCH"),
        ("trade_mode", 2, "IDENTITY_MISMATCH"),
        ("currency", "CAD", "CURRENCY_MISMATCH"),
        ("margin_mode", 0, "MODE_MISMATCH"),
        ("company", "Other", "COMPANY_MISMATCH"),
    ],
)
def test_account_fencing(demo_binding, field, value, reason):
    sdk = FakeSDK()
    setattr(sdk.account, field, value)
    with pytest.raises(ObservationFailure, match=reason):
        snapshot(demo_binding, sdk)
    assert sdk.calls[-1] == ("shutdown",)


@pytest.mark.parametrize(
    "field,value,reason",
    [
        ("path", "C:/other", "PATH_MISMATCH"),
        ("data_path", "C:/other", "PATH_MISMATCH"),
        ("build", 124, "BUILD_CHANGED"),
        ("connected", False, "DISCONNECTED"),
    ],
)
def test_terminal_fencing(demo_binding, field, value, reason):
    sdk = FakeSDK()
    setattr(sdk.terminal, field, value)
    with pytest.raises(ObservationFailure, match=reason):
        snapshot(demo_binding, sdk)


def test_permissions_and_version_gate_before_initialization(demo_binding):
    sdk = FakeSDK()
    with pytest.raises(ValueError, match="permissions"):
        snapshot(demo_binding.model_copy(update={"permissions_confirmed": False}), sdk)
    assert sdk.calls == []
    sdk.__version__ = "unqualified"
    with pytest.raises(ObservationFailure, match="SDK_MISMATCH"):
        snapshot(demo_binding, sdk)
    assert sdk.calls == []


def test_mid_read_live_switch_and_missing_history_fail_closed(demo_binding):
    sdk = FakeSDK()
    sdk.switch_during_quotes = True
    with pytest.raises(ObservationFailure, match="IDENTITY_MISMATCH"):
        snapshot(demo_binding, sdk)
    sdk = FakeSDK()
    sdk.none_positions = True
    with pytest.raises(ObservationFailure, match="READER_FAILED"):
        snapshot(demo_binding, sdk)
    sdk = FakeSDK()
    sdk.count = 1
    with pytest.raises(ObservationFailure, match="MISSING_DATA"):
        snapshot(demo_binding, sdk)


def test_demo_provenance_rejects_fixture_labels(demo_binding):
    body = TerminalObservation(
        binding_hash=demo_binding.fingerprint(),
        state="HEALTHY",
        reason="CURRENT",
        failures=0,
        last_success_at=NOW,
        snapshot=snapshot(demo_binding),
    )
    with pytest.raises(ValueError, match="broker observation"):
        Record(account=demo_binding.account, recorded_at=NOW, correlation_id=uuid4(), body=body)


def test_history_boundaries_cashflow_fees_and_order_types(demo_binding):
    sdk = FakeSDK()
    binding = demo_binding.model_copy(update={"history_hours": 2})
    # Inclusive hourly windows return the boundary deal twice; retain it once.
    boundary = int((NOW - timedelta(hours=1)).timestamp())
    deal = NS(
        ticket=100,
        symbol="EURUSD",
        type=0,
        time=boundary,
        volume=0.1,
        price=1.1,
        profit=12.5,
        commission=-0.25,
        swap=-0.1,
        fee=-0.05,
        position_id=9,
        order=10,
    )
    cashflow = NS(
        ticket=101,
        symbol="",
        type=2,
        time=boundary,
        volume=0,
        price=0,
        profit=10000,
        commission=0,
        swap=0,
        fee=0,
        position_id=0,
        order=0,
    )
    old_order = NS(
        ticket=10,
        symbol="EURUSD",
        type=2,
        time_setup=boundary - 7200,
        time_done=boundary,
        volume_current=0,
        volume_initial=0.1,
        price_open=1.1,
        sl=1.0,
        tp=1.2,
        state=4,
        position_id=9,
    )
    sdk.history_deals_get = lambda start, end: (deal, cashflow)
    sdk.history_deals_total = lambda start, end: 2
    sdk.history_orders_get = lambda start, end: (old_order,)
    sdk.history_orders_total = lambda start, end: 1
    result = snapshot(binding, sdk)
    assert len(result.deals) == 2 and len(result.history_orders) == 1
    assert str(result.deals[0].commission) == "-0.25"
    assert result.deals[1].side == "OTHER" and result.deals[1].profit == 10000
    assert result.history_orders[0].side == "BUY"
    assert result.history_orders[0].initial_volume == result.deals[0].volume
    assert result.history_orders[0].done_at == result.deals[0].at


def test_cli_permission_gate_before_database_or_sdk(demo_binding, tmp_path, monkeypatch, capsys):
    import sys

    from fx_talanta.cli import main

    binding_path = tmp_path / "binding.json"
    binding_path.write_text(
        demo_binding.model_copy(update={"permissions_confirmed": False}).model_dump_json()
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["fx-talanta", "--binding", str(binding_path), "observe", "--run-id", str(uuid4())],
    )
    with pytest.raises(SystemExit):
        main()
    assert "permissions" in capsys.readouterr().err


@pytest.mark.integration
def test_demo_storage_archive_and_restore(settings, demo_binding, tmp_path):
    source = replace(settings, namespace="fx_mt5_src_" + uuid4().hex[:10])
    target = replace(settings, namespace="fx_mt5_dst_" + uuid4().hex[:10])
    account = demo_binding.account
    bootstrap(source, paper_account=account)
    bootstrap(target, paper_account=account)
    with pytest.raises(ValueError, match="different account binding"):
        bootstrap(source)  # cannot adopt a demo database as the simulator
    with pytest.raises(ValueError, match="different account binding"):
        bootstrap(source, paper_account=account.model_copy(update={"login": "999"}))
    repo = Repository(source.runtime_dsn(Environment.PAPER), account)
    run_id = uuid4()
    repo.append(
        Record(
            account=account,
            recorded_at=NOW,
            correlation_id=run_id,
            provenance="BROKER_OBSERVATION",
            body=TerminalObservation(
                binding_hash=demo_binding.fingerprint(),
                state="HEALTHY",
                reason="CURRENT",
                failures=0,
                last_success_at=NOW,
                snapshot=snapshot(demo_binding),
            ),
        )
    )
    record = Record(
        account=account,
        recorded_at=NOW,
        correlation_id=run_id,
        provenance="BROKER_OBSERVATION",
        body=TerminalObservation(
            binding_hash=demo_binding.fingerprint(),
            state="HALTED",
            reason="BUILD_CHANGED",
            failures=1,
        ),
    )
    repo.append(record)
    payload = record.model_dump(mode="json")
    payload["record_id"] = str(uuid4())
    payload["provenance"] = "SCRIPTED_FIXTURE"
    with psycopg.connect(source.runtime_dsn(Environment.PAPER)) as conn:
        with pytest.raises(psycopg.errors.CheckViolation), conn.transaction():
            conn.execute(
                "INSERT INTO fx.records(record_id,kind,recorded_at,payload) "
                "VALUES (%s,'observation',%s,%s)",
                (payload["record_id"], NOW, Jsonb(payload)),
            )
    path = tmp_path / "demo.fxbackup"
    with pytest.raises(ValueError, match="explicit expectation"):
        export_archive(source, path)
    export_archive(source, path, paper_account=account)
    with pytest.raises(ValueError):
        read_archive(path)  # demo archives require explicit caller identity
    with pytest.raises(ValueError, match="binding"):
        read_archive(path, paper_account=account.model_copy(update={"login": "999"}))
    restore_archive(target, path, paper_account=account)
    release_restore(target, path, paper_account=account, source_retired=True)
    assert Repository(target.runtime_dsn(Environment.PAPER), account).history() == repo.history()
    observer = Observer(target.runtime_dsn(Environment.PAPER), demo_binding, run_id, FakeClock(NOW))
    try:
        assert observer.poll(MT5Reader()) == record  # halt survives without loading SDK
        with pytest.raises(ValueError, match="MT5 reader"):
            observer.poll(FixtureReader())
    finally:
        observer.close()
