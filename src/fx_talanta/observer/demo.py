from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fx_talanta.clock import FakeClock
from fx_talanta.domain.models import Environment
from fx_talanta.observer.contracts import Binding
from fx_talanta.observer.fixtures import FixtureReader
from fx_talanta.observer.supervisor import Observer
from fx_talanta.storage.config import fixture_account


def fixture_binding():
    return Binding(
        account=fixture_account(Environment.PAPER),
        terminal_path="C:/fx-talanta-fixture/terminal64.exe",
        data_path="C:/fx-talanta-fixture/data",
        expected_build=1,
    )


def run_observer_demo(settings):
    clock = FakeClock(datetime(2026, 1, 5, 12, tzinfo=UTC))
    binding = fixture_binding()
    run_id = uuid4()
    states = []
    for fault in ("NONE", "DISCONNECTED", "NONE", "BUILD"):
        # Reopen on each poll to demonstrate durable retry/recovery and build fencing.
        observer = Observer(settings.runtime_dsn(Environment.PAPER), binding, run_id, clock)
        try:
            record = observer.poll(FixtureReader(fault))
            states.append({"state": record.body.state, "reason": record.body.reason})
        finally:
            observer.close()
        clock.advance(timedelta(seconds=3))
    return {
        "run_id": str(run_id),
        "provenance": "SCRIPTED_FIXTURE",
        "states": states,
        "broker_connected": False,
        "order_interface": False,
    }
