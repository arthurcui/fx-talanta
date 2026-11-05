"""Create an explicitly synthetic B01 training fixture; no network or broker access."""

import argparse
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from fx_talanta.domain.offline import Instrument, Market, Policy, Quote
from fx_talanta.research.baseline import Bar
from fx_talanta.research.replay import Costs, Dataset, Event, Experiment

AT = datetime(2026, 11, 5, 12, tzinfo=UTC)


def bars():
    history = []
    for i in range(200):
        price = Decimal("1") + Decimal(i) / 10000
        at = AT - timedelta(hours=199 - i)
        history.append(
            Bar(
                symbol="EURUSD",
                timeframe="H1",
                close_at=at,
                available_at=at,
                revision=1,
                open=price,
                high=price,
                low=price,
                close=price,
            )
        )
    for i in range(21):
        at = AT - timedelta(minutes=(20 - i) * 15)
        history.append(
            Bar(
                symbol="EURUSD",
                timeframe="M15",
                close_at=at,
                available_at=at,
                revision=1,
                open="1.019",
                high="1.0201" if i == 20 else "1.0191",
                low="1.0189",
                close="1.0200" if i == 20 else "1.019",
            )
        )
    return history


def scenario():
    history = bars()
    instrument = Instrument(
        symbol="EURUSD",
        base="EUR",
        quote="USD",
        minimum_stop="0.00005",
        maximum_spread="0.0003",
        maximum_adverse_move="0.0005",
    )
    events = []
    for seconds, bid in [
        (-2, "1.0199"),
        (-1, "1.0199"),
        (1, "1.0200"),
        (2, "1.0200"),
        (14400, "1.0200"),
        (14401, "1.0200"),
    ]:
        at = AT + timedelta(seconds=seconds)
        events.append(
            Event(
                available_at=at,
                market=Market(
                    at=at,
                    quotes=(
                        Quote(
                            symbol="EURUSD", bid=bid, ask=Decimal(bid) + Decimal("0.0001"), at=at
                        ),
                    ),
                    instruments=(instrument,),
                    conversion={"USD": Decimal(1), "EUR": Decimal(bid)},
                ),
            )
        )
    data = Dataset(
        provenance="SYNTHETIC",
        source="Constructed lifecycle validation, not broker history",
        session_calendar="Synthetic continuous weekdays",
        bar_price_basis="BID",
        history_complete=True,
        bars=tuple(history),
        events=tuple(events),
    )
    experiment = Experiment(
        name="synthetic-lifecycle",
        symbol="EURUSD",
        start=AT - timedelta(seconds=3),
        training_end=AT + timedelta(hours=5),
        validation_end=AT + timedelta(hours=6),
        end=AT + timedelta(hours=7),
        costs=Costs(
            commission_per_lot_per_side="4",
            slippage_per_lot_per_side="2",
            financing_per_lot_day="3",
            basis="Synthetic explicit costs in USD, not a broker estimate",
        ),
        policy=Policy(maximum_positions=1),
    )
    return data, experiment


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    data, experiment = scenario()
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / "dataset.json").write_text(
        data.model_dump_json(indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    (args.output / "experiment.json").write_text(
        experiment.model_dump_json(indent=2) + "\n", encoding="utf-8", newline="\n"
    )


if __name__ == "__main__":
    main()
