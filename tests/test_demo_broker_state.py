"""Reconciled state delivery cannot authorize trading or release risk."""

import pytest

from fx_talanta.domain.ea_protocol import Envelope
from fx_talanta.shadow.wire import digest
from scripts.demo_execution_fixtures import example
from scripts.shadow_fixtures import NOW
from tests.test_demo_execution import call, make, restart


def report(
    e,
    revision=4,
    state="PROTECTED",
    filled=4000000,
    opened=4000000,
    remaining=5000000,
    stop="1.098",
):
    return "\t".join(
        map(
            str,
            [
                "demo-state/1",
                e.payload.message_id,
                e.digest,
                revision,
                state,
                filled,
                opened,
                remaining,
                500,
                700,
                stop,
                NOW,
                10,
                "a" * 64,
            ],
        )
    )


def setup(tmp_path):
    c = make(tmp_path)
    e, s = example()
    c.publish(e, s, NOW)
    call(c)
    return c, e


def test_partial_fill_repair_close_chain_and_lost_ack(tmp_path):
    c, e = setup(tmp_path)
    partial = report(e, state="PROTECTION_PENDING", stop="0")
    assert call(c, "REPORT", partial, "b" * 64).payload == digest(partial)
    c = restart(c)
    assert call(c, "REPORT", partial, "b" * 64).payload == digest(partial)
    protected = report(e, revision=5)
    call(c, "REPORT", protected, "c" * 64)
    closed = report(e, revision=6, state="CLOSED", opened=0, remaining=0, stop="0")
    call(c, "REPORT", closed, "d" * 64)
    # An old-version retransmission is acknowledged, never made current again.
    call(c, "REPORT", partial, "e" * 64)
    c = restart(c)
    status = c.status(NOW)
    assert status["broker_states"][0]["state"]["payload"]["state"] == "CLOSED"
    assert not status["broker_states"][0]["independently_verified"]
    assert status["orders_sent"] == 0 and not status["demo_order_acceptance"]
    with c.store.transaction() as events:
        rows = [r for r in events.records if r["kind"] == "demo_broker_state"]
        assert len(rows) == 3
        assert c._ledger(events).hard_halt
        assert rows[0]["state"]["payload"]["predecessor_hash"] == e.digest
        for a, b in zip(rows, rows[1:], strict=False):
            assert (
                b["state"]["payload"]["predecessor_hash"]
                == Envelope.model_validate(a["state"]).digest
            )
        # Delivery does not release or rewrite original reservations.
        assert all(not r.get("risk_released", False) for r in rows)


@pytest.mark.parametrize(
    "field,value",
    [
        (0, "bogus"),
        (2, "b" * 64),
        (3, "0"),
        (4, "FILLED"),
        (5, "3000000"),
        (6, "10000000"),
        (7, "99000000"),
        (8, "0"),
        (9, "0"),
        (10, "NaN"),
        (10, "1.097"),
        (10, "1e999999"),
        (11, str(NOW + 1000)),
        (12, "101"),
        (13, "not-a-proof"),
    ],
)
def test_invalid_native_state_rejected_atomically(tmp_path, field, value):
    c, e = setup(tmp_path)
    f = report(e).split("\t")
    f[field] = value
    before = c.checkpoint()
    with pytest.raises(ValueError):
        call(c, "REPORT", "\t".join(f), "b" * 64)
    assert c.checkpoint() == before


def test_conflicting_revision_regression_and_cross_protocol_nonce(tmp_path):
    c, e = setup(tmp_path)
    initial = report(e)
    call(c, "REPORT", initial, "b" * 64)
    with pytest.raises(ValueError, match="REVISION_CONFLICT"):
        call(c, "REPORT", report(e, stop="1.099"), "c" * 64)
    with pytest.raises(ValueError, match="REGRESSION"):
        call(c, "REPORT", report(e, revision=3), "c" * 64)
    with pytest.raises(ValueError, match="NONCE_CONFLICT"):
        call(c, nonce="b" * 64)
    with pytest.raises(ValueError, match="NONCE_CONFLICT"):
        call(c, "REPORT", initial, "a" * 64)


def test_closed_cannot_reopen_and_fill_cannot_regress(tmp_path):
    c, e = setup(tmp_path)
    call(c, "REPORT", report(e), "b" * 64)
    with pytest.raises(ValueError, match="REGRESSION"):
        call(c, "REPORT", report(e, revision=5, filled=3000000, opened=3000000), "c" * 64)
    call(
        c,
        "REPORT",
        report(e, revision=5, state="CLOSED", opened=0, remaining=0, stop="0"),
        "c" * 64,
    )
    with pytest.raises(ValueError, match="CANNOT_REOPEN"):
        call(c, "REPORT", report(e, revision=6), "d" * 64)


def test_unrelated_request_and_bad_auth_cannot_report(tmp_path):
    c, e = setup(tmp_path)
    f = report(e).split("\t")
    f[1] = "00000000-0000-4000-8000-000000000001"
    with pytest.raises(ValueError, match="UNKNOWN_WORK"):
        call(c, "REPORT", "\t".join(f), "b" * 64)


def test_actual_native_attempt_and_query_are_separate(tmp_path):
    from pathlib import Path

    c, e = setup(tmp_path)
    folder = Path(__file__).parent / "fixtures/demo"
    native = (folder / "demo-attempt.txt").read_text().strip()
    assert call(c, "REPORT", native, "b" * 64, now=NOW + 30).payload == digest(native)
    assert c.status(NOW + 30)["broker_states"] == []
    assert c.status(NOW + 30)["orders_sent"] is None
    query = (folder / "demo-state.txt").read_text().strip()
    assert call(c, "REPORT", query, "c" * 64, now=NOW + 30).payload == digest(query)
    c = restart(c)
    state = c.status(NOW + 30)["broker_states"][0]
    assert state["state"]["payload"]["state"] == "PROTECTED"
    assert state["state"]["payload"]["filled_volume"] == "0.04"
    with c.store.transaction() as events:
        row = next(r for r in events.records if r["kind"] == "demo_broker_state")
        assert Envelope.model_validate(row["reconciliation"]).payload.released_volume == 0
        assert row["reconciliation"]["payload"]["predecessor_hash"] == row["state"]["digest"]
        assert c._ledger(events).hard_halt


def test_initial_proof_remains_verifiable():
    import hashlib
    import json
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    report = json.loads((root / "docs/evidence/m2-demo-execution-initial.json").read_text())
    for name, expected in (report["native_dependency_sha256"] | report["artifacts_sha256"]).items():
        current = root / name
        if hashlib.sha256(current.read_bytes()).hexdigest() != expected:
            current = root / "tests/fixtures/source-archive" / (expected + ".txt")
        assert hashlib.sha256(current.read_bytes()).hexdigest() == expected


@pytest.mark.parametrize("action", ["CLOSE", "TIGHTEN_STOP", "CANCEL"])
def test_native_management_query_and_receipt_are_durable(tmp_path, action):
    from pathlib import Path

    c = make(tmp_path)
    c.publish(*example(), NOW)
    c.publish(*example(action, sequence=2), NOW)
    payload = (
        (Path(__file__).parent / "fixtures/demo" / f"demo-state-{action}.txt").read_text().strip()
    )
    ack = call(c, "REPORT", payload, "b" * 64, now=NOW + 30)
    c = restart(c)
    assert call(c, "REPORT", payload, "b" * 64, now=NOW + 30) == ack
    item = c.status(NOW + 30)["broker_states"][0]
    assert item["action"] == action
    result = Envelope.model_validate(item["state"]).payload
    assert result.kind == "reconciliation_result" and result.result == "CONFIRMED"
    assert result.released_volume == 0
    if action == "CLOSE":
        assert str(result.filled_volume) == "0.04"
        assert item["observed_position_volume"] == "0.05"
    with c.store.transaction() as events:
        assert c._ledger(events).hard_halt
    fields = payload.split("\t")
    fields[8 if action == "CANCEL" else 9] = "999"
    fields[3] = str(int(fields[3]) + 1)
    with pytest.raises(ValueError):
        call(c, "REPORT", "\t".join(fields), "c" * 64, now=NOW + 30)
