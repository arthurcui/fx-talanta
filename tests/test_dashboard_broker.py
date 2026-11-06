from datetime import timedelta
from uuid import uuid4

import pytest

from fx_talanta.dashboard.broker_view import BrokerViewConfig, project_observation
from fx_talanta.dashboard.demo import AT
from fx_talanta.domain.models import AccountIdentity, Environment, Record, TerminalObservation
from fx_talanta.observer.contracts import Binding
from fx_talanta.research.observer import FixtureReader
from fx_talanta.storage.config import fixture_account


def observation():
    account = AccountIdentity(
        environment="PAPER",
        broker="fixture-demo",
        server="test-server",
        login="12345",
        venue="BROKER_DEMO",
    )
    binding = Binding(
        account=fixture_account(Environment.PAPER),
        terminal_path="C:/fixture/terminal.exe",
        data_path="C:/fixture/data",
        expected_build=123,
    )
    snap = FixtureReader()(binding, AT).model_copy(
        update={"account_before": account, "account_after": account}
    )
    run = uuid4()
    record = Record(
        account=account,
        recorded_at=AT,
        correlation_id=run,
        provenance="BROKER_OBSERVATION",
        body=TerminalObservation(
            binding_hash="a" * 64,
            state="HEALTHY",
            reason="CURRENT",
            failures=0,
            last_success_at=AT,
            snapshot=snap,
        ),
    )
    config = BrokerViewConfig(
        label="Fixture broker", account=account, run_id=run, binding_hash="a" * 64
    )
    return record, config


def test_broker_projection_is_sanitized_historical_and_never_ready():
    record, config = observation()
    result = project_observation(record, config, AT + timedelta(days=1))
    assert result["snapshot"]["display_status"] == "STALE_RECORDED"
    assert result["current_positions"] == "UNKNOWN" and not result["entry_ready"]
    assert not result["execution_enabled"]
    assert config.account.login not in str(result)
    assert "terminal.exe" not in str(result) and "bid" not in str(result)


@pytest.mark.parametrize("offset,expected", [(0, "RECORDED_WINDOW_ONLY"), (61, "EXPIRED")])
def test_recent_receipt_does_not_qualify_clock_or_quote(offset, expected):
    record, config = observation()
    snap = record.body.snapshot.model_copy(
        update={
            "time_policy_from": AT - timedelta(minutes=1),
            "time_policy_until": AT + timedelta(minutes=1),
            "time_policy_evidence": "fixture evidence",
        }
    )
    record = record.model_copy(update={"body": record.body.model_copy(update={"snapshot": snap})})
    result = project_observation(record, config, AT + timedelta(seconds=offset))
    assert result["recorded_clock_policy"] == expected
    assert result["transport_at_capture"] == "CONNECTED"
    assert result["quote_freshness"] == "UNVERIFIED"
    assert all(v is None for v in result["snapshot"]["quote_ages_seconds"].values())
    assert result["snapshot"]["recorded_quote_ages_seconds"]
    assert not result["entry_ready"]


def test_missing_or_invalid_recorded_policy_never_becomes_verified():
    record, config = observation()
    assert project_observation(record, config, AT)["recorded_clock_policy"] == "UNKNOWN"
    snap = record.body.snapshot.model_copy(
        update={
            "time_policy_from": AT + timedelta(seconds=1),
            "time_policy_until": AT + timedelta(minutes=1),
            "time_policy_evidence": "fixture evidence",
        }
    )
    record = record.model_copy(update={"body": record.body.model_copy(update={"snapshot": snap})})
    assert project_observation(record, config, AT)["recorded_clock_policy"] == "INVALID_AT_CAPTURE"


@pytest.mark.parametrize("fault", ["account", "run", "binding", "future", "live"])
def test_broker_scope_and_time_fail_closed(fault):
    record, config = observation()
    data = config.model_dump(mode="json")
    if fault == "account":
        data["account"]["login"] = "99999"
    if fault == "run":
        data["run_id"] = str(uuid4())
    if fault == "binding":
        data["binding_hash"] = "b" * 64
    if fault == "live":
        data["account"]["environment"] = "LIVE"
        data["account"]["venue"] = "BROKER_LIVE"
    with pytest.raises(ValueError):
        value = BrokerViewConfig.model_validate(data)
        project_observation(record, value, AT - timedelta(seconds=1) if fault == "future" else AT)
