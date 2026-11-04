"""Small synthetic market and decision inputs for the M0B demo and fault tests."""

from datetime import timedelta
from decimal import Decimal
from uuid import uuid4, uuid5

from fx_talanta.clock import FakeClock
from fx_talanta.domain.models import Environment
from fx_talanta.domain.offline import EntryIntent, Fault, Instrument, Market, Policy, Quote
from fx_talanta.gateway.offline import Gateway
from fx_talanta.research.decisions import ScriptedDecisionSource, record_attempt, response
from fx_talanta.research.records import START
from fx_talanta.storage.config import Settings, fixture_account


def market_at(
    now, *, eur_bid="1.1000", eur_ask="1.1002", jpy_bid="150.00", jpy_ask="150.02", **changes
) -> Market:
    return Market(
        at=now,
        quotes=(
            Quote(symbol="EURUSD", bid=eur_bid, ask=eur_ask, at=now),
            Quote(symbol="USDJPY", bid=jpy_bid, ask=jpy_ask, at=now),
        ),
        instruments=(
            Instrument(
                symbol="EURUSD",
                base="EUR",
                quote="USD",
                minimum_stop="0.0001",
                maximum_spread="0.0005",
                maximum_adverse_move="0.0005",
            ),
            Instrument(
                symbol="USDJPY",
                base="USD",
                quote="JPY",
                minimum_stop="0.01",
                maximum_spread="0.05",
                maximum_adverse_move="0.05",
            ),
        ),
        conversion={
            "USD": Decimal("1"),
            "EUR": Decimal(eur_bid),
            "JPY": Decimal("1") / Decimal(jpy_bid),
        },
        **changes,
    )


def warmup(gateway, clock):
    gateway.reconcile(market_at(clock.now()))
    clock.advance(timedelta(seconds=1))
    gateway.reconcile(market_at(clock.now()))


def make_intent(gateway, *, symbol="EURUSD", side="BUY", stop=None, exit_seconds=30):
    run = uuid4()
    now = gateway.clock.now()
    result = record_attempt(
        gateway.store.repo,
        ScriptedDecisionSource(
            (response(gateway.account, now + timedelta(seconds=60), symbol=symbol, side=side),)
        ),
        gateway.clock,
        run,
        "offline-decision",
        (),
    )
    eur = symbol == "EURUSD"
    return EntryIntent(
        intent_id=uuid5(run, "entry"),
        account=gateway.account,
        decision_id=result.record_id,
        symbol=symbol,
        side=side,
        benchmark=("1.1002" if side == "BUY" else "1.1000")
        if eur
        else ("150.02" if side == "BUY" else "150.00"),
        stop=stop
        or (
            ("1.0980" if side == "BUY" else "1.1020")
            if eur
            else ("149.80" if side == "BUY" else "150.20")
        ),
        target=("1.1046" if side == "BUY" else "1.0960")
        if eur
        else ("150.46" if side == "BUY" else "149.60"),
        expires_at=now + timedelta(seconds=60),
        exit_at=now + timedelta(seconds=exit_seconds),
    )


def run_offline_demo(settings: Settings) -> dict:
    run_id, clock = uuid4(), FakeClock(START)
    account = fixture_account(Environment.PAPER)
    dsn = settings.runtime_dsn(Environment.PAPER)
    gateway = Gateway(dsn, account, run_id, clock, Policy())
    try:
        warmup(gateway, clock)
        intent = make_intent(gateway)
        gateway.broker.next_fault = Fault(kind="LOST_RESPONSE")
        unknown = gateway.submit(intent, market_at(clock.now()))
        reserved = unknown.reservation.volume
        gateway.close()
        clock.advance(timedelta(seconds=1))
        gateway = Gateway(dsn, account, run_id, clock)
        gateway.reconcile(market_at(clock.now()))
        recovered = gateway.entry(intent.intent_id).state
        clock.advance(timedelta(seconds=30))
        gateway.reconcile(market_at(clock.now(), eur_bid="1.1030", eur_ask="1.1032"))
        final = gateway.entry(intent.intent_id)
        position = gateway.broker.book.positions[0]
        return {
            "run_id": str(run_id),
            "environment": "PAPER",
            "venue": "SIMULATOR",
            "initial_state": unknown.state,
            "reserved_volume_during_uncertainty": str(reserved),
            "after_restart": recovered,
            "final_state": final.state,
            "entry_submissions": gateway.broker.book.calls.count(intent.intent_id),
            "open_volume": str(position.volume),
            "net_pnl_usd": str(position.realized),
            "live_enabled": False,
        }
    finally:
        gateway.close()
