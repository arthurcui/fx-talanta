from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from uuid import uuid4

import pytest

from fx_talanta.advisor.command_gateway import command_snapshot, dispatch_simulated
from fx_talanta.advisor.commands import CommandInput, SimulatedScope, command_text
from fx_talanta.clock import FakeClock
from fx_talanta.domain.models import Environment
from fx_talanta.domain.offline import Fault, Policy
from fx_talanta.gateway.offline import Gateway
from fx_talanta.research.offline import make_intent, market_at, warmup
from fx_talanta.research.records import START
from fx_talanta.storage.config import fixture_account
from fx_talanta.storage.repository import RecordConflict


def replay():
    clock = FakeClock(START)
    gateway = Gateway.for_replay(fixture_account(Environment.PAPER), uuid4(), clock, Policy())
    warmup(gateway, clock)
    return gateway


def request(gateway, action, language="en", position=None):
    market = market_at(gateway.clock.now())
    scope = SimulatedScope(
        actor_id="trusted-fixture",
        account=gateway.account,
        allowed_actions=(action,),
        expires_at=gateway.clock.now() + timedelta(minutes=1),
    )
    value = CommandInput(
        request_id=uuid4(),
        conversation_id=uuid4(),
        account=gateway.account,
        language=language,
        text=command_text(gateway.account, action, language, position),
        expires_at=gateway.clock.now() + timedelta(seconds=20),
        expected_state_version=command_snapshot(gateway, market).version,
    )
    return scope, value, market


def enter(gateway, fault=None):
    if fault:
        gateway.broker.next_fault = Fault(kind=fault)
    gateway.submit(make_intent(gateway), market_at(gateway.clock.now()))
    return next((p.position_id for p in gateway.broker.book.positions if p.volume), None)


@pytest.mark.parametrize("language", ["en", "zh"])
def test_pause_blocks_entry_resume_preserves_gates(language):
    g = replay()
    assert dispatch_simulated(g, *request(g, "PAUSE_ENTRIES", language))["status"] == "COMPLETED"
    calls = len(g.broker.book.calls)
    result = g.submit(make_intent(g), market_at(g.clock.now()))
    assert result.state == "REJECTED" and len(g.broker.book.calls) == calls
    assert dispatch_simulated(g, *request(g, "RESUME_ENTRIES", language))["status"] == "COMPLETED"
    assert not g.book.administrative_pause
    g.book = g.book.model_copy(update={"integrity_halt": True, "administrative_pause": True})
    g._save("FIXTURE_HALT")
    assert dispatch_simulated(g, *request(g, "RESUME_ENTRIES", language))["status"] == "REJECTED"
    assert g.book.administrative_pause and g.book.integrity_halt


@pytest.mark.parametrize("language", ["en", "zh"])
def test_owned_close_actual_simulator_evidence_no_duplicate(language):
    g = replay()
    position = enter(g)
    args = request(g, "CLOSE_OWNED_POSITION", language, position)
    first = dispatch_simulated(g, *args)
    calls = tuple(g.broker.book.calls)
    assert first["status"] == "COMPLETED"
    assert all(not p.volume for p in g.broker.book.positions)
    assert dispatch_simulated(g, *args) == first and tuple(g.broker.book.calls) == calls
    assert len(first["operation_ids"]) == 1
    with pytest.raises(RecordConflict):
        dispatch_simulated(g, args[0], args[1].model_copy(update={"text": "changed"}), args[2])


@pytest.mark.parametrize("fault", ["LOST_RESPONSE", "TIMEOUT_BEFORE"])
def test_uncertainty_never_blind_resends(fault):
    g = replay()
    position = enter(g)
    args = request(g, "CLOSE_OWNED_POSITION", position=position)
    g.broker.next_fault = Fault(kind=fault)
    first = dispatch_simulated(g, *args)
    assert first["status"] == "OUTCOME_UNKNOWN"
    calls = tuple(g.broker.book.calls)
    assert dispatch_simulated(g, *args) == first
    assert tuple(g.broker.book.calls) == calls


@pytest.mark.parametrize("fault", [None, "ACK_ONLY", "PARTIAL"])
def test_flatten_cancels_remainders_closes_and_halts(fault):
    g = replay()
    enter(g, fault)
    result = dispatch_simulated(g, *request(g, "FLATTEN_OWNED_AND_HALT"))
    assert result["status"] == "COMPLETED"
    assert all(not p.volume for p in g.broker.book.positions)
    assert all(not o.remaining for o in g.broker.book.orders)
    assert g.book.administrative_pause and g.book.integrity_halt


def test_state_change_stale_quote_and_ambiguous_text_do_not_close():
    g = replay()
    position = enter(g)
    args = request(g, "CLOSE_OWNED_POSITION", position=position)
    g.book = g.book.model_copy(update={"administrative_pause": True})
    g._save("FIXTURE_PAUSE")
    count = len(g.broker.book.calls)
    assert dispatch_simulated(g, *args)["reason"] == "STATE_VERSION_CONFLICT"
    args = request(g, "CLOSE_OWNED_POSITION", position=position)
    assert (
        dispatch_simulated(
            g, args[0], args[1].model_copy(update={"text": "Do not " + args[1].text}), args[2]
        )["status"]
        == "REJECTED"
    )
    args = request(g, "CLOSE_OWNED_POSITION", position=position)
    g.clock.advance(timedelta(seconds=3))
    assert dispatch_simulated(g, *args)["reason"] == "STALE_STATE"
    assert len(g.broker.book.calls) == count


def test_reservation_storage_failure_fences_writer_before_mutation(monkeypatch):
    g = replay()
    position = enter(g)
    args = request(g, "CLOSE_OWNED_POSITION", position=position)
    count = len(g.broker.book.calls)
    monkeypatch.setattr(g.store, "save", lambda *a, **k: (_ for _ in ()).throw(OSError("disk")))
    with pytest.raises(OSError):
        dispatch_simulated(g, *args)
    assert len(g.broker.book.calls) == count and g.store.closed


def test_deadline_after_cancel_stops_close(monkeypatch):
    g = replay()
    enter(g, "PARTIAL")
    args = request(g, "FLATTEN_OWNED_AND_HALT")
    manage = g.manage

    def slow_manage(*a, **k):
        result = manage(*a, **k)
        g.clock.advance(timedelta(seconds=21))
        return result

    monkeypatch.setattr(g, "manage", slow_manage)
    result = dispatch_simulated(g, *args)
    assert result["reason"] == "DEADLINE_NO_FURTHER_ACTION"
    assert any(p.volume for p in g.broker.book.positions)
    assert g.book.administrative_pause and g.book.integrity_halt
    calls = tuple(g.broker.book.calls)
    assert dispatch_simulated(g, *args) == result
    assert tuple(g.broker.book.calls) == calls


@pytest.mark.integration
@pytest.mark.parametrize("fail_receipt", [False, True])
def test_postgres_concurrent_close_restart_and_interrupted_receipt(
    settings, monkeypatch, fail_receipt
):
    account, run, clock = fixture_account(Environment.PAPER), uuid4(), FakeClock(START)
    dsn = settings.runtime_dsn(Environment.PAPER)
    g = Gateway(dsn, account, run, clock)
    try:
        warmup(g, clock)
        position = enter(g)
        args = request(g, "CLOSE_OWNED_POSITION", position=position)
        original = g._save

        def fail_final(event, records=()):
            if fail_receipt and event == "ADMIN_RESULT":
                raise OSError("fixture final receipt failure")
            original(event, records)

        monkeypatch.setattr(g, "_save", fail_final)
        if fail_receipt:
            with pytest.raises(OSError):
                dispatch_simulated(g, *args)
        else:
            with ThreadPoolExecutor(max_workers=2) as pool:
                completed = list(pool.map(lambda _: dispatch_simulated(g, *args), range(2)))
            assert completed[0] == completed[1]
            assert completed[0]["status"] == "COMPLETED"
        calls = tuple(g.broker.book.calls)
    finally:
        g.close()
    g = Gateway(dsn, account, run, clock)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: dispatch_simulated(g, *args), range(2)))
        assert results[0] == results[1]
        assert results[0]["reason"] == (
            "INTERRUPTED_NO_RESEND" if fail_receipt else "SIMULATOR_CONFIRMED"
        )
        assert tuple(g.broker.book.calls) == calls
        assert all(not p.volume for p in g.broker.book.positions)
    finally:
        g.close()
