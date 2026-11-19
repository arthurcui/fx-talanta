"""Export a clearly synthetic UI bundle, not historical or profitability evidence."""

import json

from tools.fixtures.b01_replay import scenario


def bundle():
    dataset, experiment = scenario()
    policy = experiment.policy.model_copy(
        update={
            "trade_fraction": experiment.policy.trade_fraction / 5,
            "aggregate_fraction": experiment.policy.aggregate_fraction / 5,
            "daily_fraction": experiment.policy.daily_fraction / 5,
        }
    )
    experiment = experiment.model_copy(update={"policy": policy})
    return dict(
        dataset=dataset.model_dump(mode="json"),
        experiment=experiment.model_dump(mode="json"),
        minimum_closed_trades=1,
        maximum_drawdown_fraction="0.05",
    )


if __name__ == "__main__":
    print(json.dumps(bundle(), indent=2))
