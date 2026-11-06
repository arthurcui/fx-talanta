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
