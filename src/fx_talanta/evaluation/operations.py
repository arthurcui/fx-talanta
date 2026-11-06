"""Bound local input queue to the simulation runner; no collector or network transport."""

import argparse
import json
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field

from fx_talanta.clock import SystemClock
from fx_talanta.domain.models import FrozenModel, Hash
from fx_talanta.evaluation.ledger import canonical, digest
from fx_talanta.evaluation.runner import Runner, Tick
from fx_talanta.provider_pipeline import status_lock


class Binding(FrozenModel):
    version: Literal["simulation-source-binding/1"] = "simulation-source-binding/1"
    source_id: UUID
    runner: str
    registration_hash: Hash
    capacity: Annotated[int, Field(strict=True, ge=1, le=250)] = 100
    execution_enabled: Literal[False] = False


class Operations:
    def __init__(self, path, clock=None):
        self.path, self.clock = Path(path), clock or SystemClock()

    def connect(self, mode="ro"):
        return sqlite3.connect(self.path.resolve().as_uri() + f"?mode={mode}", uri=True, timeout=3)

    @classmethod
    def create(cls, path, binding, clock=None):
        binding = Binding.model_validate(
            binding.model_dump() if isinstance(binding, Binding) else binding
        )
        target = Path(binding.runner)
        if not target.is_absolute() or target.resolve() == Path(path).resolve():
            raise ValueError("separate absolute runner path required")
        obj = cls(path, clock)
        report = Runner(target, obj.clock).report(binding.registration_hash)
        if report["observations"] or report["status"] != "AWAITING_INPUT":
            raise ValueError("source may bind only an empty current runner")
        if binding.capacity > report["max_observations"]:
            raise ValueError("source capacity exceeds runner mandate")
        raw = canonical(binding.model_dump(mode="json"))
        sha = digest(json.loads(raw))
        with obj.path.open("xb"):
            pass
        with closing(sqlite3.connect(obj.path)) as conn, conn:
            conn.executescript("""
                CREATE TABLE binding(payload TEXT NOT NULL,sha TEXT NOT NULL);
                CREATE TABLE inputs(seq INTEGER PRIMARY KEY,id TEXT UNIQUE NOT NULL,
                    payload TEXT NOT NULL,at TEXT NOT NULL,
                    previous TEXT NOT NULL,sha TEXT NOT NULL);
                CREATE TABLE acknowledgements(seq INTEGER PRIMARY KEY,source_sha TEXT NOT NULL,
                    runner_sha TEXT NOT NULL,at TEXT NOT NULL);
                CREATE TABLE sealed(reason TEXT NOT NULL,source_sha TEXT NOT NULL);
            """)
            for table in ("binding", "inputs", "acknowledgements", "sealed"):
                for action in ("UPDATE", "DELETE"):
                    conn.execute(
                        f"CREATE TRIGGER forbid_{table}_{action} BEFORE {action} ON {table} "
                        "BEGIN SELECT RAISE(ABORT,'immutable source evidence'); END"
                    )
            conn.execute("INSERT INTO binding VALUES (?,?)", (raw, sha))
        return obj, sha

    def load(self, conn, expected):
        headers = conn.execute("SELECT payload,sha FROM binding").fetchall()
        if (
            len(headers) != 1
            or headers[0][1] != expected
            or digest(json.loads(headers[0][0])) != expected
        ):
            raise ValueError("source binding mismatch")
        binding = Binding.model_validate_json(headers[0][0])
        rows = conn.execute("SELECT * FROM inputs ORDER BY seq LIMIT 251").fetchall()
        if len(rows) > binding.capacity or sum(len(r[2]) for r in rows) > 16 * 1024 * 1024:
            raise ValueError("source capacity violated")
        previous, at = expected, None
        for number, row in enumerate(rows, 1):
            seq, event_id, payload, received, prev, sha = row
            tick = Tick.model_validate_json(payload)
            received = datetime.fromisoformat(received)
            if (
                seq != number
                or tick.sequence != seq
                or str(tick.event_id) != event_id
                or prev != previous
                or digest(list(row[:-1])) != sha
                or (at and received < at)
                or tick.market.at > received
            ):
                raise ValueError("source sequence, clock or hash invalid")
            previous, at = sha, received
        if at and self.clock.now() < at:
            raise ValueError("source clock rollback")
        acknowledgements = conn.execute("SELECT * FROM acknowledgements ORDER BY seq").fetchall()
        if len(acknowledgements) > len(rows):
            raise ValueError("acknowledgement without input")
        previous_ack = None
        for number, (seq, source_sha, _, ack_at) in enumerate(acknowledgements, 1):
            if (
                seq != number
                or source_sha != rows[seq - 1][5]
                or datetime.fromisoformat(ack_at) < datetime.fromisoformat(rows[seq - 1][3])
            ):
                raise ValueError("invalid acknowledgement")
            if self.clock.now() < datetime.fromisoformat(ack_at):
                raise ValueError("acknowledgement clock rollback")
            if previous_ack and datetime.fromisoformat(ack_at) < previous_ack:
                raise ValueError("acknowledgement time order invalid")
            previous_ack = datetime.fromisoformat(ack_at)
        sealed = conn.execute("SELECT reason,source_sha FROM sealed").fetchall()
        if len(sealed) > 1 or (sealed and sealed[0][1] != previous):
            raise ValueError("invalid sealed source")
        return binding, rows, acknowledgements, sealed

    def enqueue(self, tick, expected):
        tick = Tick.model_validate(tick.model_dump() if isinstance(tick, Tick) else tick)
        payload = tick.model_dump_json()
        if len(payload.encode()) > 65536:
            raise ValueError("source item exceeds 64 KiB")
        with closing(self.connect("rw")) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            binding, rows, _, sealed = self.load(conn, expected)
            old = next((r for r in rows if r[1] == str(tick.event_id)), None)
            if old:
                if old[2] != payload:
                    raise ValueError("conflicting source identity")
                return dict(sequence=old[0], source_sha=old[5], replayed=True)
            if sealed or len(rows) >= binding.capacity or tick.sequence != len(rows) + 1:
                raise ValueError("source sealed, full or out of order")
            now = self.clock.now()
            if tick.market.at > now or any(b.available_at > now for b in tick.bars):
                raise ValueError("future source data")
            row = [
                tick.sequence,
                str(tick.event_id),
                payload,
                now.isoformat(),
                rows[-1][5] if rows else expected,
            ]
            sha = digest(row)
            conn.execute("INSERT INTO inputs VALUES (?,?,?,?,?,?)", (*row, sha))
            return dict(sequence=tick.sequence, source_sha=sha, replayed=False)

    def target(self, binding, rows, acks):
        runner = Runner(binding.runner, self.clock)
        checkpoint = (acks[-1][0], acks[-1][2]) if acks else (0, binding.registration_hash)
        report = runner.report(binding.registration_hash, checkpoint)
        count = report["observations"]
        if not len(acks) <= count <= min(len(rows), len(acks) + 1):
            raise ValueError("runner diverged from bound source")
        # An unacknowledged commit must be the exact queued input, never an adopted write.
        with closing(
            sqlite3.connect(Path(binding.runner).resolve().as_uri() + "?mode=ro", uri=True)
        ) as conn:
            for seq, event_id, payload, sha in conn.execute(
                "SELECT seq,id,payload,sha FROM ticks ORDER BY seq"
            ):
                if seq > len(rows) or (event_id, payload) != (rows[seq - 1][1], rows[seq - 1][2]):
                    raise ValueError("runner input does not match source")
                if seq <= len(acks) and sha != acks[seq - 1][2]:
                    raise ValueError("acknowledgement fingerprint mismatch")
        return runner, report

    def drain_one(self, expected):
        with status_lock(self.path.with_suffix(".consumer.lock")):
            with closing(self.connect()) as conn:
                conn.execute("BEGIN")
                binding, rows, acks, sealed = self.load(conn, expected)
            runner, report = self.target(binding, rows, acks)
            if sealed or report["status"] == "STOPPED":
                raise ValueError("source or runner stopped")
            if len(rows) == len(acks):
                return dict(status="EMPTY", execution_enabled=False)
            row = rows[len(acks)]
            result = runner.admit(Tick.model_validate_json(row[2]), binding.registration_hash)
            self._acknowledge(expected, row, result)
            return dict(
                status="ACKNOWLEDGED",
                sequence=result["sequence"],
                replayed=result["replayed"],
                execution_enabled=False,
            )

    def _acknowledge(self, expected, row, result):
        with closing(self.connect("rw")) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            _, rows, acks, sealed = self.load(conn, expected)
            if sealed or len(acks) + 1 != row[0] or rows[row[0] - 1] != row:
                raise ValueError("source changed before acknowledgement")
            conn.execute(
                "INSERT INTO acknowledgements VALUES (?,?,?,?)",
                (row[0], row[5], result["sha"], self.clock.now().isoformat()),
            )

    def report(self, expected, checkpoint=None):
        with closing(self.connect()) as conn:
            conn.execute("BEGIN")
            binding, rows, acks, sealed = self.load(conn, expected)
        _, report = self.target(binding, rows, acks)
        if checkpoint:
            seq, head, ack_count, ack_head, seal, runner_seq, runner_head = checkpoint
            heads = {0: expected, **{r[0]: r[5] for r in rows}}
            ack_heads = {0: expected, **{r[0]: r[2] for r in acks}}
            if (
                heads.get(seq) != head
                or ack_heads.get(ack_count) != ack_head
                or (seal and [list(s) for s in sealed] != seal)
            ):
                raise ValueError("source checkpoint rollback")
            Runner(binding.runner, self.clock).report(
                binding.registration_hash, (runner_seq, runner_head)
            )
        cursor = [
            len(rows),
            rows[-1][5] if rows else expected,
            len(acks),
            acks[-1][2] if acks else expected,
            [list(s) for s in sealed],
            report["receipt_sequence"],
            report["receipt_hash"],
        ]
        # JSON checkpoints normalize SQL tuples to lists.
        oldest = datetime.fromisoformat(rows[len(acks)][3]) if len(rows) > len(acks) else None
        return dict(
            version="simulation-source-report/1",
            source_id=str(binding.source_id),
            binding_hash=expected,
            queued=len(rows),
            acknowledged=len(acks),
            pending=len(rows) - len(acks),
            source_head=rows[-1][5] if rows else expected,
            status="SEALED"
            if sealed
            else "CAPACITY_REACHED"
            if len(rows) == binding.capacity
            else "OPEN",
            unacknowledged_runner_commit=report["observations"] > len(acks),
            runner=report,
            execution_enabled=False,
            source_qualified=False,
            checkpoint=cursor,
            oldest_pending_age_seconds=(self.clock.now() - oldest).total_seconds()
            if oldest
            else None,
            producer_liveness="UNVERIFIED",
        )

    def stop(self, expected, reason):
        if not isinstance(reason, str) or not 1 <= len(reason) <= 256:
            raise ValueError("bounded stop reason required")
        with status_lock(self.path.with_suffix(".consumer.lock")):
            with closing(self.connect("rw")) as conn, conn:
                conn.execute("BEGIN IMMEDIATE")
                binding, rows, acks, sealed = self.load(conn, expected)
                runner, _ = self.target(binding, rows, acks)
                if sealed and sealed[0][0] != reason:
                    raise ValueError("stop reason already fixed")
                if not sealed:
                    conn.execute(
                        "INSERT INTO sealed VALUES (?,?)",
                        (reason, rows[-1][5] if rows else expected),
                    )
            # Seal commits first; crash/retry cannot reopen admission or invent closure.
            runner.stop(binding.registration_hash, reason)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["create", "enqueue", "drain-one", "report", "stop"])
    parser.add_argument("--queue", type=Path, required=True)
    parser.add_argument("--input", type=Path)
    parser.add_argument("--binding-hash")
    parser.add_argument("--reason")
    args = parser.parse_args()
    if args.action in {"create", "enqueue"}:
        if not args.input:
            parser.error("input required")
        with args.input.open("rb") as stream:
            raw = stream.read(65537)
        if len(raw) > 65536:
            parser.error("input too large")
    obj = Operations(args.queue)
    if args.action == "create":
        _, sha = Operations.create(args.queue, Binding.model_validate_json(raw))
        result = dict(binding_hash=sha, execution_enabled=False)
    else:
        if not args.binding_hash:
            parser.error("exact binding hash required")
        if args.action == "enqueue":
            result = obj.enqueue(Tick.model_validate_json(raw), args.binding_hash)
        elif args.action == "drain-one":
            result = obj.drain_one(args.binding_hash)
        elif args.action == "stop":
            obj.stop(args.binding_hash, args.reason)
            result = obj.report(args.binding_hash)
        else:
            result = obj.report(args.binding_hash)
    print(canonical(result))


if __name__ == "__main__":
    main()
