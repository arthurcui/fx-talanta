"""Append-only matched-study receipts, offline only; no strategy or broker runner."""

import argparse
import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, TypeAdapter, model_validator

from fx_talanta.clock import SystemClock
from fx_talanta.domain.models import Amount, FrozenModel, Hash, NonNegative, Timestamp
from fx_talanta.evaluation.matched import ARM_NAMES, Sample, Study, evaluate

MAX_EVENTS = 12000
MAX_BYTES = 32 * 1024 * 1024


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


class Plan(Study):
    schema_version: Literal["matched-receipt-plan/1"] = "matched-receipt-plan/1"
    run_id: UUID
    samples: tuple[Sample, ...] = ()
    max_snapshots: Annotated[int, Field(strict=True, ge=1, le=1000)] = 250

    @model_validator(mode="after")
    def registration_only(self):
        if self.samples or self.cutoff <= self.frozen_at:
            raise ValueError("registration must have no samples and a positive window")
        return self


class Registration(FrozenModel):
    plan: Plan
    # UTF-8 artifact bytes are supplied as strings, keyed by their SHA-256.
    artifacts: Annotated[dict[Hash, str], Field(min_length=1, max_length=32)]

    @model_validator(mode="after")
    def actual_artifacts(self):
        required = {
            getattr(self.plan, name)
            for name in (
                "candidate_hash",
                "dataset_hash",
                "criteria_hash",
                "feature_hash",
                "lessons_hash",
                "news_interpretation_hash",
            )
        }
        for arm in self.plan.arms:
            required.update(
                filter(None, (arm.policy_hash, arm.safety_hash, arm.model_hash, arm.prompt_hash))
            )
        if (
            set(self.artifacts) != required
            or sum(len(v.encode()) for v in self.artifacts.values()) > 1024 * 1024
        ):
            raise ValueError("exact bounded frozen artifacts required")
        if any(hashlib.sha256(v.encode()).hexdigest() != k for k, v in self.artifacts.items()):
            raise ValueError("frozen artifact hash mismatch")
        return self


class Observation(FrozenModel):
    snapshot_hash: Hash
    snapshot_at: Timestamp
    content: Annotated[str, Field(max_length=65536)]

    @model_validator(mode="after")
    def content_hash(self):
        if hashlib.sha256(self.content.encode()).hexdigest() != self.snapshot_hash:
            raise ValueError("snapshot hash mismatch")
        return self


class Decision(Sample):
    decision_hash: Hash
    decision_content: Annotated[str, Field(min_length=1, max_length=65536)]

    @model_validator(mode="after")
    def no_outcome(self):
        if hashlib.sha256(self.decision_content.encode()).hexdigest() != self.decision_hash:
            raise ValueError("decision content hash mismatch")
        if any(x is not None for x in (self.outcome_at, self.gross_pnl, self.cost)):
            raise ValueError("decision cannot contain outcome information")
        return self


class Outcome(FrozenModel):
    snapshot_hash: Hash
    arm: Literal["NO_AI", "AI_NO_NEWS", "AI_NEWS"]
    decision_id: UUID
    outcome_at: Timestamp
    gross_pnl: Amount | None
    cost: NonNegative | None
    evidence: Annotated[str, Field(min_length=1, max_length=65536)]
    supersedes: UUID | None = None


class Stop(FrozenModel):
    reason: Annotated[str, Field(min_length=1, max_length=256)]


MODELS = {
    "REGISTER": Registration,
    "OBSERVE": Observation,
    "DECIDE": Decision,
    "OUTCOME": Outcome,
    "CLOSE": Stop,
}


def replay(rows):
    """Revalidate every receipt, its ordering and hash chain, including on resume."""
    if not rows or len(rows) > MAX_EVENTS + 1 or sum(len(r[3]) for r in rows) > MAX_BYTES:
        raise ValueError("missing or oversized receipt journal")
    previous, last_at = "0" * 64, None
    plan = None
    observations, decisions, outcomes = {}, {}, {}
    closed, revisions = False, 0
    heads, ids = {}, set()
    for expected_seq, (seq, event_id, kind, raw, at, prev, sha) in enumerate(rows, 1):
        UUID(event_id)
        if event_id in ids:
            raise ValueError("duplicate receipt identity")
        ids.add(event_id)
        payload = json.loads(raw)
        value = MODELS[kind].model_validate(payload)
        at = TypeAdapter(Timestamp).validate_python(at)
        body = dict(
            seq=seq,
            event_id=event_id,
            kind=kind,
            payload=payload,
            received_at=at.isoformat(),
            previous=prev,
        )
        if (
            seq != expected_seq
            or prev != previous
            or digest(body) != sha
            or (last_at and at < last_at)
        ):
            raise ValueError("receipt chain or clock order invalid")
        previous, last_at = sha, at
        heads[seq] = sha
        if seq == 1:
            if kind != "REGISTER":
                raise ValueError("registration must be first")
            plan = value.plan
            registered_at = at
            if not plan.frozen_at <= at < plan.cutoff:
                raise ValueError("registration outside frozen window")
            continue
        if closed or kind == "REGISTER":
            raise ValueError("closed or already registered")
        if kind == "CLOSE":
            closed = True
            continue
        if not registered_at <= at <= plan.cutoff:
            raise ValueError("receipt outside registered window")
        if kind == "OBSERVE":
            if value.snapshot_hash in observations or len(observations) >= plan.max_snapshots:
                raise ValueError("duplicate snapshot or snapshot limit")
            if not registered_at <= value.snapshot_at <= at:
                raise ValueError("observation predates registration or is in the future")
            observations[value.snapshot_hash] = (value, at)
        elif kind == "DECIDE":
            observation = observations.get(value.snapshot_hash)
            key = (value.snapshot_hash, value.arm)
            if (
                not observation
                or key in decisions
                or any(value.decision_id == d[0].decision_id for d in decisions.values())
            ):
                raise ValueError("missing observation or duplicate decision")
            if (
                value.snapshot_at != observation[0].snapshot_at
                or not observation[1] <= value.decision_at <= at
            ):
                raise ValueError("decision before observation receipt or in future")
            if any(k[0] == value.snapshot_hash for k in outcomes):
                raise ValueError("decision after outcome receipt")
            decisions[key] = (value, at)
        else:
            key = (value.snapshot_hash, value.arm)
            group = [decisions.get((value.snapshot_hash, arm)) for arm in ARM_NAMES]
            if not all(group) or decisions[key][0].decision_id != value.decision_id:
                raise ValueError("all three decisions must be durably received first")
            if not max(d[1] for d in group) < value.outcome_at <= at:
                raise ValueError("outcome predates complete decision receipts or is future")
            old = outcomes.get(key)
            if (old is None and value.supersedes is not None) or (
                old and str(value.supersedes) != old[1]
            ):
                raise ValueError("correction must supersede current outcome")
            if old and value.outcome_at < old[0].outcome_at:
                raise ValueError("correction cannot move outcome backwards")
            revisions += bool(old)
            outcomes[key] = (value, event_id)
    return dict(
        plan=plan,
        registered_at=registered_at,
        observations=observations,
        decisions=decisions,
        outcomes=outcomes,
        closed=closed,
        revisions=revisions,
        heads=heads,
        last_at=last_at,
    )


def load(conn):
    if not conn.in_transaction:
        conn.execute("BEGIN")
    count, size = conn.execute(
        "SELECT count(*), coalesce(sum(length(CAST(payload AS BLOB))),0) FROM "
        "(SELECT payload FROM events LIMIT ?)",
        (MAX_EVENTS + 2,),
    ).fetchone()
    if count > MAX_EVENTS + 1 or size > MAX_BYTES:
        raise ValueError("receipt journal exceeds bounds")
    rows = conn.execute(
        "SELECT seq,id,kind,payload,at,previous,sha FROM events ORDER BY seq LIMIT ?",
        (MAX_EVENTS + 2,),
    ).fetchall()
    return rows, replay(rows)


class Ledger:
    def __init__(self, path, clock=None):
        self.path, self.clock = Path(path), clock or SystemClock()

    @classmethod
    def create(cls, path, registration, event_id, clock=None):
        ledger = cls(path, clock)
        value = Registration.model_validate(registration)
        value = value.model_dump(mode="json")
        with ledger.path.open("xb"):
            pass
        with closing(sqlite3.connect(ledger.path)) as conn, conn:
            conn.executescript("""
                CREATE TABLE events(seq INTEGER PRIMARY KEY,id TEXT UNIQUE NOT NULL,
                    kind TEXT NOT NULL,
                    payload TEXT NOT NULL,at TEXT NOT NULL,
                    previous TEXT NOT NULL,sha TEXT NOT NULL);
                CREATE TRIGGER no_change BEFORE UPDATE ON events
                    BEGIN SELECT RAISE(ABORT,'immutable receipts'); END;
                CREATE TRIGGER no_delete BEFORE DELETE ON events
                    BEGIN SELECT RAISE(ABORT,'immutable receipts'); END;
            """)
            row = ledger.row([], "REGISTER", value, event_id)
            replay([row])
            conn.execute("INSERT INTO events VALUES (?,?,?,?,?,?,?)", row)
        return ledger

    def row(self, rows, kind, payload, event_id):
        at = self.clock.now().isoformat()
        seq, previous = len(rows) + 1, rows[-1][6] if rows else "0" * 64
        event_id = str(UUID(str(event_id)))
        sha = digest(
            dict(
                seq=seq,
                event_id=event_id,
                kind=kind,
                payload=payload,
                received_at=at,
                previous=previous,
            )
        )
        return (seq, event_id, kind, canonical(payload), at, previous, sha)

    def append(self, kind, payload, event_id, *, expected_plan_hash):
        if kind not in MODELS or kind == "REGISTER":
            raise ValueError("invalid receipt kind")
        event_id = str(UUID(str(event_id)))
        data = MODELS[kind].model_validate(payload).model_dump(mode="json")
        with closing(
            sqlite3.connect(self.path.resolve().as_uri() + "?mode=rw", uri=True, timeout=3)
        ) as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                rows, state = load(conn)
                if digest(state["plan"].model_dump(mode="json")) != expected_plan_hash:
                    raise ValueError("plan binding mismatch")
                old = next((r for r in rows if r[1] == str(event_id)), None)
                if old:
                    if old[2] != kind or old[3] != canonical(data):
                        raise ValueError("conflicting event id")
                    conn.rollback()
                    return dict(sequence=old[0], receipt_hash=old[6], replayed=True)
                if len(rows) >= MAX_EVENTS and kind != "CLOSE":
                    raise ValueError("receipt capacity reached")
                row = self.row(rows, kind, data, event_id)
                replay([*rows, row])
                conn.execute("INSERT INTO events VALUES (?,?,?,?,?,?,?)", row)
                conn.commit()
                return dict(sequence=row[0], receipt_hash=row[6], replayed=False)
            except BaseException:
                conn.rollback()
                raise

    def report(self, expected_plan_hash, checkpoint=None):
        with closing(
            sqlite3.connect(self.path.resolve().as_uri() + "?mode=ro", uri=True, timeout=3)
        ) as conn:
            rows, state = load(conn)
        plan = state["plan"]
        if digest(plan.model_dump(mode="json")) != expected_plan_hash:
            raise ValueError("plan binding mismatch")
        if checkpoint and state["heads"].get(checkpoint[0]) != checkpoint[1]:
            raise ValueError("journal rollback or changed receipt prefix")
        now = self.clock.now()
        if now < state["last_at"]:
            raise ValueError("clock before latest receipt")
        samples = []
        for key, (decision, _) in state["decisions"].items():
            sample = decision.model_dump(mode="json", exclude={"decision_hash", "decision_content"})
            if key in state["outcomes"]:
                outcome = state["outcomes"][key][0]
                sample.update(
                    outcome.model_dump(mode="json", include={"outcome_at", "gross_pnl", "cost"})
                )
            samples.append(sample)
        study = None
        comparison = None
        if samples:
            data = plan.model_dump(mode="json", exclude={"run_id", "max_snapshots"})
            data.update(
                schema_version="matched-offline-study/1",
                samples=samples,
                cutoff=min(now, plan.cutoff),
            )
            study = Study.model_validate(data)
            comparison = evaluate(study)
        return dict(
            schema_version="matched-receipt-report/1",
            status="CLOSED"
            if state["closed"]
            else "WINDOW_EXPIRED"
            if now > plan.cutoff
            else "REGISTERED"
            if len(rows) == 1
            else "COLLECTING_RECEIPTS",
            run_id=str(plan.run_id),
            plan_hash=expected_plan_hash,
            provenance=plan.provenance,
            receipt_sequence=rows[-1][0],
            receipt_hash=rows[-1][6],
            registered_at=state["registered_at"].isoformat(),
            deadline=plan.cutoff.isoformat(),
            observations=len(state["observations"]),
            decisions=len(samples),
            outcomes=len(state["outcomes"]),
            revisions=state["revisions"],
            observations_without_decisions=len(state["observations"])
            - len({key[0] for key in state["decisions"]}),
            missing_decisions=3 * len(state["observations"]) - len(samples),
            pending_outcomes=len(samples) - len(state["outcomes"]),
            comparison=comparison,
            study=study.model_dump(mode="json") if study else None,
            result="OFFLINE_RECEIPT_WORKFLOW_ONLY",
            execution_enabled=False,
            prospective_evidence_verified=False,
            qualified_for_unattended_paper=False,
            limitations=[
                "Local receipt order is not trusted external publication or broker evidence",
                "Artifact hashes verify bytes, not strategy quality or input provenance",
                "No strategy/model/broker runner or campaign started",
                "M1-M3 gaps and B01 rejection preserved",
            ],
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action", choices=["register", "observe", "decide", "outcome", "close", "report", "export"]
    )
    parser.add_argument("--journal", type=Path, required=True)
    parser.add_argument("--input", type=Path)
    parser.add_argument("--event-id", type=UUID)
    parser.add_argument("--plan-hash")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.action in ("report", "export"):
        if not args.output or not args.plan_hash:
            parser.error("report/export requires output and exact plan hash")
        result = Ledger(args.journal).report(args.plan_hash)
        value = result if args.action == "report" else result["study"]
        if value is None:
            raise ValueError("no decisions to export")
        with args.output.open("x", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2)
    else:
        if not args.input or not args.event_id:
            parser.error("receipt requires input and stable event id")
        with args.input.open("rb") as stream:
            raw = stream.read(2 * 1024 * 1024 + 1)
        if len(raw) > 2 * 1024 * 1024:
            raise ValueError("input exceeds 2 MiB")
        if args.action == "register":
            value = Registration.model_validate_json(raw)
            Ledger.create(args.journal, value, args.event_id)
            print("Plan SHA-256: " + digest(value.plan.model_dump(mode="json")))
        else:
            if not args.plan_hash:
                parser.error("exact plan hash required")
            Ledger(args.journal).append(
                args.action.upper(),
                json.loads(raw),
                args.event_id,
                expected_plan_hash=args.plan_hash,
            )
    print("Offline receipts only; trading disabled; no campaign or qualification")


if __name__ == "__main__":
    main()
