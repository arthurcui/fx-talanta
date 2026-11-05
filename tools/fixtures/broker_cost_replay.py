"""Constructed rollover/quote-gap replay. No historical calibration claim."""

import argparse
from datetime import UTC, datetime
from pathlib import Path

from fx_talanta.research.broker_costs import BrokerCosts
from fx_talanta.research.replay import Dataset, Experiment
from tools.fixtures.b01_replay import AT
from tools.fixtures.b01_replay import scenario as legacy_scenario


def scenario():
    data, experiment = legacy_scenario()
    at = datetime(2025, 1, 8, 19, tzinfo=UTC)
    delta = at - AT
    data = Dataset.model_validate(
        {
            **data.model_dump(),
            "source": "Synthetic Wednesday rollover across a quote gap; not broker observations",
            "bars": tuple(
                b.model_copy(
                    update={"close_at": b.close_at + delta, "available_at": b.available_at + delta}
                )
                for b in data.bars
            ),
            "events": tuple(
                e.model_copy(
                    update={
                        "available_at": e.available_at + delta,
                        "market": e.market.model_copy(
                            update={
                                "at": e.market.at + delta,
                                "quotes": tuple(
                                    q.model_copy(update={"at": q.at + delta})
                                    for q in e.market.quotes
                                ),
                            }
                        ),
                    }
                )
                for e in data.events
            ),
        }
    )
    bounds = {
        k: getattr(experiment, k) + delta
        for k in ("start", "training_end", "validation_end", "end")
    }
    costs = BrokerCosts(
        version="broker-costs/1",
        symbol="EURUSD",
        account_currency="USD",
        broker="synthetic",
        account_plan="fixture USD-notional",
        status="SYNTHETIC",
        evidence="constructed commission schedule",
        basis="Fixture only; not calibrated",
        valid_from=bounds["start"],
        valid_until=bounds["end"],
        available_at=bounds["start"],
        commission_usd_per_100k="7",
        slippage_per_lot_per_side="2",
        commission_reserve_per_lot_per_side="10",
        financing_reserve_per_lot="15",
        rollover_convention="NEW_YORK_17_WEEKDAYS_EXPLICIT_MULTIPLIERS",
        swap_days=(
            {
                "cutoff": datetime(2025, 1, 8, 22, tzinfo=UTC),
                "available_at": bounds["start"],
                "multiplier": 3,
                "buy_usd_per_lot": "-5",
                "sell_usd_per_lot": "2",
                "evidence": "synthetic side-specific Wednesday rate",
            },
        ),
    )
    experiment = Experiment.model_validate(
        {**experiment.model_dump(), **bounds, "name": "synthetic-broker-costs", "costs": costs}
    )
    return data, experiment


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    data, experiment = scenario()
    args.output.mkdir(parents=True, exist_ok=False)
    for name, value in (("dataset", data), ("experiment", experiment)):
        with (args.output / f"{name}.json").open("x") as stream:
            stream.write(value.model_dump_json(indent=2) + "\n")


if __name__ == "__main__":
    main()
