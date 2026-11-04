from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from fx_talanta.domain.models import Environment
from fx_talanta.domain.offline import (
    BrokerBook,
    Entry,
    EntryIntent,
    LossLedger,
    Policy,
    Position,
    Reservation,
)
from fx_talanta.research.offline import market_at
from fx_talanta.research.records import START
from fx_talanta.risk.governor import exposure, losses, size
from fx_talanta.storage.config import fixture_account

D = Decimal
ACCOUNT = fixture_account(Environment.PAPER)


def intent(symbol="EURUSD", side="BUY"):
    return EntryIntent(
        intent_id=uuid4(),
        decision_id=uuid4(),
        account=ACCOUNT,
        symbol=symbol,
        side=side,
        stop=("1.0980" if side == "BUY" else "1.1020")
        if symbol == "EURUSD"
        else ("149.80" if side == "BUY" else "150.20"),
        target=("1.1046" if side == "BUY" else "1.0960")
        if symbol == "EURUSD"
        else ("150.46" if side == "BUY" else "149.60"),
        benchmark=("1.1002" if side == "BUY" else "1.1000")
        if symbol == "EURUSD"
        else ("150.02" if side == "BUY" else "150.00"),
        expires_at=START + timedelta(seconds=60),
        exit_at=START + timedelta(hours=1),
    )


def evaluate(policy=None, *, capital="10000", proposal=None, market=None, ledger=None, entries=()):
    book = BrokerBook(account=ACCOUNT, initial_balance=capital, balance=capital)
    market = market or market_at(START)
    policy = policy or Policy(capital=capital)
    ledger = ledger or losses(None, book, market, policy, START)
    return size(proposal or intent(), book, entries, market, policy, ledger, START)


def test_known_eurusd_size_includes_costs_and_rounds_down():
    reservation, reason = evaluate()
    assert reason == "approved"
    assert reservation.volume == D("0.09")
    # 0.0022 price risk * 100,000 + round-trip commission 8 + slippage 5.
    assert reservation.risk_per_lot == D("233")


@pytest.mark.parametrize(
    "policy",
    [
        Policy(trade_fraction="0.00001"),
        Policy(aggregate_fraction="0.00001"),
        Policy(gross_multiple="0.01"),
        Policy(currency_multiple="0.01"),
        Policy(margin_fraction="0.00001"),
    ],
)
def test_each_independent_budget_can_make_minimum_lot_ineligible(policy):
    reservation, reason = evaluate(policy)
    assert reservation is None and "minimum lot" in reason


def test_daily_loss_remaining_includes_already_lost_equity():
    ledger = LossLedger(
        day=START.date(), start_equity="10000", day_flow_base="0", units="10000", day_loss="99"
    )
    assert evaluate(ledger=ledger)[0] is None


def test_existing_reservation_consumes_aggregate_budget_and_slot():
    other = intent("USDJPY")
    reserved = Entry(
        intent=other,
        state="OUTCOME_UNKNOWN",
        reservation=Reservation(
            volume="0.1",
            risk_per_lot="499",
            gross_per_lot="100000",
            margin_per_lot="2000",
            currency_per_lot={"USD": D("100000"), "JPY": D("-100000")},
        ),
    )
    assert evaluate(entries=(reserved,))[0] is None
    assert evaluate(proposal=other, entries=(reserved,))[1] == "position slot occupied"


@pytest.mark.parametrize("capital", ["50", "1000", "2000", "10000"])
@pytest.mark.parametrize("symbol", ["EURUSD", "USDJPY"])
@pytest.mark.parametrize("side", ["BUY", "SELL"])
def test_size_respects_all_caps_after_immediate_mark_and_cost(capital, symbol, side):
    market = market_at(START)
    proposal = intent(symbol, side)
    result, _ = evaluate(capital=capital, proposal=proposal)
    if result is None:
        # At $1,000 even the USDJPY minimum lot uses the entire currency cap
        # before spread/commission. EURUSD's minimum base leg is $1,100.
        assert D(capital) <= 1000
        return
    spec, quote = market.spec_for(symbol), market.quote_for(symbol)
    equity_after = D(capital) - result.volume * (
        (quote.ask - quote.bid) * spec.contract_size * market.conversion[spec.quote]
        + spec.commission_per_lot
    )
    assert result.volume % spec.volume_step == 0
    assert result.volume * result.risk_per_lot <= equity_after * D("0.0025")
    assert result.volume * result.gross_per_lot <= equity_after * 2
    assert result.volume * result.margin_per_lot <= equity_after * D("0.20")
    assert all(abs(v * result.volume) <= equity_after for v in result.currency_per_lot.values())


@pytest.mark.parametrize(
    "changes",
    [
        {"news_ok": False},
        {"calendar_ok": False},
        {"event_blackout": True},
        {"session_open": False},
    ],
)
def test_required_input_and_event_gates(changes):
    assert evaluate(market=market_at(START, **changes))[0] is None


def test_stale_future_spread_and_adverse_move_rejected():
    for market in (
        market_at(START - timedelta(seconds=3)),
        market_at(START + timedelta(seconds=1)),
        market_at(START, eur_ask="1.1010"),
        market_at(START, eur_bid="1.1010", eur_ask="1.1012"),
    ):
        assert evaluate(market=market)[0] is None


def test_stop_risk_is_current_to_stop_not_original_entry_loss():
    position = Position(
        position_id=uuid4(),
        entry_id=uuid4(),
        symbol="EURUSD",
        side="BUY",
        price="1.0800",
        stop="1.0950",
        target="1.12",
        volume="0.1",
    )
    book = BrokerBook(
        account=ACCOUNT, initial_balance="10000", balance="10000", positions=(position,)
    )
    risk = exposure(book, (), market_at(START))[0]
    assert risk == D("50.9")  # Current 1.1000 → stop 1.0950 plus exit cost/slippage.


def test_hedged_currency_legs_do_not_offset_stop_risk():
    long = Position(
        position_id=uuid4(),
        entry_id=uuid4(),
        symbol="EURUSD",
        side="BUY",
        price="1.1002",
        stop="1.0980",
        target="1.11",
        volume="0.1",
    )
    short = long.model_copy(
        update={"position_id": uuid4(), "entry_id": uuid4(), "side": "SELL", "stop": D("1.1020")}
    )
    book = BrokerBook(
        account=ACCOUNT, initial_balance="10000", balance="10000", positions=(long, short)
    )
    used = exposure(book, (), market_at(START))
    assert used[0] == D("39.8")
    assert used[3]["EUR"] == 0
