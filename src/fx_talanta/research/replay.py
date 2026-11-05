"""Availability-ordered, simulator-only B01 replay and immutable experiments."""

import argparse
import json
from datetime import datetime
from decimal import Decimal, localcontext
from hashlib import sha256
from pathlib import Path
from typing import Literal
from uuid import NAMESPACE_URL, uuid5

from pydantic import Field, model_validator

from fx_talanta.brokers.simulator import Simulator
from fx_talanta.clock import FakeClock
from fx_talanta.domain.models import (
    AccountIdentity,
    Decision,
    DecisionAttempt,
    FrozenModel,
    ModelTrace,
    NonNegative,
    Record,
    Timestamp,
    Versions,
)
from fx_talanta.domain.offline import EntryIntent, Fault, Market, Policy
from fx_talanta.gateway.offline import Gateway
from fx_talanta.research.baseline import VERSION, Bar, evaluate
from fx_talanta.risk.governor import equity, health_reason

LIMIT = 32 * 1024 * 1024


def digest(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class Costs(FrozenModel):
    commission_per_lot_per_side: NonNegative
    slippage_per_lot_per_side: NonNegative
    financing_per_lot_day: NonNegative
    basis: str = Field(min_length=1, max_length=500)


class Event(FrozenModel):
    available_at: Timestamp
    market: Market
    fault: Fault = Fault()

    @model_validator(mode="after")
    def timing(self):
        if self.available_at < self.market.at:
            raise ValueError("market cannot arrive before its observation time")
        if self.fault.kind not in {"NORMAL", "REJECT", "PARTIAL"} or self.fault.price_delta:
            raise ValueError("this replay supports normal, rejected and partial entry fills")
        return self


class Dataset(FrozenModel):
    provenance: Literal["SYNTHETIC", "HISTORICAL_UNQUALIFIED"]
    source: str = Field(min_length=1, max_length=500)
    session_calendar: str = Field(min_length=1, max_length=500)
    bar_price_basis: Literal["BID"]
    history_complete: bool = False
    bars: tuple[Bar, ...] = Field(max_length=20000)
    events: tuple[Event, ...] = Field(min_length=1, max_length=50000)

    @model_validator(mode="after")
    def ordered(self):
        times = [e.available_at for e in self.events]
        if times != sorted(times) or len(times) != len(set(times)):
            raise ValueError("market arrivals must be strictly ordered")
        return self


class Experiment(FrozenModel):
    name: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,79}$")
    symbol: Literal["EURUSD", "USDJPY"]
    start: Timestamp
    training_end: Timestamp
    validation_end: Timestamp
    end: Timestamp
    costs: Costs
    policy: Policy

    @model_validator(mode="after")
    def boundaries(self):
        if not self.start < self.training_end < self.validation_end < self.end:
            raise ValueError("chronological training/validation/holdout intervals required")
        if self.policy.maximum_positions != 1:
            raise ValueError("B01 replay allows one position at a time")
        return self

    def window(self, partition):
        return {
            "training": (self.start, self.training_end),
            "validation": (self.training_end, self.validation_end),
            "holdout": (self.validation_end, self.end),
        }[partition]


class CostSimulator(Simulator):
    """Same simulator order semantics, with explicit adverse fills and financing."""

    def __init__(self, store, capital, costs):
        super().__init__(store, capital)
        self.costs, self.financing, self.fill_costs = costs, [], []

    def record_cost(self, request, market, result):
        if result.filled:
            q, spec = market.quote_for(request.symbol), market.spec_for(request.symbol)
            self.fill_costs.append(
                {
                    "request_id": str(request.request_id),
                    "commission": str(result.filled * self.costs.commission_per_lot_per_side),
                    "slippage": str(result.filled * self.costs.slippage_per_lot_per_side),
                    "half_spread": str(
                        (q.ask - q.bid)
                        / 2
                        * result.filled
                        * spec.contract_size
                        * market.conversion[spec.quote]
                    ),
                }
            )

    def shifted(self, market, symbol, buy):
        q, spec = market.quote_for(symbol), market.spec_for(symbol)
        amount = self.costs.slippage_per_lot_per_side / (
            spec.contract_size * market.conversion[spec.quote]
        )
        delta = amount if buy else -amount
        quote = q.model_copy(update={"bid": q.bid + delta, "ask": q.ask + delta})
        return Market.model_validate(
            {
                **market.model_dump(),
                "quotes": tuple(quote if x.symbol == symbol else x for x in market.quotes),
            }
        )

    def _enter(self, request, market, fault):
        result = super()._enter(
            request, self.shifted(market, request.symbol, request.side == "BUY"), fault
        )
        self.record_cost(request, market, result)
        return result

    def _manage(self, request, market):
        if request.action != "CLOSE":
            return super()._manage(request, market)
        position = next(
            (p for p in self.book.positions if p.position_id == request.position_id), None
        )
        if position is None:
            return super()._manage(request, market)
        result = super()._manage(
            request, self.shifted(market, request.symbol, position.side == "SELL")
        )
        if result.state == "FILLED":
            self.record_cost(request, market, result)
            entered = next(
                d.at
                for d in self.book.deals
                if d.position_id == position.position_id and d.action == "ENTER"
            )
            days = Decimal(str((self.store.clock.now() - entered).total_seconds())) / 86400
            charge = days * self.costs.financing_per_lot_day * result.filled
            deal = self.book.deals[-1]
            self.financing.append({"deal_id": str(deal.deal_id), "charge": str(charge)})
            self.book = self.book.model_copy(
                update={
                    "balance": self.book.balance - charge,
                    "deals": self.book.deals[:-1]
                    + (deal.model_copy(update={"realized": deal.realized - charge}),),
                    "positions": tuple(
                        p.model_copy(update={"realized": p.realized - charge})
                        if p.position_id == position.position_id
                        else p
                        for p in self.book.positions
                    ),
                }
            )
        return result


def priced(market, costs):
    return Market.model_validate(
        {
            **market.model_dump(),
            "instruments": tuple(
                s.model_copy(
                    update={
                        "commission_per_lot": costs.commission_per_lot_per_side,
                        "slippage_per_lot": costs.slippage_per_lot_per_side * 2,
                        # Budget a day; delayed exits can exceed this estimate.
                        "financing_per_lot": costs.financing_per_lot_day,
                    }
                )
                for s in market.instruments
            ),
        }
    )


def run(dataset, experiment, partition):
    dataset = Dataset.model_validate_json(dataset.model_dump_json())
    experiment = Experiment.model_validate_json(experiment.model_dump_json())
    start, end = experiment.window(partition)
    events = {e.available_at: e for e in dataset.events if start <= e.available_at < end}
    if not events:
        raise ValueError("partition has no market evidence")
    if any({q.symbol for q in e.market.quotes} != {experiment.symbol} for e in events.values()):
        raise ValueError("replay market must contain exactly the experiment symbol")
    timeline = sorted(
        set(events) | {b.available_at for b in dataset.bars if start <= b.available_at < end}
    )
    bar_times = {b.available_at for b in dataset.bars}
    run_id = uuid5(
        NAMESPACE_URL,
        digest(
            {
                "dataset": dataset.model_dump(mode="json"),
                "experiment": experiment.model_dump(mode="json"),
                "partition": partition,
                "strategy": VERSION,
            }
        ),
    )
    account = AccountIdentity(
        environment="PAPER", venue="SIMULATOR", broker="REPLAY", server="OFFLINE", login="B01"
    )
    clock = FakeClock(start)
    gateway = Gateway.for_replay(account, run_id, clock, experiment.policy)
    gateway.broker = CostSimulator(gateway.store, experiment.policy.capital, experiment.costs)
    pending, seen, decisions, samples, final_market = None, set(), [], [], None
    with localcontext() as context:
        context.prec = 34
        try:
            for at in timeline:
                clock.advance(at - clock.now())
                if pending and at >= datetime.fromisoformat(pending["expires_at"]):
                    decisions.append(
                        {
                            "at": at.isoformat(),
                            "action": "EXPIRED",
                            "signal": pending["signal_bar_close"],
                        }
                    )
                    pending = None
                if at in bar_times:
                    candidate = evaluate(
                        dataset.bars,
                        experiment.symbol,
                        at,
                        history_complete=dataset.history_complete,
                        position_open=any(p.volume for p in gateway.broker.book.positions),
                    )
                    decisions.append(candidate)
                    if (
                        candidate["action"] == "CANDIDATE"
                        and candidate["signal_bar_close"] not in seen
                    ):
                        pending = candidate
                        seen.add(candidate["signal_bar_close"])
                if at not in events:
                    continue
                event = events[at]
                market = priced(event.market, experiment.costs)
                gateway.reconcile(market)
                final_market = market
                if pending:
                    q, spec = (
                        market.quote_for(experiment.symbol),
                        market.spec_for(experiment.symbol),
                    )
                    after_signal = q.at > datetime.fromisoformat(pending["as_of"])
                    if (
                        after_signal
                        and gateway.book.state == "RUNNING"
                        and health_reason(market, at, experiment.policy) is None
                        and q.ask - q.bid <= spec.maximum_spread
                    ):
                        side = pending["side"]
                        distance = Decimal(pending["stop_distance"])
                        price = q.ask if side == "BUY" else q.bid
                        sign = 1 if side == "BUY" else -1
                        benchmark = Decimal(pending["signal_price"])
                        if sign * (price - benchmark) > spec.maximum_adverse_move:
                            samples.append(
                                {
                                    "at": at.isoformat(),
                                    "equity": str(equity(gateway.broker.book, market)),
                                    "state": gateway.book.state,
                                }
                            )
                            continue
                        decision_id = uuid5(run_id, "decision/" + pending["signal_bar_close"])
                        decision = Decision(
                            account=account,
                            action="ENTER",
                            candidate_id=VERSION,
                            symbol=experiment.symbol,
                            side=side,
                            expires_at=pending["expires_at"],
                            rationale="Frozen B01 replay candidate",
                        )
                        record = Record(
                            record_id=decision_id,
                            account=account,
                            recorded_at=datetime.fromisoformat(pending["as_of"]),
                            correlation_id=run_id,
                            provenance="OFFLINE_SIMULATION",
                            versions=Versions(strategy=VERSION, policy=experiment.policy.version),
                            body=DecisionAttempt(
                                result="VALID",
                                action="ENTER",
                                cutoff=pending["as_of"],
                                input_snapshot=pending["input_hash"],
                                candidates=(VERSION,),
                                response=decision.model_dump_json(),
                                decision=decision,
                                reason="Research-only signal",
                                trace=ModelTrace(request_id=uuid5(decision_id, "trace")),
                            ),
                        )
                        gateway.store.append_batch((record,))
                        intent = EntryIntent(
                            intent_id=uuid5(decision_id, "entry"),
                            account=account,
                            decision_id=decision_id,
                            strategy=VERSION,
                            policy_version=experiment.policy.version,
                            symbol=experiment.symbol,
                            side=side,
                            stop=price - sign * distance,
                            target=price + sign * distance * 2,
                            benchmark=benchmark,
                            expires_at=pending["expires_at"],
                            exit_at=pending["time_exit_at"],
                        )
                        gateway.broker.next_fault = event.fault
                        entry = gateway.submit(intent, market)
                        decisions.append(
                            {
                                "at": at.isoformat(),
                                "action": "SUBMITTED_TO_SIMULATOR",
                                "state": entry.state,
                                "reason": entry.reason,
                                "signal": pending["signal_bar_close"],
                            }
                        )
                        pending = None
                samples.append(
                    {
                        "at": at.isoformat(),
                        "equity": str(equity(gateway.broker.book, market)),
                        "state": gateway.book.state,
                    }
                )
            book = gateway.broker.book
            result = {
                "schema": "b01-replay/1",
                "strategy": VERSION,
                "partition": partition,
                "provenance": dataset.provenance,
                "source": dataset.source,
                "experiment": experiment.model_dump(mode="json"),
                "run_id": str(run_id),
                "decisions": decisions,
                "equity_samples": samples,
                "deals": [d.model_dump(mode="json") for d in book.deals],
                "financing": gateway.broker.financing,
                "fill_costs": gateway.broker.fill_costs,
                "cost_note": "Spread/slippage are embedded in fills; do not subtract them twice.",
                "balance": str(book.balance),
                "marked_equity": str(equity(book, final_market)),
                "open_positions": sum(bool(p.volume) for p in book.positions),
                "pending_signal": pending is not None,
                "commission": str(sum((d.commission for d in book.deals), Decimal(0))),
                "net_realized_pnl": str(book.balance - book.initial_balance),
                "journal_tip": gateway.store.journal[-1]["hash"],
                "execution_enabled": False,
                "m1_qualified": False,
                "economic_acceptance": False,
            }
            closed = [p.realized for p in book.positions if not p.volume]
            peak, drawdown = experiment.policy.capital, Decimal(0)
            for sample in samples:
                value = Decimal(sample["equity"])
                peak = max(peak, value)
                drawdown = max(drawdown, (peak - value) / peak)
            result["metrics"] = {
                "closed_trades": len(closed),
                "winning_trades": sum(p > 0 for p in closed),
                "net_expectancy": str(sum(closed) / len(closed)) if closed else None,
                "maximum_observed_drawdown_fraction": str(drawdown),
                "uncertainty": "Bounded sample: no economic inference or annualized ratios.",
            }
            result["unsettled_entry_orders"] = sum(
                o.remaining > 0
                for o in book.orders
                if o.state not in {"CANCELLED", "REJECTED", "FILLED"}
            )
            result["fully_settled"] = not (
                result["open_positions"] or result["unsettled_entry_orders"]
            )
            result["marking_limitations"] = (
                "Open equity excludes uncharged financing and future close costs; "
                "gaps between quotes are unobserved."
            )
            return result, gateway.store.journal
        finally:
            gateway.close()


def read(path):
    with Path(path).open("rb") as stream:
        raw = stream.read(LIMIT + 1)
    if len(raw) > LIMIT:
        raise ValueError("input bound")
    return raw


def source_hash():
    root = Path(__file__).resolve().parents[1]
    paths = [
        "research/baseline.py",
        "research/replay.py",
        "research/store.py",
        "risk/governor.py",
        "gateway/offline.py",
        "brokers/simulator.py",
        "domain/offline.py",
        "domain/models.py",
    ]
    return digest(
        {p: sha256((root / p).read_bytes().replace(b"\r\n", b"\n")).hexdigest() for p in paths}
    )


def register(directory, dataset_path, experiment_path):
    data, spec = read(dataset_path), read(experiment_path)
    Dataset.model_validate_json(data)
    experiment = Experiment.model_validate_json(spec)
    manifest = {
        "schema": "b01-experiment/1",
        "dataset_sha256": sha256(data).hexdigest(),
        "engine_sha256": source_hash(),
        "experiment": experiment.model_dump(mode="json"),
    }
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    (directory / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    (directory / "registered.sha256").write_text(
        digest(manifest) + "\n", encoding="utf-8", newline="\n"
    )
    return manifest


def verify_result(directory, manifest):
    receipt = json.loads(read(directory / "receipt.json"))
    result = json.loads(read(directory / "result.json"))
    journal = json.loads(read(directory / "journal.json"))
    expected = {
        "result_hash": digest(result),
        "journal_hash": digest(journal),
        "manifest_hash": digest(manifest),
    }
    if receipt != expected:
        raise ValueError("prior partition evidence changed")
    previous = "0" * 64
    for item in journal:
        if item["payload"]["previous"] != previous or digest(item["payload"]) != item["hash"]:
            raise ValueError("journal chain invalid")
        previous = item["hash"]
    if previous != result["journal_tip"]:
        raise ValueError("journal tip mismatch")


def execute(directory, dataset_path, partition):
    directory = Path(directory)
    manifest = json.loads(read(directory / "manifest.json"))
    if read(directory / "registered.sha256").decode().strip() != digest(manifest):
        raise ValueError("registered manifest changed")
    raw = read(dataset_path)
    if (
        manifest["engine_sha256"] != source_hash()
        or manifest["dataset_sha256"] != sha256(raw).hexdigest()
    ):
        raise ValueError("registered source or dataset changed; register a distinct experiment")
    if partition not in {"training", "validation", "holdout"}:
        raise ValueError("unknown partition")
    for previous in {
        "training": (),
        "validation": ("training",),
        "holdout": ("training", "validation"),
    }[partition]:
        verify_result(directory / previous, manifest)
    output = directory / partition
    output.mkdir(exist_ok=False)  # Includes failed attempts; no overwrite or hidden retry.
    try:
        result, journal = run(
            Dataset.model_validate_json(raw),
            Experiment.model_validate(manifest["experiment"]),
            partition,
        )
        (output / "journal.json").write_text(
            json.dumps(journal, indent=2) + "\n", encoding="utf-8", newline="\n"
        )
        (output / "result.json").write_text(
            json.dumps(result, indent=2) + "\n", encoding="utf-8", newline="\n"
        )
        (output / "receipt.json").write_text(
            json.dumps(
                {
                    "result_hash": digest(result),
                    "journal_hash": digest(journal),
                    "manifest_hash": digest(manifest),
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
            newline="\n",
        )
        return result
    except Exception:
        (output / "failed.json").write_text(
            '{"status":"FAILED","retry_allowed":false}\n', encoding="utf-8", newline="\n"
        )
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    registration = sub.add_parser("register")
    registration.add_argument("--experiment", type=Path, required=True)
    for item in (registration, sub.add_parser("run")):
        item.add_argument("--directory", type=Path, required=True)
        item.add_argument("--dataset", type=Path, required=True)
        if item is not registration:
            item.add_argument(
                "--partition", choices=("training", "validation", "holdout"), required=True
            )
    args = parser.parse_args(argv)
    try:
        if args.command == "register":
            register(args.directory, args.dataset, args.experiment)
            print("Experiment registered before replay; execution disabled.")
        else:
            result = execute(args.directory, args.dataset, args.partition)
            print(
                json.dumps(
                    {
                        "partition": args.partition,
                        "result_hash": digest(result),
                        "open_positions": result["open_positions"],
                        "execution_enabled": False,
                    }
                )
            )
        return 0
    except (OSError, ValueError, KeyError, TypeError):
        print("Replay rejected or failed; preserve evidence and register changes separately.")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
