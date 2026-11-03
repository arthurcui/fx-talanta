"""Regression cases authored for remediation; execution is separately controlled."""

from datetime import UTC, datetime, timedelta

import pytest

from fx_talanta.domain.models import Environment, ObservationDiagnostic, TerminalObservation
from fx_talanta.observer.contracts import Binding
from fx_talanta.observer.fixtures import FixtureReader
from fx_talanta.observer.supervisor import assess
from fx_talanta.storage.config import fixture_account


def test_invalid_data_keeps_rule_without_changing_halt_reason():
    now = datetime(2026, 1, 5, 12, tzinfo=UTC)
    binding = Binding(
        account=fixture_account(Environment.PAPER),
        terminal_path="C:/fixture/terminal64.exe",
        data_path="C:/fixture/data",
        expected_build=123,
    )
    snapshot = FixtureReader()(binding, now)
    tick = snapshot.ticks[0].model_copy(update={"at": now + timedelta(seconds=1)})
    reason = assess(snapshot.model_copy(update={"ticks": (tick,)}), binding, now)
    assert reason == "INVALID_DATA"
    assert reason.diagnostic.rule == "FUTURE_TICK"
    body = TerminalObservation(
        binding_hash=binding.fingerprint(),
        state="HALTED",
        reason=reason,
        failures=1,
        diagnostic=reason.diagnostic,
    )
    restored = TerminalObservation.model_validate_json(body.model_dump_json())
    assert restored.diagnostic == reason.diagnostic
    assert restored.snapshot is None


def test_diagnostic_has_no_arbitrary_text_and_legacy_payload_stays_unchanged():
    with pytest.raises(ValueError):
        ObservationDiagnostic(stage="READER", rule="SECRET_ACCOUNT_OR_EXCEPTION")
    with pytest.raises(ValueError):
        ObservationDiagnostic(stage="READER", rule="SNAPSHOT_SCHEMA", raw="secret")
    body = TerminalObservation(
        binding_hash="a" * 64,
        state="HALTED",
        reason="INVALID_DATA",
        failures=1,
    )
    payload = body.model_dump(mode="json")
    assert "diagnostic" not in payload
    assert "health" not in payload
    assert TerminalObservation.model_validate(payload).model_dump(mode="json") == payload
