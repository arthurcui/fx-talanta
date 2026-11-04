import json
from pathlib import Path

import pytest

from tools.fixtures.demo_execution_fixtures import compare


def test_no_manifest_cannot_become_native_acceptance(tmp_path):
    (tmp_path / "demo-checks.tsv").write_text("".join(f"passing-{n}\t1\n" for n in range(20)))
    with pytest.raises(ValueError, match="REQUIRED_CHECK_MANIFEST_MISSING"):
        compare(tmp_path)


@pytest.mark.parametrize(
    "rows, reason",
    [
        ("entry\t1\n", "SET_MISMATCH"),
        ("entry\t1\nclose\t1\nextra\t1\n", "SET_MISMATCH"),
        ("entry\t1\nentry\t1\nclose\t1\n", "DUPLICATE"),
        ("entry\t0\nentry\t1\nclose\t1\n", "DUPLICATE"),
        ("entry\t0\nclose\t1\n", "NATIVE_FAILURE"),
        ("entry\ttrue\nclose\t1\n", "INVALID_NATIVE_CHECK_VALUE"),
        ("entry\t1\textra\nclose\t1\n", "MALFORMED"),
        ("", "SET_MISMATCH"),
    ],
)
def test_incomplete_or_ambiguous_evidence_fails_closed(tmp_path, rows, reason):
    (tmp_path / "demo-checks.tsv").write_text(rows)
    with pytest.raises(ValueError, match=reason):
        compare(tmp_path, required_checks=["entry", "close"])


@pytest.mark.parametrize("required", [[], ["entry", "entry"], [None], [["entry"]], "entry"])
def test_invalid_manifest_is_rejected(tmp_path, required):
    with pytest.raises(ValueError, match="INVALID_REQUIRED_CHECK_MANIFEST"):
        compare(tmp_path, required_checks=required)


def test_exact_check_set_is_complete_but_not_connected_acceptance(tmp_path):
    (tmp_path / "demo-checks.tsv").write_text("close\t1\nentry\t1\n")
    result = compare(tmp_path, required_checks=["entry", "close"])
    assert result["check_set_complete"] and result["required_check_count"] == 2
    assert result["synthetic"] and not result["demo_order_acceptance"]


def test_closeout_manifest_preserves_all_prior_activation_checks():
    root = Path(__file__).parent / "fixtures"
    baseline = {
        line.split("\t")[0]
        for line in (root / "demo-activation/demo-checks.tsv").read_text().splitlines()
    }
    required = json.loads((root / "demo-closeout/required-checks.json").read_text())["checks"]
    assert baseline < set(required)
    assert len(required) == len(set(required))
    assert {
        "closeout-drain-completes-without-restart",
        "closeout-lost-report-ack-blocks-drain",
    } <= set(required)


def test_actual_native_closeout_capture_matches_pinned_sources(historical_source, tmp_path):
    import hashlib

    root = Path(__file__).resolve().parents[1]
    fixture = root / "tests/fixtures/demo-closeout"
    report = json.loads((root / "docs/evidence/m2-native-closeout-20261104.json").read_text())
    required_path = fixture / "required-checks.json"
    assert (
        hashlib.sha256(required_path.read_bytes()).hexdigest() == report["required_manifest_sha256"]
    )
    result = compare(fixture, required_checks=json.loads(required_path.read_text())["checks"])
    assert result["checks"] == report["checks"] and result["required_check_count"] == 142
    for name, expected in report["source_sha256"].items():
        assert hashlib.sha256(historical_source(name, expected)).hexdigest() == expected
    assert (
        hashlib.sha256((fixture / "demo-checks.tsv").read_bytes()).hexdigest()
        == report["checks_sha256"]
    )
    assert (
        hashlib.sha256((fixture / "closeout-state.txt").read_bytes()).hexdigest()
        == report["closed_state_sha256"]
    )
    initial = report["initial_attempt"]
    assert (
        hashlib.sha256((fixture / "initial-checks.tsv").read_bytes()).hexdigest()
        == initial["checks_sha256"]
    )
    assert (
        hashlib.sha256(
            historical_source(
                "tests/native/demo/NativeTests.mq5", initial["native_test_source_sha256"]
            )
        ).hexdigest()
        == initial["native_test_source_sha256"]
    )
    (tmp_path / "demo-checks.tsv").write_bytes((fixture / "initial-checks.tsv").read_bytes())
    with pytest.raises(ValueError, match="closeout-protection-settled"):
        compare(tmp_path, required_checks=json.loads(required_path.read_text())["checks"])
    assert not report["full_m2_acceptance"] and not report["m1_qualified"]


def test_native_closed_payload_survives_backend_restart_and_lost_ack(tmp_path):
    from fx_talanta.shadow.wire import digest
    from tests.test_demo_broker_state import setup
    from tests.test_demo_execution import call, restart
    from tools.fixtures.shadow_fixtures import NOW

    fixture = Path(__file__).parent / "fixtures/demo-closeout/closeout-state.txt"
    payload = fixture.read_text(encoding="ascii")
    backend, _ = setup(tmp_path)
    first = call(backend, "REPORT", payload, "d" * 64, now=NOW + 40)
    assert first.payload == digest(payload)
    backend = restart(backend)
    replay = call(backend, "REPORT", payload, "d" * 64, now=NOW + 40)
    assert replay.payload == first.payload
    status = backend.status(NOW + 40)
    assert len(status["broker_states"]) == 1
    state = status["broker_states"][0]
    assert state["state"]["payload"]["state"] == "CLOSED"
    assert not state["independently_verified"]
    assert not status["demo_order_acceptance"] and status["orders_sent"] == 0
    with backend.store.transaction() as events:
        states = [r for r in events.records if r["kind"] == "demo_broker_state"]
        assert len(states) == 1 and not states[0].get("risk_released", False)
