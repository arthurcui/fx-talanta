from datetime import UTC, datetime, timedelta
from decimal import Decimal as D
from uuid import uuid4

import pytest

from fx_talanta.clock import FakeClock
from fx_talanta.domain.models import AccountIdentity
from fx_talanta.domain.offline import BrokerRequest, Fault, Instrument, Market, Quote
from fx_talanta.research.broker_costs import BrokerCosts, BrokerCostSimulator
from fx_talanta.research.replay import Experiment, digest, run
from fx_talanta.research.store import ReplayStore
from tools.fixtures.b01_replay import scenario
from tools.qualification.session_report import reconcile_fills

START = datetime(2025, 1, 8, 21, tzinfo=UTC)  # Wednesday, before 17:00 New York.
CUTOFF = START + timedelta(hours=1)


def test_legacy_result_and_journal_match_pre_integration_engine():
    result, journal = run(*scenario(), "training")
    assert digest(result) == "a1c9aa890db891d2670d0ec5de7ee4b4fdd654007a21082d12fa88112bb1d6f2"
    assert digest(journal) == "53a32cc7b0fc69052a2b4602eed6750f21b86116c6d3552667c5abf035ead7f7"


def profile(start=START, end=None, rows=None, **updates):
    end = end or start + timedelta(hours=3)
    rows = (
        rows
        if rows is not None
        else [
            {
                "cutoff": CUTOFF,
                "available_at": START,
                "multiplier": 3,
                "buy_usd_per_lot": "-5",
                "sell_usd_per_lot": "2",
                "evidence": "synthetic day rate",
            }
        ]
    )
    return BrokerCosts.model_validate(
        {
            "version": "broker-costs/1",
            "symbol": "EURUSD",
            "account_currency": "USD",
            "broker": "synthetic",
            "account_plan": "synthetic USD-notional",
            "status": "SYNTHETIC",
            "evidence": "constructed fee schedule",
            "basis": "fixture only",
            "valid_from": start,
            "valid_until": end,
            "available_at": start,
            "commission_usd_per_100k": "7",
            "slippage_per_lot_per_side": "2",
            "commission_reserve_per_lot_per_side": "10",
            "financing_reserve_per_lot": "15",
            "rollover_convention": "NEW_YORK_17_WEEKDAYS_EXPLICIT_MULTIPLIERS",
            "swap_days": rows,
            **updates,
        }
    )


def market(at, symbol="EURUSD", price="1.1"):
    pip = D(".0001") if symbol == "EURUSD" else D(".01")
    price = D(price)
    return Market(
        at=at,
        quotes=(Quote(symbol=symbol, bid=price, ask=price + pip, at=at),),
        instruments=(
            Instrument(
                symbol=symbol,
                base=symbol[:3],
                quote=symbol[3:],
                minimum_stop=pip,
                maximum_spread=pip * 3,
                maximum_adverse_move=pip * 5,
            ),
        ),
        conversion={
            "USD": D(1),
            "EUR" if symbol == "EURUSD" else "JPY": price
            if symbol == "EURUSD"
            else D(1) / (price + pip),
        },
    )


def broker(costs=None):
    account = AccountIdentity(
        environment="PAPER", venue="SIMULATOR", broker="REPLAY", server="OFFLINE", login="TEST"
    )
    clock = FakeClock(START)
    store = ReplayStore(account, uuid4(), clock)
    return BrokerCostSimulator(store, D(10000), costs or profile())


def enter(b, side="BUY", volume="1", symbol="EURUSD"):
    return BrokerRequest(
        account=b.store.account,
        request_id=uuid4(),
        entry_id=uuid4(),
        action="ENTER",
        symbol=symbol,
        volume=volume,
        side=side,
        stop="1.0",
        target="2.0",
    )


def close(b, volume="1"):
    p = b.book.positions[0]
    return BrokerRequest(
        account=b.store.account,
        request_id=uuid4(),
        entry_id=p.entry_id,
        position_id=p.position_id,
        expected_version=p.version,
        action="CLOSE",
        symbol=p.symbol,
        volume=volume,
    )


def test_fill_notional_each_leg_and_intraday_no_swap():
    b = broker()
    b.mutate(enter(b), market(START))
    assert b.book.deals[-1].commission == D("7.70084")
    b.store.clock.advance(timedelta(minutes=1))
    b.mutate(close(b), market(b.store.clock.now(), price="1.2"))
    assert b.book.deals[-1].commission == D("8.39986")
    assert b.financing == []
    assert b.book.balance == D(10000) + sum(d.realized for d in b.book.deals)


@pytest.mark.parametrize("side,cash", [("BUY", D(-15)), ("SELL", D(6))])
def test_rollover_posts_before_close_once_and_changes_equity(side, cash):
    b = broker()
    b.mutate(enter(b, side), market(START))
    before = b.book.balance
    b.store.clock.advance(timedelta(hours=1))
    b.accrue(CUTOFF)
    assert b.book.balance == before + cash
    b.accrue(CUTOFF)
    assert b.book.balance == before + cash
    b.mutate(close(b), market(CUTOFF))
    assert len(b.financing) == 1
    assert b.book.balance == D(10000) + sum(d.realized for d in b.book.deals) + cash
    assert not b.book.cash_flows  # Financing is trading PnL, never an external deposit.


def test_partial_volume_at_cutoff_and_rejection_does_not_create_fees():
    b = broker()
    b.next_fault = Fault(kind="REJECT")
    b.mutate(enter(b), market(START))
    assert not b.book.deals and not b.fill_costs
    b.next_fault = Fault(kind="PARTIAL", fraction="0.5")
    b.mutate(enter(b), market(START))
    assert b.book.deals[-1].commission == D("3.850420")
    b.mutate(close(b, ".2"), market(START))
    b.store.clock.advance(timedelta(hours=1))
    b.accrue(CUTOFF)
    assert D(b.financing[0]["charge"]) == D("4.5")  # Remaining 0.3 lot only.
    with pytest.raises(ValueError, match="remainder"):
        b.settle_entry(None, None)


def test_cutoff_entry_does_not_pay_just_elapsed_rollover():
    b = broker()
    b.store.clock.advance(timedelta(hours=1))
    b.mutate(enter(b), market(CUTOFF))
    b.accrue(CUTOFF + timedelta(seconds=1))
    assert b.financing == []
    with pytest.raises(ValueError, match="reset"):
        BrokerCostSimulator(b.store, D(10000), b.costs)


def test_missing_late_rates_currency_and_insufficient_reserves_fail_closed():
    for updates in (
        {"rows": []},
        {"account_currency": "CAD"},
        {"financing_reserve_per_lot": "14"},
        {"status": "QUALIFIED"},
    ):
        with pytest.raises(ValueError):
            profile(**updates)
    with pytest.raises(ValueError, match="unavailable"):
        profile(
            rows=[
                {
                    "cutoff": CUTOFF,
                    "available_at": CUTOFF + timedelta(seconds=1),
                    "multiplier": 3,
                    "buy_usd_per_lot": "-5",
                    "sell_usd_per_lot": "2",
                    "evidence": "late",
                }
            ]
        )
    with pytest.raises(ValueError, match="commission"):
        profile(commission_reserve_per_lot_per_side="1").price_risk(market(START))


def test_usdjpy_commission_uses_usd_base_not_yen_price():
    b = broker(profile(symbol="USDJPY"))
    b.mutate(enter(b, symbol="USDJPY"), market(START, "USDJPY", "150"))
    assert b.book.deals[-1].commission == D(7)
    wrong = broker()
    with pytest.raises(ValueError, match="symbol"):
        wrong.mutate(enter(wrong, symbol="USDJPY"), market(START, "USDJPY", "150"))
    assert not wrong.book.deals


def test_full_replay_accepts_new_profile_and_reconstructs_ledger():
    data, old = scenario()
    costs = profile(old.start, old.end, rows=[])
    experiment = Experiment.model_validate({**old.model_dump(), "costs": costs.model_dump()})
    result, journal = run(data, experiment, "training")
    assert result["cost_model"] == "broker-costs/1"
    assert result["cost_qualification"] == "SYNTHETIC"
    assert result["fully_settled"] and not result["execution_enabled"]
    assert result["metrics"]["closed_trades"] == 1
    assert reconcile_fills(result)["balance_from_fills"]
    assert journal


def test_replay_posts_cutoff_inside_quote_gap_before_later_exit():
    from tools.fixtures.broker_cost_replay import scenario as rollover_scenario

    data, experiment = rollover_scenario()
    result, journal = run(data, experiment, "training")
    assert result["fully_settled"]
    assert len(result["financing"]) == 1
    posting = result["financing"][0]
    assert posting["cutoff"] == posting["posted_at"] == "2025-01-08T22:00:00+00:00"
    assert D(posting["charge"]) == D(posting["volume"]) * 15
    assert result["financing_equity_samples"] == 1
    assert len(result["equity_samples"]) == len(data.events) + 1
    assert reconcile_fills(result)["balance_from_fills"]
    assert [
        x["payload"]["posting"] for x in journal if x["payload"]["stream"] == "financing"
    ] == result["financing"]
    assert result["deals"][-1]["at"] > "2025-01-08T22:00:00Z"


def test_rollover_after_last_quote_marks_unresolved_exposure_and_stream_verifies(tmp_path):
    from uuid import uuid4

    from fx_talanta.research.replay import digest, execute_timeline
    from fx_talanta.research.session_study import timeline, verify_phase, write
    from fx_talanta.research.spool import EquitySpool, Spool
    from tools.fixtures.broker_cost_replay import scenario as rollover_scenario

    data, experiment = rollover_scenario()
    start, end = experiment.window("training")
    journal = Spool(tmp_path / "journal.jsonl.gz")
    equity = EquitySpool(tmp_path / "equity.jsonl.gz", experiment.policy.capital)
    result, _ = execute_timeline(
        data,
        experiment,
        "training",
        timeline(data.bars, data.events[:4], start, end),
        uuid4(),
        journal_sink=journal,
        samples_sink=equity,
    )
    journal.close()
    equity.close()
    result["coverage"] = {"ticks": 4}
    assert not result["fully_settled"]
    assert result["financing_equity_samples"] == 1
    assert reconcile_fills(result)["balance_from_fills"]
    write(tmp_path / "result.json", result)
    write(
        tmp_path / "receipt.json",
        {
            "manifest_hash": digest({}),
            "result_hash": digest(result),
            "journal": journal.receipt(),
            "equity": equity.receipt(),
        },
    )
    assert verify_phase(tmp_path, {}, full=True) == result


def test_summer_dst_and_holiday_multiplier_are_explicit():
    start = datetime(2025, 7, 9, 20, tzinfo=UTC)
    row = {
        "cutoff": start + timedelta(hours=1),
        "available_at": start,
        "multiplier": 4,
        "buy_usd_per_lot": "-2",
        "sell_usd_per_lot": "1",
        "evidence": "fixture holiday override",
    }
    costs = profile(start, rows=[row])
    assert costs.swap_days[0].cutoff.hour == 21
    assert costs.swap_days[0].multiplier == 4
    with pytest.raises(ValueError, match="cutoff"):
        profile(start, rows=[{**row, "cutoff": start + timedelta(hours=2)}])
