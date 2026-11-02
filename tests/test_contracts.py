from datetime import datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from fx_talanta.clock import FakeClock
from fx_talanta.domain.models import (
    AccountIdentity,
    Cost,
    Decision,
    Environment,
    ExperienceCase,
    Record,
)
from fx_talanta.fixtures import START
from fx_talanta.storage.config import fixture_account, init_local


def test_account_is_frozen():
    account = fixture_account(Environment.PAPER)
    with pytest.raises(ValidationError):
        account.environment = Environment.LIVE


@pytest.mark.parametrize(
    "environment,venue",
    [
        ("PAPER", "BROKER_LIVE"),
        ("LIVE", "SIMULATOR"),
        ("LIVE", "BROKER_DEMO"),
    ],
)
def test_inconsistent_account_venue_rejected(environment, venue):
    with pytest.raises(ValidationError):
        AccountIdentity(environment=environment, venue=venue, broker="x", server="x", login="x")


@pytest.mark.parametrize("value", [0.1, True, "NaN", "Infinity", "-0.01"])
def test_costs_reject_inexact_nonfinite_or_negative_values(value):
    with pytest.raises(ValidationError):
        Cost(commission=value)


def test_decimal_roundtrip():
    cost = Cost(commission="0.000000000000000001")
    assert Cost.model_validate_json(cost.model_dump_json()).commission == Decimal("1E-18")


def test_naive_timestamp_rejected():
    with pytest.raises(ValidationError):
        Record(
            account=fixture_account(Environment.PAPER),
            recorded_at=datetime(2026, 1, 1),
            correlation_id=uuid4(),
            body=ExperienceCase(
                operational_result="UNKNOWN",
                policy_compliance="UNKNOWN",
                economic_outcome="UNKNOWN",
                summary="unknown",
            ),
        )


def test_entry_requires_candidate():
    with pytest.raises(ValidationError):
        Decision(
            account=fixture_account(Environment.PAPER),
            action="ENTER",
            expires_at=START,
            rationale="incomplete",
        )


@pytest.mark.parametrize(
    "label,pnl", [("PROFIT", "-1"), ("LOSS", "1"), ("FLAT", "1"), ("UNKNOWN", "0")]
)
def test_economic_label_must_match_evidence(label, pnl):
    with pytest.raises(ValidationError):
        ExperienceCase(
            operational_result="SUCCESS",
            policy_compliance="COMPLIANT",
            economic_outcome=label,
            net_pnl=pnl,
            outcome_known_at=START,
            summary="x",
        )


def test_clock_never_rewinds():
    clock = FakeClock(START)
    clock.advance(timedelta(seconds=1))
    assert clock.now() == START + timedelta(seconds=1)
    with pytest.raises(ValueError):
        clock.advance(timedelta(seconds=-1))


def test_init_preserves_existing_secrets(tmp_path):
    path = tmp_path / ".env"
    init_local(path)
    original = path.read_bytes()
    with pytest.raises(FileExistsError):
        init_local(path)
    assert path.read_bytes() == original
