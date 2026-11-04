import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

import psycopg
import pytest
from psycopg.types.json import Jsonb

from fx_talanta.clock import FakeClock
from fx_talanta.domain.models import Environment
from fx_talanta.domain.offline import BrokerRequest, Fault, Policy, Position
from fx_talanta.gateway.offline import Gateway, SimulatedCrash
from fx_talanta.research.offline import make_intent, market_at, warmup
from fx_talanta.research.records import START
from fx_talanta.risk.governor import exposure
from fx_talanta.storage.config import fixture_account
from fx_talanta.storage.offline import WriterBusy
from fx_talanta.storage.repository import AccountMismatch, RecordConflict

pytestmark = pytest.mark.integration
D = Decimal


@pytest.fixture
def gateway(settings):
    clock = FakeClock(START)
    value = Gateway(
        settings.runtime_dsn(Environment.PAPER), fixture_account(Environment.PAPER), uuid4(), clock
    )
    warmup(value, clock)
    try:
        yield value
    finally:
        value.close()


def restart(gateway, settings):
    gateway.close()
    return Gateway(
        settings.runtime_dsn(Environment.PAPER),
        gateway.account,
        gateway.run_id,
        gateway.clock,
        gateway.book.policy,
    )


def tick(gateway, seconds=1, **market):
    gateway.clock.advance(timedelta(seconds=seconds))
    value = market_at(gateway.clock.now(), **market)
    gateway.reconcile(value)
    return value


def management(gateway, entry, action="CLOSE", **changes):
    p = next(p for p in gateway.broker.book.positions if p.entry_id == entry.intent.intent_id)
    values = dict(
        request_id=uuid4(),
        account=gateway.account,
        entry_id=p.entry_id,
        action=action,
        symbol=p.symbol,
        position_id=p.position_id,
        expected_version=p.version,
        volume=p.volume,
    )
    values.update(changes)
    return BrokerRequest(**values)


def test_offline_loop_records_net_outcome_and_exact_request(gateway):
    intent = make_intent(gateway)
    entry = gateway.submit(intent, market_at(gateway.clock.now()))
    assert entry.state == "PROTECTED"
    assert entry.reservation.volume == 0
    assert gateway.broker.book.calls == (intent.intent_id,)
    gateway.submit(intent, market_at(gateway.clock.now()))
    assert gateway.broker.book.calls == (intent.intent_id,)
    tick(gateway, 31, eur_bid="1.1030", eur_ask="1.1032")
    assert gateway.entry(intent.intent_id).state == "COMPLETED"
    assert gateway.broker.book.positions[0].volume == 0
    pnl = gateway.broker.book.positions[0].realized
    assert pnl > 0
    assert gateway.broker.book.balance == gateway.book.policy.capital + pnl
    final = gateway.store.repo.get(gateway.entry(intent.intent_id).case_id)
    assert final.body.net_pnl == pnl and final.body.economic_outcome == "PROFIT"
    assert final.costs.commission > 0
    rows = gateway.store.conn.execute(
        "SELECT event,payload FROM fx.offline_journal WHERE run_id=%s AND stream='gateway' "
        "ORDER BY revision",
        (gateway.run_id,),
    ).fetchall()
    assert any(
        event == "SUBMITTING"
        and data["entries"][0]["request"]["request_id"] == str(intent.intent_id)
        for event, data in rows
    )


@pytest.mark.parametrize(
    "point,expected,calls",
    [
        ("after_reserve", "CANCELLED", 0),
        ("before_send", "OUTCOME_UNKNOWN", 0),
        ("after_send", "PROTECTED", 1),
        ("after_fill", "PROTECTED", 1),
        ("after_partial", "PROTECTED", 1),
    ],
)
def test_crash_windows_preserve_and_reconstruct(gateway, settings, point, expected, calls):
    intent = make_intent(gateway)
    if point == "after_partial":
        gateway.broker.next_fault = Fault(kind="PARTIAL")
    with pytest.raises(SimulatedCrash):
        gateway.submit(intent, market_at(gateway.clock.now()), crash_at=point)
    fresh = restart(gateway, settings)
    try:
        fresh.reconcile(market_at(fresh.clock.now()))
        entry = fresh.entry(intent.intent_id)
        assert entry.state == expected
        assert fresh.broker.book.calls.count(intent.intent_id) == calls
        if point in {"before_send", "after_partial"}:
            assert entry.reservation.volume > 0
        if point == "before_send":
            tick(fresh, 120)
            assert fresh.entry(intent.intent_id).state == "OUTCOME_UNKNOWN"
            assert fresh.entry(intent.intent_id).reservation.volume > 0
    finally:
        fresh.close()


def test_lost_response_never_resends_and_links_recovery(gateway, settings):
    intent = make_intent(gateway)
    gateway.broker.next_fault = Fault(kind="LOST_RESPONSE")
    unknown = gateway.submit(intent, market_at(gateway.clock.now()))
    assert unknown.state == "OUTCOME_UNKNOWN" and unknown.reservation.volume > 0
    assert gateway.book.state == "OUTCOME_UNKNOWN"
    fresh = restart(gateway, settings)
    try:
        fresh.reconcile(market_at(fresh.clock.now()))
        assert fresh.entry(intent.intent_id).state == "PROTECTED"
        assert fresh.broker.book.calls.count(intent.intent_id) == 1
        assert fresh.store.repo.get(unknown.case_id).body.operational_result == "UNKNOWN"
        cases = fresh.store.repo.history(correlation_id=fresh.run_id, kind="experience")
        assert any(r.body.operational_result == "RECOVERED" for r in cases)
    finally:
        fresh.close()


def test_absent_history_is_not_failed_execution(gateway):
    intent = make_intent(gateway)
    gateway.broker.next_fault = Fault(kind="TIMEOUT_BEFORE")
    result = gateway.submit(intent, market_at(gateway.clock.now()))
    for _ in range(3):
        tick(gateway)
    assert gateway.entry(intent.intent_id).reservation == result.reservation
    assert gateway.broker.book.calls.count(intent.intent_id) == 1
    other = make_intent(gateway, symbol="USDJPY")
    assert gateway.submit(other, market_at(gateway.clock.now())).state == "REJECTED"
    gateway.broker.confirm_not_executed(result.request)
    tick(gateway)
    assert gateway.entry(intent.intent_id).state == "REJECTED"
    assert gateway.entry(intent.intent_id).reservation.volume == 0


def test_partial_fill_remaining_reservation_without_double_count(gateway, settings):
    gateway.broker.next_fault = Fault(kind="PARTIAL")
    intent = make_intent(gateway)
    entry = gateway.submit(intent, market_at(gateway.clock.now()))
    position = gateway.broker.book.positions[0]
    assert entry.reservation.volume + position.volume == entry.request.volume
    used = exposure(gateway.broker.book, gateway.book.entries, market_at(gateway.clock.now()))
    assert used[1] == entry.request.volume * D("100000") * D("1.1000")
    fresh = restart(gateway, settings)
    try:
        fresh.broker.settle_entry(intent.intent_id, market_at(fresh.clock.now()))
        fresh.reconcile(market_at(fresh.clock.now()))
        assert fresh.entry(intent.intent_id).reservation.volume == 0
        assert fresh.broker.book.positions[0].volume == entry.request.volume
        assert fresh.broker.book.calls.count(intent.intent_id) == 1
    finally:
        fresh.close()


def test_acknowledgment_is_not_fill_and_pending_expiry_cancels(gateway):
    gateway.broker.next_fault = Fault(kind="ACK_ONLY")
    intent = make_intent(gateway, exit_seconds=300)
    entry = gateway.submit(intent, market_at(gateway.clock.now()))
    assert entry.state == "ACKNOWLEDGED" and not gateway.broker.book.positions
    assert entry.reservation.volume > 0
    tick(gateway, 61)
    assert gateway.entry(intent.intent_id).state == "CANCELLED"
    assert gateway.entry(intent.intent_id).reservation.volume == 0


def test_fill_then_protect_and_missing_initial_stop(settings):
    for mode in ("FILL_THEN_PROTECT", "INITIAL_STOP"):
        clock = FakeClock(START)
        gateway = Gateway(
            settings.runtime_dsn(Environment.PAPER),
            fixture_account(Environment.PAPER),
            uuid4(),
            clock,
            Policy(protection_mode=mode),
        )
        try:
            warmup(gateway, clock)
            if mode == "INITIAL_STOP":
                gateway.broker.next_fault = Fault(kind="NO_STOP")
            entry = gateway.submit(make_intent(gateway), market_at(clock.now()))
            assert entry.state == "PROTECTED"
            assert gateway.broker.book.positions[0].stop is not None
            events = gateway.store.repo.history(correlation_id=gateway.run_id, kind="execution")
            assert any(r.body.state == "PROTECTION_PENDING" for r in events)
        finally:
            gateway.close()


def test_failed_protection_closes_known_position(gateway):
    intent = make_intent(gateway)
    gateway.broker.next_fault = Fault(kind="NO_STOP")
    with pytest.raises(SimulatedCrash):
        gateway.submit(intent, market_at(gateway.clock.now()), crash_at="after_fill")
    gateway.broker.next_fault = Fault(kind="REJECT")
    tick(gateway)
    assert gateway.entry(intent.intent_id).state == "COMPLETED"
    assert gateway.broker.book.positions[0].volume == 0
    assert any(
        o.request.action == "TIGHTEN_STOP" and o.state == "REJECTED"
        for o in gateway.book.operations
    )


def test_protection_deadline_counts_from_submission(gateway, settings):
    intent = make_intent(gateway)
    gateway.broker.next_fault = Fault(kind="NO_STOP")
    with pytest.raises(SimulatedCrash):
        gateway.submit(intent, market_at(gateway.clock.now()), crash_at="after_fill")
    fresh = restart(gateway, settings)
    try:
        tick(fresh, 6)
        assert fresh.entry(intent.intent_id).state == "COMPLETED"
        assert not any(o.request.action == "TIGHTEN_STOP" for o in fresh.book.operations)
    finally:
        fresh.close()


def test_gap_fill_risk_breach_closes_and_halts(gateway):
    gateway.broker.next_fault = Fault(kind="GAP_FILL", price_delta="0.02")
    entry = gateway.submit(make_intent(gateway), market_at(gateway.clock.now()))
    assert entry.state == "COMPLETED"
    assert gateway.book.state in {"HARD_HALT", "LOSS_PAUSE"}
    assert gateway.broker.book.positions[0].volume == 0


@pytest.mark.parametrize("changes", [{"volume": D("50")}, {"expected_version": 0}])
def test_stale_and_oversized_closes_cannot_reverse(gateway, changes):
    entry = gateway.submit(make_intent(gateway), market_at(gateway.clock.now()))
    volume = gateway.broker.book.positions[0].volume
    operation = gateway.manage(
        management(gateway, entry, **changes), market_at(gateway.clock.now())
    )
    assert operation.state == "REJECTED"
    assert gateway.broker.book.positions[0].volume == volume


@pytest.mark.parametrize("stop", [None, D("1.0900")])
def test_stop_cannot_be_removed_or_widened(gateway, stop):
    entry = gateway.submit(make_intent(gateway), market_at(gateway.clock.now()))
    old = gateway.broker.book.positions[0].stop
    result = gateway.manage(
        management(gateway, entry, "TIGHTEN_STOP", stop=stop), market_at(gateway.clock.now())
    )
    assert result.state == "REJECTED"
    assert gateway.broker.book.positions[0].stop == old


def test_uncertain_close_is_not_repeated_after_restart(gateway, settings):
    entry = gateway.submit(make_intent(gateway), market_at(gateway.clock.now()))
    request = management(gateway, entry)
    gateway.broker.next_fault = Fault(kind="LOST_RESPONSE")
    assert gateway.manage(request, market_at(gateway.clock.now())).state == "OUTCOME_UNKNOWN"
    with pytest.raises(ValueError, match="unresolved"):
        gateway.manage(management(gateway, entry), market_at(gateway.clock.now()))
    fresh = restart(gateway, settings)
    try:
        tick(fresh)
        assert fresh.entry(entry.intent.intent_id).state == "COMPLETED"
        assert fresh.broker.book.calls.count(request.request_id) == 1
    finally:
        fresh.close()


def test_second_writer_and_live_gateway_rejected(gateway, settings):
    with pytest.raises(WriterBusy):
        Gateway(settings.runtime_dsn(Environment.PAPER), gateway.account, uuid4(), gateway.clock)
    with pytest.raises(AccountMismatch):
        Gateway(
            settings.runtime_dsn(Environment.LIVE),
            fixture_account(Environment.LIVE),
            uuid4(),
            gateway.clock,
        )
    intent = make_intent(gateway).model_copy(update={"account": fixture_account(Environment.LIVE)})
    with pytest.raises(AccountMismatch):
        gateway.submit(intent, market_at(gateway.clock.now()))


def test_simultaneous_entries_cannot_consume_same_slot(gateway):
    intents = [make_intent(gateway) for _ in range(4)]
    market = market_at(gateway.clock.now())
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda i: gateway.submit(i, market), intents))
    assert sum(e.state == "PROTECTED" for e in results) == 1
    assert sum(e.state == "REJECTED" for e in results) == 3
    assert len(gateway.broker.book.positions) == 1


def test_lost_database_session_fences_old_simulator(gateway, settings):
    entry = gateway.submit(make_intent(gateway), market_at(gateway.clock.now()))
    request = management(gateway, entry)
    gateway.store.conn.close()
    with pytest.raises(psycopg.Error):
        gateway.broker.mutate(request, market_at(gateway.clock.now()))
    fresh = restart(gateway, settings)
    try:
        assert request.request_id not in fresh.broker.book.calls
        assert fresh.broker.book.positions[0].volume > 0
    finally:
        fresh.close()


def test_news_outage_blocks_entries_but_time_exit_runs(gateway):
    entry = gateway.submit(make_intent(gateway), market_at(gateway.clock.now()))
    market = tick(gateway, 31, news_ok=False)
    assert gateway.entry(entry.intent.intent_id).state == "COMPLETED"
    assert gateway.book.state == "DEGRADED_PROTECT"
    assert gateway.submit(make_intent(gateway), market).state == "REJECTED"
    tick(gateway)
    assert gateway.book.state == "DEGRADED_PROTECT"
    tick(gateway)
    assert gateway.book.state == "RUNNING"


def test_market_closed_exit_is_not_false_completion(gateway):
    entry = gateway.submit(make_intent(gateway), market_at(gateway.clock.now()))
    tick(gateway, 31, session_open=False)
    assert gateway.broker.book.positions[0].volume > 0
    assert gateway.entry(entry.intent.intent_id).state != "COMPLETED"
    tick(gateway)
    assert gateway.entry(entry.intent.intent_id).state == "COMPLETED"


def test_external_position_halts_without_claiming_or_liquidating_it(gateway):
    position = Position(
        position_id=uuid4(),
        entry_id=uuid4(),
        symbol="EURUSD",
        side="BUY",
        volume="0.01",
        price="1.1000",
        stop="1.0980",
        target="1.11",
        owned=False,
    )
    gateway.broker.inject_position(position)
    tick(gateway)
    assert gateway.book.state == "HARD_HALT"
    assert gateway.broker.book.positions[0] == position
    assert not gateway.broker.book.calls


def test_hard_drawdown_survives_restart_and_deposit(gateway, settings):
    gateway.submit(make_intent(gateway, exit_seconds=3600), market_at(gateway.clock.now()))
    # A gap can exceed the stop and drawdown mandate; closure is at the observed price.
    bad = tick(gateway, eur_bid="1.0200", eur_ask="1.0202")
    assert gateway.book.losses.hard_halt
    gateway.broker.cash_flow(D("10000"), bad, uuid4())
    tick(gateway)
    fresh = restart(gateway, settings)
    try:
        tick(fresh, 86400)
        assert fresh.book.state == "HARD_HALT"
        assert fresh.book.losses.hard_halt
        assert fresh.book.policy.capital == D("10000")
    finally:
        fresh.close()


def test_daily_loss_pause_survives_restart_and_clears_next_utc_day(gateway, settings):
    gateway.submit(make_intent(gateway, exit_seconds=3600), market_at(gateway.clock.now()))
    tick(gateway, eur_bid="1.0850", eur_ask="1.0852")
    assert gateway.book.state == "LOSS_PAUSE"
    fresh = restart(gateway, settings)
    try:
        tick(fresh)
        assert fresh.book.state == "LOSS_PAUSE"
        assert fresh.book.losses.start_equity == D("10000")
        tick(fresh, 86400)
        assert fresh.book.state == "RUNNING"
        assert not fresh.book.losses.hard_halt
    finally:
        fresh.close()


def test_cashflows_do_not_reset_nav_or_expand_capital(gateway):
    market = market_at(gateway.clock.now())
    gateway.broker.cash_flow(D("10000"), market, uuid4())
    tick(gateway)
    assert gateway.book.losses.units == D("20000")
    assert gateway.book.losses.high_water_nav == 1
    entry = gateway.submit(make_intent(gateway), market_at(gateway.clock.now()))
    assert entry.request.volume <= D("0.09")  # Allocation did not double with the deposit.


def test_unknown_cashflow_blocks_entry(gateway):
    gateway.broker.cash_flow(D("100"), market_at(gateway.clock.now()), uuid4(), classified=False)
    tick(gateway)
    assert gateway.book.state == "DEGRADED_PROTECT"
    assert gateway.submit(make_intent(gateway), market_at(gateway.clock.now())).state == "REJECTED"


def test_restart_cannot_change_policy(gateway, settings):
    gateway.close()
    with pytest.raises(ValueError, match="mandate"):
        Gateway(
            settings.runtime_dsn(Environment.PAPER),
            gateway.account,
            gateway.run_id,
            gateway.clock,
            Policy(capital="20000"),
        )


def test_changed_intent_id_is_not_new_authority(gateway):
    intent = make_intent(gateway)
    gateway.submit(intent, market_at(gateway.clock.now()))
    with pytest.raises(RecordConflict):
        gateway.submit(
            intent.model_copy(update={"stop": D("1.0970")}), market_at(gateway.clock.now())
        )


def test_offline_history_append_only_and_live_database_rejects_it(gateway, settings):
    with psycopg.connect(settings.runtime_dsn(Environment.PAPER)) as conn:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("DELETE FROM fx.offline_journal")
    with psycopg.connect(settings.runtime_dsn(Environment.LIVE)) as conn:
        data = gateway.book.model_dump(mode="json")
        data["account"] = fixture_account(Environment.LIVE).model_dump(mode="json")
        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute(
                "INSERT INTO fx.offline_journal VALUES (%s,'gateway',1,%s,'FORGED',%s)",
                (uuid4(), gateway.clock.now(), Jsonb(data)),
            )


def test_protection_continues_for_known_fill_with_hidden_order_history(gateway):
    intent = make_intent(gateway)
    gateway.broker.next_fault = Fault(kind="NO_STOP")
    with pytest.raises(SimulatedCrash):
        gateway.submit(intent, market_at(gateway.clock.now()), crash_at="after_fill")
    gateway.broker.history_visible = False
    tick(gateway)
    assert gateway.entry(intent.intent_id).state == "OUTCOME_UNKNOWN"
    assert gateway.broker.book.positions[0].stop == intent.stop
    assert gateway.broker.book.calls.count(intent.intent_id) == 1


def test_disconnection_does_not_claim_exit_and_recovers(gateway):
    entry = gateway.submit(make_intent(gateway), market_at(gateway.clock.now()))
    gateway.broker.connected = False
    tick(gateway, 31)
    assert gateway.book.state == "DEGRADED_PROTECT"
    assert gateway.broker.book.positions[0].volume > 0
    gateway.broker.connected = True
    tick(gateway)
    assert gateway.entry(entry.intent.intent_id).state == "COMPLETED"


def test_fresh_process_recovers_fill_without_resend(gateway):
    intent = make_intent(gateway)
    with pytest.raises(SimulatedCrash):
        gateway.submit(intent, market_at(gateway.clock.now()), crash_at="after_fill")
    run_id, at = str(gateway.run_id), gateway.clock.now().isoformat()
    gateway.close()
    code = """
import json, sys
from datetime import datetime
from uuid import UUID
from fx_talanta.clock import FakeClock
from fx_talanta.domain.models import Environment
from fx_talanta.storage.config import Settings, fixture_account
from fx_talanta.gateway.offline import Gateway
from fx_talanta.research.offline import market_at
clock = FakeClock(datetime.fromisoformat(sys.argv[2]))
g = Gateway(Settings.load().runtime_dsn(Environment.PAPER), fixture_account(Environment.PAPER),
            UUID(sys.argv[1]), clock)
try:
    g.reconcile(market_at(clock.now()))
    print(json.dumps({"state": g.book.entries[0].state, "calls": len(g.broker.book.calls)}))
finally:
    g.close()
"""
    result = subprocess.run(
        [sys.executable, "-c", code, run_id, at], capture_output=True, text=True, check=True
    )
    assert json.loads(result.stdout) == {"state": "PROTECTED", "calls": 1}


def test_stale_quotes_cannot_roll_loss_baseline(gateway):
    old = gateway.book.losses
    stale = market_at(gateway.clock.now())
    gateway.clock.advance(timedelta(days=1))
    gateway.reconcile(stale)
    assert gateway.book.state == "DEGRADED_PROTECT"
    assert gateway.book.losses == old


def test_unavailable_history_blocks_new_risk_even_with_protected_position(gateway):
    gateway.submit(make_intent(gateway), market_at(gateway.clock.now()))
    gateway.broker.history_visible = False
    tick(gateway)
    assert gateway.book.state == "DEGRADED_PROTECT"
    other = make_intent(gateway, symbol="USDJPY")
    assert gateway.submit(other, market_at(gateway.clock.now())).state == "REJECTED"


def test_known_partial_remainder_cancelled_at_entry_expiry(gateway):
    gateway.broker.next_fault = Fault(kind="PARTIAL")
    entry = gateway.submit(make_intent(gateway, exit_seconds=300), market_at(gateway.clock.now()))
    filled_volume = gateway.broker.book.positions[0].volume
    assert entry.reservation.volume > 0
    tick(gateway, 61)
    assert gateway.entry(entry.intent.intent_id).reservation.volume == 0
    assert gateway.entry(entry.intent.intent_id).state == "PROTECTED"
    assert gateway.broker.book.positions[0].volume == filled_volume
    assert gateway.broker.book.calls.count(entry.intent.intent_id) == 1
