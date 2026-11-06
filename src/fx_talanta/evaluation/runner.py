"""Incremental PAPER runner engineering: simulator and scripted selectors only.

Every admission commits its input and deterministic transition atomically. Restart
rebuilds only local simulator state; no broker, provider, credential or network path.
"""

import argparse
import hashlib
import json
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta
from decimal import Decimal, localcontext
from pathlib import Path
from typing import Annotated, Literal
from uuid import UUID, uuid5

from pydantic import Field, model_validator

from fx_talanta.advisor.proposal_contracts import Selection
from fx_talanta.clock import FakeClock, SystemClock
from fx_talanta.domain.models import (
    AccountIdentity,
    Decision,
    DecisionAttempt,
    FrozenModel,
    ModelTrace,
    Record,
    Timestamp,
    Versions,
)
from fx_talanta.domain.offline import EntryIntent, Fault, Instrument, Market, Policy
from fx_talanta.evaluation.inputs import SourceRecord, bars_hash, project
from fx_talanta.evaluation.ledger import Ledger, Registration, canonical, digest
from fx_talanta.evaluation.matched import ARM_NAMES
from fx_talanta.gateway.offline import TERMINAL, Gateway
from fx_talanta.research.baseline import VERSION, Bar, evaluate, visible
from fx_talanta.research.replay import Costs, CostSimulator, priced
from fx_talanta.risk.governor import health_reason

LIMIT = 64 * 1024 * 1024


class Config(FrozenModel):
    version: Literal["paper-simulation-runner/1"] = "paper-simulation-runner/1"
    run_id: UUID
    start: Timestamp
    deadline: Timestamp
    provenance: Literal["SYNTHETIC", "RECORDED_OFFLINE"]
    venue: Literal["SIMULATOR"] = "SIMULATOR"
    execution_enabled: Literal[False] = False
    strategy: Literal["B01-research/1"] = VERSION
    selector: Literal["SCRIPTED_TEST_DOUBLE"] = "SCRIPTED_TEST_DOUBLE"
    symbol: Literal["EURUSD", "USDJPY"]
    instrument: Instrument
    history_complete: bool = False
    policy: Policy
    costs: Costs
    max_observations: Annotated[int, Field(strict=True, ge=1, le=250)] = 100
    max_entries_per_arm: Annotated[int, Field(strict=True, ge=1, le=100)] = 10

    @model_validator(mode="after")
    def bounded(self):
        if self.deadline <= self.start or self.policy.maximum_positions != 1:
            raise ValueError("positive fixed window and one position per arm required")
        if self.instrument.symbol != self.symbol:
            raise ValueError("instrument binding mismatch")
        return self


class Tick(FrozenModel):
    event_id: UUID
    sequence: Annotated[int, Field(strict=True, ge=1)]
    market: Market
    bars: Annotated[tuple[Bar, ...], Field(max_length=1000)] = ()
    news: Literal["NEUTRAL", "ADVERSE", "UNAVAILABLE"] = "UNAVAILABLE"
    selector_result: Literal["SELECT", "HOLD", "TIMEOUT", "MALFORMED"] = "SELECT"
    fault: Fault = Fault()
    source_record: SourceRecord | None = None

    @model_validator(mode="after")
    def deterministic_fault(self):
        if self.fault.kind not in {"NORMAL", "REJECT", "LOST_RESPONSE", "NO_STOP"}:
            raise ValueError("unsupported runner fault")
        if self.fault.price_delta:
            raise ValueError("use frozen cost terms, not arbitrary fill deltas")
        if self.source_record:
            source = self.source_record
            market, news = project(source, source.normalized_at)
            if (
                self.market != market
                or self.news != news
                or self.event_id != source.event_id
                or self.sequence != source.sequence
                or bars_hash(self.bars) != source.bars_hash
                or any(b.available_at > source.received_at for b in self.bars)
                or self.selector_result != "SELECT"
                or self.fault != Fault()
            ):
                raise ValueError("normalized input differs from preserved source")
        return self


def engine_hash():
    root = Path(__file__).resolve().parents[1]
    return digest(
        {
            p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*.py"))
        }
    )


def registration(config):
    artifacts = {}

    def artifact(value):
        raw = canonical(value)
        sha = hashlib.sha256(raw.encode()).hexdigest()
        artifacts[sha] = raw
        return sha

    shared = artifact(config.policy.model_dump(mode="json"))
    model, prompt = artifact(config.selector), artifact("fixture selection over B01 or HOLD/1")
    ai_policy = artifact("shared scripted selector policy/1")
    return Registration.model_validate(
        dict(
            plan=dict(
                schema_version="matched-receipt-plan/1",
                run_id=config.run_id,
                provenance=config.provenance,
                frozen_at=config.start,
                cutoff=config.deadline,
                max_snapshots=config.max_observations,
                samples=[],
                candidate_hash=artifact(dict(strategy=VERSION, verdict="REJECT_FOR_PROMOTION")),
                dataset_hash=artifact(config.model_dump(mode="json")),
                criteria_hash=artifact("simulation engineering only; no economic acceptance"),
                feature_hash=artifact("completed B01 bars available by receipt cutoff"),
                lessons_hash=artifact("no promoted lessons"),
                news_interpretation_hash=artifact("scripted news admission; not qualified news"),
                arms=[
                    dict(
                        name=name,
                        ledger=name,
                        safety_hash=shared,
                        policy_hash=artifact("B01 without AI/news")
                        if name == "NO_AI"
                        else ai_policy,
                        model_hash=None if name == "NO_AI" else model,
                        prompt_hash=None if name == "NO_AI" else prompt,
                        news_content=name == "AI_NEWS",
                    )
                    for name in ARM_NAMES
                ],
            ),
            artifacts=artifacts,
        )
    )


class Engine:
    def __init__(self, config):
        self.config, self.clock = config, FakeClock(config.start)
        self.bars, self.decisions, self.settled, self.seen = [], {}, set(), set()
        self.gateways = {}
        for name in ARM_NAMES:
            account = AccountIdentity(
                environment="PAPER",
                venue="SIMULATOR",
                broker="RUNNER",
                server="OFFLINE",
                login=name,
            )
            gateway = Gateway.for_replay(
                account, uuid5(config.run_id, name), self.clock, config.policy
            )
            gateway.broker = CostSimulator(gateway.store, config.policy.capital, config.costs)
            self.gateways[name] = gateway

    def close(self):
        for gateway in self.gateways.values():
            gateway.close()

    def step(self, tick, at):
        with localcontext() as context:
            context.prec = 34
            return self._step(tick, at)

    def _step(self, tick, at):
        self.clock.advance(at - self.clock.now())
        config = self.config
        if tick.market.at > at or any(b.available_at > at for b in tick.bars):
            raise ValueError("future input")
        if {q.symbol for q in tick.market.quotes} != {config.symbol}:
            raise ValueError("exact registered symbol required")
        if tick.market.instruments != (config.instrument,):
            raise ValueError("instrument specifications changed")
        self.bars.extend(tick.bars)
        if len(self.bars) > 20000:
            raise ValueError("bar capacity exhausted")
        visible(self.bars, config.symbol, at)  # Revision conflicts also fail on HOLD paths.
        source_market, source_news = tick.market, tick.news
        if tick.source_record:
            if tick.source_record.provenance != config.provenance:
                raise ValueError("source provenance differs from registration")
            source_market, source_news = project(tick.source_record, at)
        market = priced(source_market, config.costs, at)
        snapshot = tick.model_dump_json()
        sha = hashlib.sha256(snapshot.encode()).hexdigest()
        receipts = [
            (
                "OBSERVE",
                dict(snapshot_hash=sha, snapshot_at=tick.market.at.isoformat(), content=snapshot),
            )
        ]
        offsets = {name: len(g.store.journal) for name, g in self.gateways.items()}
        for gateway in self.gateways.values():
            gateway.reconcile(market)
        # Outcomes can only arise from an earlier committed input/decision group.
        for key, previous in self.decisions.items():
            if key in self.settled or previous["at"] >= at:
                continue
            gateway = self.gateways[previous["arm"]]
            entry_id = previous["entry"]
            gross = cost = Decimal(0)
            if entry_id:
                entry = gateway.entry(entry_id)
                if entry.state not in TERMINAL:
                    continue
                position = next(
                    (p for p in gateway.broker.book.positions if p.entry_id == entry_id), None
                )
                if position and position.volume:
                    continue
                if position:
                    fees = sum(
                        (
                            d.commission
                            for d in gateway.broker.book.deals
                            if d.position_id == position.position_id
                        ),
                        Decimal(0),
                    )
                    exit_ids = {
                        str(d.deal_id)
                        for d in gateway.broker.book.deals
                        if d.position_id == position.position_id and d.action == "CLOSE"
                    }
                    funding = sum(
                        (
                            Decimal(f["charge"])
                            for f in gateway.broker.financing
                            if f["deal_id"] in exit_ids
                        ),
                        Decimal(0),
                    )
                    cost = fees + funding
                    gross = position.realized + cost
            receipts.append(
                (
                    "OUTCOME",
                    dict(
                        snapshot_hash=previous["snapshot"],
                        arm=previous["arm"],
                        decision_id=str(key),
                        outcome_at=at.isoformat(),
                        gross_pnl=str(gross),
                        cost=str(cost),
                        evidence="SIMULATOR fills include spread/slippage; fees/funding explicit",
                    ),
                )
            )
            self.settled.add(key)

        candidates = {}
        for name, gateway in self.gateways.items():
            candidate = evaluate(
                self.bars,
                config.symbol,
                at,
                history_complete=config.history_complete,
                position_open=any(p.volume for p in gateway.broker.book.positions),
            )
            candidates[name] = candidate
            decision_id = uuid5(tick.event_id, name)
            signal = (name, candidate.get("signal_bar_close"))
            allowed = candidate["action"] == "CANDIDATE"
            reason = candidate.get("reason", "CANDIDATE_SELECTED")
            if allowed and market.quote_for(config.symbol).at <= datetime.fromisoformat(
                candidate["signal_available_at"]
            ):
                allowed, reason = False, "WAIT_FOR_POST_SIGNAL_QUOTE"
            if allowed and (
                signal in self.seen or len(gateway.book.entries) >= config.max_entries_per_arm
            ):
                allowed, reason = False, "SIGNAL_CONSUMED_OR_ENTRY_CAP"
            selector_input = dict(candidate=candidate)
            if name != "NO_AI":
                if name == "AI_NEWS":
                    selector_input["news"] = source_news
                if tick.selector_result != "SELECT":
                    allowed, reason = False, "SCRIPTED_" + tick.selector_result
                if name == "AI_NEWS" and source_news != "NEUTRAL":
                    allowed, reason = False, "NEWS_UNAVAILABLE_OR_ADVERSE"
            choice = Selection(
                action="SELECT" if allowed else "HOLD",
                candidate_id=decision_id if allowed else None,
                exit_option="TIME_EXIT" if allowed else None,
                reason="CANDIDATE_SELECTED" if allowed else "INSUFFICIENT_EVIDENCE",
            )
            detail = canonical(
                dict(
                    selection=choice.model_dump(mode="json"),
                    reason=reason,
                    selector_input=selector_input,
                    selector="NO_AI" if name == "NO_AI" else config.selector,
                )
            )
            receipts.append(
                (
                    "DECIDE",
                    dict(
                        snapshot_hash=sha,
                        snapshot_at=tick.market.at.isoformat(),
                        arm=name,
                        decision_id=str(decision_id),
                        decision_at=at.isoformat(),
                        latency_ms=0,
                        missed_entry=not allowed and candidate["action"] == "CANDIDATE",
                        decision_hash=hashlib.sha256(detail.encode()).hexdigest(),
                        decision_content=detail,
                    ),
                )
            )
            self.decisions[decision_id] = dict(arm=name, snapshot=sha, at=at, entry=None)
            candidates[name] = (candidate, allowed, decision_id, signal)
        # All three decisions are constructed before any local simulator submission.
        for name, (candidate, allowed, decision_id, signal) in candidates.items():
            if not allowed:
                continue
            gateway = self.gateways[name]
            expires = min(
                datetime.fromisoformat(candidate["expires_at"]), at + timedelta(seconds=2)
            )
            decision = Decision(
                account=gateway.account,
                action="ENTER",
                candidate_id=VERSION,
                symbol=config.symbol,
                side=candidate["side"],
                expires_at=expires,
                rationale="Frozen research signal; scripted simulation selector",
            )
            gateway.store.append_batch(
                (
                    Record(
                        record_id=decision_id,
                        account=gateway.account,
                        recorded_at=at,
                        correlation_id=config.run_id,
                        provenance="OFFLINE_SIMULATION",
                        versions=Versions(strategy=VERSION, policy=config.policy.version),
                        body=DecisionAttempt(
                            result="VALID",
                            action="ENTER",
                            cutoff=at,
                            input_snapshot=sha,
                            candidates=(VERSION,),
                            response=decision.model_dump_json(),
                            decision=decision,
                            reason="Research simulation only",
                            trace=ModelTrace(request_id=uuid5(decision_id, "trace")),
                        ),
                    ),
                )
            )
            price = (
                market.quote_for(config.symbol).ask
                if candidate["side"] == "BUY"
                else market.quote_for(config.symbol).bid
            )
            sign = 1 if candidate["side"] == "BUY" else -1
            distance = Decimal(candidate["stop_distance"])
            entry_id = uuid5(decision_id, "entry")
            intent = EntryIntent(
                intent_id=entry_id,
                account=gateway.account,
                decision_id=decision_id,
                strategy=VERSION,
                policy_version=config.policy.version,
                symbol=config.symbol,
                side=candidate["side"],
                stop=price - sign * distance,
                target=price + sign * distance * 2,
                benchmark=candidate["signal_price"],
                expires_at=expires,
                exit_at=candidate["time_exit_at"],
            )
            gateway.broker.next_fault = tick.fault
            entry = gateway.submit(intent, market)
            if entry.state in {"REJECTED", "CANCELLED"}:
                for kind, payload in receipts:
                    if kind == "DECIDE" and payload["decision_id"] == str(decision_id):
                        payload["missed_entry"] = True
            self.seen.add(signal)
            self.decisions[decision_id]["entry"] = entry_id
        return dict(
            receipts=[dict(kind=k, payload=v) for k, v in receipts],
            arms={
                name: dict(
                    journal=g.store.journal[offsets[name] :],
                    state=g.book.state,
                    input_health_reason=health_reason(market, at, config.policy),
                    entries=len(g.book.entries),
                    open_positions=sum(bool(p.volume) for p in g.broker.book.positions),
                    closed_positions=sum(not p.volume for p in g.broker.book.positions),
                    balance=str(g.broker.book.balance),
                )
                for name, g in self.gateways.items()
            },
        )


class Runner:
    def __init__(self, path, clock=None):
        self.path, self.clock = Path(path), clock or SystemClock()

    @classmethod
    def create(cls, path, config, clock=None):
        config = Config.model_validate(
            config.model_dump() if isinstance(config, Config) else config
        )
        runner = cls(path, clock)
        at = runner.clock.now()
        if not config.start <= at < config.deadline:
            raise ValueError("registration outside window")
        # Receipt time, not an earlier claimed start, is the actual admission floor.
        body = dict(
            config=config.model_dump(mode="json"),
            registered_at=at.isoformat(),
            engine_hash=engine_hash(),
        )
        with runner.path.open("xb"):
            pass
        with closing(sqlite3.connect(runner.path)) as conn, conn:
            conn.executescript("""
                CREATE TABLE header(payload TEXT NOT NULL,sha TEXT NOT NULL);
                CREATE TABLE ticks(seq INTEGER PRIMARY KEY,id TEXT UNIQUE NOT NULL,
                    payload TEXT NOT NULL,at TEXT NOT NULL,result TEXT NOT NULL,
                    previous TEXT NOT NULL,sha TEXT NOT NULL);
                CREATE TABLE stopped(at TEXT NOT NULL,reason TEXT NOT NULL,sha TEXT NOT NULL);
                CREATE TRIGGER immutable_tick BEFORE UPDATE ON ticks
                    BEGIN SELECT RAISE(ABORT,'immutable'); END;
                CREATE TRIGGER no_delete_tick BEFORE DELETE ON ticks
                    BEGIN SELECT RAISE(ABORT,'immutable'); END;
                CREATE TRIGGER immutable_header BEFORE UPDATE ON header
                    BEGIN SELECT RAISE(ABORT,'immutable'); END;
                CREATE TRIGGER no_delete_header BEFORE DELETE ON header
                    BEGIN SELECT RAISE(ABORT,'immutable'); END;
                CREATE TRIGGER immutable_stop BEFORE UPDATE ON stopped
                    BEGIN SELECT RAISE(ABORT,'immutable'); END;
                CREATE TRIGGER no_delete_stop BEFORE DELETE ON stopped
                    BEGIN SELECT RAISE(ABORT,'immutable'); END;
            """)
            conn.execute("INSERT INTO header VALUES (?,?)", (canonical(body), digest(body)))
        return runner

    def _load(self, conn, expected_hash):
        headers = conn.execute("SELECT payload,sha FROM header").fetchall()
        if len(headers) != 1:
            raise ValueError("invalid registration")
        raw, sha = headers[0]
        body = json.loads(raw)
        if sha != expected_hash or digest(body) != sha or body["engine_hash"] != engine_hash():
            raise ValueError("registration or engine mismatch")
        config = Config.model_validate(body["config"])
        rows = conn.execute("SELECT * FROM ticks ORDER BY seq LIMIT 251").fetchall()
        if len(rows) > config.max_observations or sum(len(r[2]) + len(r[4]) for r in rows) > LIMIT:
            raise ValueError("runner capacity exceeded")
        engine = Engine(config)
        previous, at = sha, datetime.fromisoformat(body["registered_at"])
        market_at = at
        try:
            for expected_sequence, (
                seq,
                event_id,
                payload,
                received,
                result,
                prev,
                row_hash,
            ) in enumerate(rows, 1):
                tick = Tick.model_validate_json(payload)
                received = datetime.fromisoformat(received)
                if (
                    tick.sequence != seq
                    or seq != expected_sequence
                    or str(tick.event_id) != event_id
                    or prev != previous
                    or received < at
                    or (seq > 1 and tick.market.at == market_at)
                    or not market_at <= tick.market.at <= received <= config.deadline
                ):
                    raise ValueError("invalid input order")
                if digest([seq, event_id, payload, received.isoformat(), result, prev]) != row_hash:
                    raise ValueError("receipt hash mismatch")
                computed = engine.step(tick, received)
                if canonical(computed) != result:
                    raise ValueError("transition differs from deterministic reconstruction")
                previous, at, market_at = row_hash, received, tick.market.at
            stops = conn.execute("SELECT at,reason,sha FROM stopped").fetchall()
            if len(stops) > 1 or (
                stops
                and (
                    datetime.fromisoformat(stops[0][0]) < at
                    or digest([previous, stops[0][0], stops[0][1]]) != stops[0][2]
                )
            ):
                raise ValueError("invalid stop")
            return body, config, rows, engine, previous, at, market_at, stops
        except BaseException:
            engine.close()
            raise

    def admit(self, tick, expected_hash):
        tick = Tick.model_validate(tick.model_dump() if isinstance(tick, Tick) else tick)
        with closing(
            sqlite3.connect(self.path.resolve().as_uri() + "?mode=rw", uri=True, timeout=3)
        ) as conn:
            conn.execute("BEGIN IMMEDIATE")
            engine = None
            try:
                body, config, rows, engine, previous, at, market_at, stops = self._load(
                    conn, expected_hash
                )
                payload = tick.model_dump_json()
                if len(payload.encode()) > 65536:
                    raise ValueError("observation exceeds receipt content limit")
                old = next((r for r in rows if r[1] == str(tick.event_id)), None)
                if old:
                    if old[2] != payload:
                        raise ValueError("conflicting event identity")
                    return dict(sequence=old[0], sha=old[6], replayed=True)
                now = self.clock.now()
                if stops or len(rows) >= config.max_observations:
                    raise ValueError("closed or capacity exhausted")
                if tick.sequence != len(rows) + 1 or not at <= now <= config.deadline:
                    raise ValueError("sequence, clock or deadline invalid")
                if not market_at <= tick.market.at <= now or (rows and tick.market.at == market_at):
                    raise ValueError("market timestamp must advance without future data")
                with localcontext() as context:
                    context.prec = 34
                    result = canonical(engine.step(tick, now))
                finished = self.clock.now()
                if not now <= finished <= config.deadline:
                    raise ValueError("clock or deadline changed during transition")
                # No external side effects: abort if processing outlives entry freshness.
                has_new_submission = any(
                    item["payload"]["event"] == "SUBMITTING"
                    for arm in json.loads(result)["arms"].values()
                    for item in arm["journal"]
                )
                if has_new_submission and any(
                    (finished - q.at).total_seconds() > config.policy.quote_age_seconds
                    for q in tick.market.quotes
                ):
                    raise ValueError("quote expired during simulation transition")
                row = [
                    tick.sequence,
                    str(tick.event_id),
                    payload,
                    now.isoformat(),
                    result,
                    previous,
                ]
                sha = digest(row)
                if sum(len(r[2]) + len(r[4]) for r in rows) + len(payload) + len(result) > LIMIT:
                    raise ValueError("runner byte capacity exceeded")
                conn.execute("INSERT INTO ticks VALUES (?,?,?,?,?,?,?)", (*row, sha))
                conn.commit()
                return dict(sequence=tick.sequence, sha=sha, replayed=False)
            finally:
                conn.rollback()
                if engine:
                    engine.close()

    def stop(self, expected_hash, reason):
        if not isinstance(reason, str) or not 1 <= len(reason) <= 256:
            raise ValueError("bounded stop reason required")
        with (
            closing(sqlite3.connect(self.path.resolve().as_uri() + "?mode=rw", uri=True)) as conn,
            conn,
        ):
            conn.execute("BEGIN IMMEDIATE")
            _, _, _, engine, head, at, _, stops = self._load(conn, expected_hash)
            engine.close()
            if stops:
                if stops[0][1] != reason:
                    raise ValueError("stop reason already fixed")
                return
            if self.clock.now() < at:
                raise ValueError("clock rollback")
            stopped_at = self.clock.now().isoformat()
            conn.execute(
                "INSERT INTO stopped VALUES (?,?,?)",
                (stopped_at, reason, digest([head, stopped_at, reason])),
            )

    def report(self, expected_hash, checkpoint=None):
        with closing(sqlite3.connect(self.path.resolve().as_uri() + "?mode=ro", uri=True)) as conn:
            conn.execute("BEGIN")
            body, config, rows, engine, head, at, _, stops = self._load(conn, expected_hash)
        try:
            if self.clock.now() < at or (
                stops and self.clock.now() < datetime.fromisoformat(stops[0][0])
            ):
                raise ValueError("clock rollback")
            heads = {0: expected_hash, **{r[0]: r[6] for r in rows}}
            if stops:
                heads[len(rows) + 1] = stops[0][2]
            if checkpoint and (
                type(checkpoint[0]) is not int or heads.get(checkpoint[0]) != checkpoint[1]
            ):
                raise ValueError("runner prefix rollback")
            return dict(
                version="paper-simulation-report/1",
                run_id=str(config.run_id),
                status="STOPPED"
                if stops
                else "WINDOW_EXPIRED"
                if self.clock.now() > config.deadline
                else "CAPACITY_REACHED"
                if len(rows) >= config.max_observations
                else "AWAITING_INPUT",
                provenance=config.provenance,
                registered_at=body["registered_at"],
                deadline=config.deadline.isoformat(),
                observations=len(rows),
                normalized_inputs=sum(
                    Tick.model_validate_json(r[2]).source_record is not None for r in rows
                ),
                input_channels=sorted(
                    {
                        Tick.model_validate_json(r[2]).source_record.channel
                        for r in rows
                        if Tick.model_validate_json(r[2]).source_record
                    }
                ),
                max_observations=config.max_observations,
                decisions=len(engine.decisions),
                outcomes=len(engine.settled),
                revisions=0,
                missing_decisions=0,
                last_input_at=at.isoformat(),
                input_age_seconds=(self.clock.now() - at).total_seconds(),
                receipt_sequence=len(rows) + bool(stops),
                receipt_hash=stops[0][2] if stops else head,
                registration_hash=expected_hash,
                arms={
                    n: dict(
                        state=g.book.state,
                        entries=len(g.book.entries),
                        closed_simulated_positions=sum(
                            not p.volume for p in g.broker.book.positions
                        ),
                        open_positions=sum(bool(p.volume) for p in g.broker.book.positions),
                        balance=str(g.broker.book.balance),
                    )
                    for n, g in engine.gateways.items()
                },
                pending_outcomes=len(engine.decisions) - len(engine.settled),
                execution_enabled=False,
                broker_calls=0,
                external_model_calls=0,
                selector=config.selector,
                qualified_for_unattended_paper=False,
                prospective_evidence_verified=False,
                full_M5_complete=False,
                B01="REJECT_FOR_PROMOTION",
            )
        finally:
            engine.close()

    def export(self, expected_hash, destination):
        with closing(sqlite3.connect(self.path.resolve().as_uri() + "?mode=ro", uri=True)) as conn:
            conn.execute("BEGIN")
            body, config, rows, engine, _, _, _, stops = self._load(conn, expected_hash)
        engine.close()
        reg = registration(config)
        clock = FakeClock(datetime.fromisoformat(body["registered_at"]))
        ledger = Ledger.create(destination, reg, uuid5(config.run_id, "register"), clock)
        plan_hash = digest(reg.plan.model_dump(mode="json"))
        for row in rows:
            clock.advance(datetime.fromisoformat(row[3]) - clock.now())
            for index, item in enumerate(json.loads(row[4])["receipts"]):
                ledger.append(
                    item["kind"],
                    item["payload"],
                    uuid5(UUID(row[1]), f"receipt/{index}"),
                    expected_plan_hash=plan_hash,
                )
        if stops:
            clock.advance(datetime.fromisoformat(stops[0][0]) - clock.now())
            ledger.append(
                "CLOSE",
                dict(reason=stops[0][1]),
                uuid5(config.run_id, "stop"),
                expected_plan_hash=plan_hash,
            )
        return dict(
            plan_hash=plan_hash,
            source_registration=expected_hash,
            source_receipt_hash=stops[0][2] if stops else rows[-1][6] if rows else expected_hash,
            derived_export=True,
            execution_enabled=False,
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["register", "admit", "report", "stop", "export"])
    parser.add_argument("--journal", type=Path, required=True)
    parser.add_argument("--input", type=Path)
    parser.add_argument("--registration-hash")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--reason")
    args = parser.parse_args()
    runner = Runner(args.journal)
    if args.action in {"register", "admit"}:
        if not args.input:
            parser.error("input required")
        with args.input.open("rb") as stream:
            raw = stream.read(2 * 1024 * 1024 + 1)
        if len(raw) > 2 * 1024 * 1024:
            parser.error("input exceeds limit")
    if args.action == "register":
        Runner.create(args.journal, Config.model_validate_json(raw))
        with closing(sqlite3.connect(args.journal)) as conn:
            result = dict(registration_hash=conn.execute("SELECT sha FROM header").fetchone()[0])
    else:
        if not args.registration_hash:
            parser.error("exact registration hash required")
        if args.action == "admit":
            result = runner.admit(Tick.model_validate_json(raw), args.registration_hash)
        elif args.action == "stop":
            runner.stop(args.registration_hash, args.reason)
            result = runner.report(args.registration_hash)
        elif args.action == "export":
            if not args.output:
                parser.error("new receipt journal destination required")
            result = runner.export(args.registration_hash, args.output)
        else:
            result = runner.report(args.registration_hash)
    print(canonical(result))


if __name__ == "__main__":
    main()
