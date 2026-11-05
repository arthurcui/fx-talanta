import json
import shutil
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from fx_talanta.research.replay import Dataset, run
from tools.fixtures.b01_replay import AT, scenario
from tools.qualification.b01_parity import qualify


@pytest.mark.skipif(
    shutil.which("node") is None, reason="Node reference runs explicitly in host CI"
)
def test_independent_rational_reference_and_pinned_evidence():
    result = qualify()
    pinned = json.loads(
        (Path(__file__).parents[1] / "docs/evidence/m3-numerical-parity-20261105.json").read_text()
    )
    for key in ("cases", "vectors_sha256", "reference_sha256", "baseline_sha256"):
        assert result[key] == pinned[key]
    assert len(result["cases"]) == 36
    assert result["passed"] and not result["execution_enabled"]
    assert not result["mql5_native_parity"]


def test_gap_exit_waits_for_fresh_quote_and_uses_adverse_observed_fill():
    data, experiment = scenario()
    stale = data.events[3]
    quote = stale.market.quotes[0].model_copy(
        update={"bid": Decimal("1.0100"), "ask": Decimal("1.0101")}
    )
    stale = stale.model_copy(
        update={
            "available_at": AT + timedelta(seconds=10),
            "market": stale.market.model_copy(update={"quotes": (quote,)}),
        }
    )
    fresh_at = AT + timedelta(seconds=11)
    fresh = stale.model_copy(
        update={
            "available_at": fresh_at,
            "market": stale.market.model_copy(
                update={"at": fresh_at, "quotes": (quote.model_copy(update={"at": fresh_at}),)}
            ),
        }
    )
    changed = Dataset.model_validate(
        {**data.model_dump(), "events": data.events[:3] + (stale, fresh) + data.events[4:]}
    )
    result, _ = run(changed, experiment, "training")
    assert [d["action"] for d in result["deals"]] == ["ENTER", "CLOSE"]
    close = result["deals"][1]
    assert close["at"] == fresh_at.isoformat().replace("+00:00", "Z")
    assert Decimal(close["price"]) == Decimal("1.00998")
    assert result["fully_settled"]


def test_higher_costs_reduce_per_lot_returns_without_increasing_volume():
    data, experiment = scenario()
    base, _ = run(data, experiment, "training")
    costs = experiment.costs.model_copy(
        update={
            "commission_per_lot_per_side": Decimal("8"),
            "slippage_per_lot_per_side": Decimal("4"),
            "financing_per_lot_day": Decimal("6"),
        }
    )
    stressed, _ = run(data, experiment.model_copy(update={"costs": costs}), "training")
    base_volume = Decimal(base["deals"][0]["volume"])
    stress_volume = Decimal(stressed["deals"][0]["volume"])
    assert stress_volume <= base_volume
    assert (
        Decimal(stressed["net_realized_pnl"]) / stress_volume
        < Decimal(base["net_realized_pnl"]) / base_volume
    )
    assert stressed["fully_settled"] and not stressed["execution_enabled"]


def test_ohlc_only_dataset_cannot_invent_execution_path():
    data, _ = scenario()
    with pytest.raises(ValueError):
        Dataset.model_validate({**data.model_dump(), "events": ()})
