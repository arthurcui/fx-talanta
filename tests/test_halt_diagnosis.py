import copy
import json
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from fx_talanta.research.halt_diagnosis import reproduce
from fx_talanta.research.replay import Costs


@pytest.fixture
def checkpoint():
    data = json.loads((Path(__file__).parent / "fixtures/research-halt.json").read_text())
    # Controlled preceding quote: 0.2 pip below the retained trigger, 106 ms earlier.
    # The production diagnosis instead extracts both exact quotes from the pinned index.
    previous = copy.deepcopy(data["market"])
    at = datetime.fromisoformat(data["at"]) - timedelta(milliseconds=106)
    previous["at"] = at.isoformat()
    for q in previous["quotes"]:
        q["at"] = at.isoformat()
        for field in ("bid", "ask"):
            q[field] = str(Decimal(q[field]) - Decimal("0.00002"))
    data.update(previous_market=previous, previous_at=at.isoformat())
    return data


@pytest.fixture
def costs():
    return Costs(
        commission_per_lot_per_side="4",
        slippage_per_lot_per_side="2",
        financing_per_lot_day="3",
        basis="Original research assumptions",
    )


def test_targeted_replay_reproduces_giveback_breach_without_new_entry(checkpoint, costs):
    original = copy.deepcopy(checkpoint)
    report = reproduce(checkpoint, costs)
    assert checkpoint == original
    assert report["historical_observations"] == 2
    assert report["elapsed_seconds"] == 0.106
    assert Decimal(report["before"]["aggregate_risk"]) == Decimal("9.92")
    assert Decimal(report["before"]["excess"]) < 0
    assert Decimal(report["trigger"]["aggregate_risk"]) == Decimal("10.08")
    assert Decimal(report["trigger"]["excess"]) > 0
    p = report["trigger"]["positions"][0]
    assert Decimal(p["entry_to_stop_loss"]) == Decimal("7.12")
    assert Decimal(p["unrealized_pnl"]) == Decimal("2.08")
    assert Decimal(p["incremental_exit_buffer"]) == Decimal("0.88")
    assert Decimal(report["trigger"]["pending_reservation_risk"]) == 0
    assert [d["action"] for d in report["new_deals"]] == ["CLOSE"]
    assert report["final_state"] == "HARD_HALT"
    assert report["remaining_positions"] == 0
    assert report["policy_unchanged"] and report["repeated_quote_stays_halted"]
    assert not report["execution_enabled"]


def test_replay_rejects_already_breached_preceding_quote(checkpoint, costs):
    checkpoint["previous_market"] = copy.deepcopy(checkpoint["market"])
    with pytest.raises(ValueError, match="preceding checkpoint"):
        reproduce(checkpoint, costs)


def test_replay_rejects_nonlocal_time_window(checkpoint, costs):
    checkpoint["previous_at"] = (
        datetime.fromisoformat(checkpoint["at"]) - timedelta(seconds=6)
    ).isoformat()
    with pytest.raises(ValueError, match="adjacent fresh"):
        reproduce(checkpoint, costs)


def test_replay_rejects_halted_checkpoint(checkpoint, costs):
    checkpoint["gateway"]["integrity_halt"] = True
    with pytest.raises(ValueError, match="unhalted matching"):
        reproduce(checkpoint, costs)
