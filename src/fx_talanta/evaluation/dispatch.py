"""Durable simulation selector dispatch; transport is injected, never configured here."""

import json
import sqlite3
from contextlib import closing
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field

from fx_talanta.clock import SystemClock
from fx_talanta.domain.models import FrozenModel, Hash, Identifier, NonNegative, Timestamp
from fx_talanta.evaluation.ledger import canonical, digest
from fx_talanta.evaluation.operations import Operations
from fx_talanta.evaluation.runner import Runner, Tick
from fx_talanta.evaluation.selectors import Batch, Reply
from fx_talanta.provider_pipeline import status_lock

ARMS = ("AI_NO_NEWS", "AI_NEWS")


class Policy(FrozenModel):
    queue: str
    source_hash: Hash
    deadline: Timestamp
    max_calls: Annotated[int, Field(strict=True, ge=2, le=500)]
    tokens_per_call: Annotated[int, Field(strict=True, ge=1, le=200000)]
    max_reserved_tokens: Annotated[int, Field(strict=True, ge=2, le=100000000)]
    execution_enabled: Literal[False] = False


class Delivery(FrozenModel):
    status: Literal["RESPONSE", "TIMEOUT", "ERROR"]
    returned_model: Identifier | None = None
    response: Annotated[str, Field(max_length=4096)] | None = None
    input_tokens: Annotated[int, Field(strict=True, ge=0, le=100000)] = 0
    output_tokens: Annotated[int, Field(strict=True, ge=0, le=100000)] = 0
    reported_cost_usd: NonNegative | None = None


class Dispatcher:
    def __init__(self, path, clock=None):
        self.path, self.clock = Path(path), clock or SystemClock()

    def connect(self, mode="ro"):
        return sqlite3.connect(self.path.resolve().as_uri() + f"?mode={mode}", uri=True, timeout=3)

    @classmethod
    def create(cls, path, policy, clock=None):
        policy = Policy.model_validate(
            policy.model_dump() if isinstance(policy, Policy) else policy
        )
        obj = cls(path, clock)
        if (
            not Path(policy.queue).is_absolute()
            or Path(policy.queue).resolve() == Path(path).resolve()
        ):
            raise ValueError("separate absolute source queue required")
        source = Operations(policy.queue, obj.clock).report(policy.source_hash)
        runner = source["runner"]
        if (
            source["queued"]
            or source["status"] != "OPEN"
            or runner["status"] != "AWAITING_INPUT"
            or runner["selector"] != "RECORDED_MODEL_RESPONSES"
            or not obj.clock.now() < policy.deadline <= datetime.fromisoformat(runner["deadline"])
            or policy.max_reserved_tokens < 2 * policy.tokens_per_call
        ):
            raise ValueError("empty current recorded runner and bounded mandate required")
        body = policy.model_dump(mode="json")
        sha = digest(body)
        if obj.path.exists():
            raise FileExistsError(obj.path)
        marker = Path(policy.queue).with_name(Path(policy.queue).name + ".dispatch-binding.json")
        with marker.open("x", encoding="utf-8") as stream:
            stream.write(canonical(dict(dispatcher=str(obj.path.resolve()), policy_hash=sha)))
        with obj.path.open("xb"):
            pass
        with closing(sqlite3.connect(obj.path)) as conn, conn:
            conn.executescript("""
                CREATE TABLE header(payload TEXT NOT NULL,sha TEXT NOT NULL);
                CREATE TABLE events(seq INTEGER PRIMARY KEY,kind TEXT NOT NULL,
                    event_id TEXT NOT NULL,at TEXT NOT NULL,payload TEXT NOT NULL,
                    previous TEXT NOT NULL,sha TEXT NOT NULL);
            """)
            for table in ("header", "events"):
                for action in ("UPDATE", "DELETE"):
                    conn.execute(
                        f"CREATE TRIGGER no_{table}_{action} BEFORE {action} ON {table} "
                        "BEGIN SELECT RAISE(ABORT,'immutable dispatch evidence'); END"
                    )
            conn.execute("INSERT INTO header VALUES (?,?)", (canonical(body), sha))
        return obj, sha

    def load(self, conn, expected):
        headers = conn.execute("SELECT payload,sha FROM header").fetchall()
        if (
            len(headers) != 1
            or headers[0][1] != expected
            or digest(json.loads(headers[0][0])) != expected
        ):
            raise ValueError("dispatch binding mismatch")
        policy = Policy.model_validate_json(headers[0][0])
        marker = Path(policy.queue).with_name(Path(policy.queue).name + ".dispatch-binding.json")
        with marker.open("rb") as stream:
            marker_bytes = stream.read(8193)
        if len(marker_bytes) > 8192 or json.loads(marker_bytes) != dict(
            dispatcher=str(self.path.resolve()), policy_hash=expected
        ):
            raise ValueError("source dispatcher binding mismatch")
        rows = conn.execute("SELECT * FROM events ORDER BY seq LIMIT 1502").fetchall()
        if len(rows) > 1501 or sum(len(r[4]) for r in rows) > 64 * 1024 * 1024:
            raise ValueError("dispatch capacity exhausted")
        groups, stopped, previous, last_at = {}, False, expected, None
        for index, row in enumerate(rows, 1):
            seq, kind, event_id, at, raw, prev, sha = row
            at = datetime.fromisoformat(at)
            if (
                seq != index
                or prev != previous
                or digest(list(row[:-1])) != sha
                or (last_at and at < last_at)
                or at > self.clock.now()
                or stopped
            ):
                raise ValueError("dispatch sequence, clock or hash invalid")
            payload = json.loads(raw)
            if kind == "RESERVE":
                if (
                    event_id in groups
                    or any("publication" not in g for g in groups.values())
                    or (len(groups) + 1) * 2 > policy.max_calls
                    or (len(groups) + 1) * 2 * policy.tokens_per_call > policy.max_reserved_tokens
                    or at > policy.deadline
                ):
                    raise ValueError("invalid dispatch reservation")
                tick = Tick.model_validate_json(payload["tick"])
                if str(tick.event_id) != event_id or tick.model_batch:
                    raise ValueError("invalid reserved tick")
                groups[event_id] = dict(reservation=payload, results={}, uncertain=False)
            elif kind == "STOP":
                stopped = True
            else:
                if event_id not in groups:
                    raise ValueError("dispatch event without reservation")
                group = groups[event_id]
                if group["uncertain"] or "publication" in group:
                    raise ValueError("terminal dispatch group")
                if kind == "RESULT":
                    arm = payload["arm"]
                    reply = Reply.model_validate(payload["reply"])
                    if (
                        arm not in ARMS
                        or arm in group["results"]
                        or reply.completed_at.isoformat() != row[3]
                    ):
                        raise ValueError("invalid dispatch result")
                    group["results"][arm] = payload["reply"]
                elif kind == "UNCERTAIN":
                    group["uncertain"] = True
                elif kind == "PUBLISHED":
                    if set(group["results"]) != set(ARMS):
                        raise ValueError("publication without both results")
                    group["publication"] = payload
                else:
                    raise ValueError("unknown dispatch event")
            previous, last_at = sha, at
        return policy, rows, groups, stopped

    def _append(self, expected, kind, event_id, payload):
        with closing(self.connect("rw")) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            _, rows, _, stopped = self.load(conn, expected)
            if stopped:
                raise ValueError("dispatcher stopped")
            row = [
                len(rows) + 1,
                kind,
                str(event_id),
                self.clock.now().isoformat(),
                canonical(payload),
                rows[-1][6] if rows else expected,
            ]
            conn.execute("INSERT INTO events VALUES (?,?,?,?,?,?,?)", (*row, digest(row)))
            self.load(conn, expected)

    def dispatch(self, tick, expected, transport):
        tick = Tick.model_validate(tick.model_dump() if isinstance(tick, Tick) else tick)
        if tick.model_batch or len(tick.model_dump_json().encode()) > 65536:
            raise ValueError("bounded unselected tick required")
        with status_lock(self.path.with_suffix(".dispatch.lock")):
            with closing(self.connect()) as conn:
                policy, _, groups, stopped = self.load(conn, expected)
            if stopped or self.clock.now() > policy.deadline:
                raise ValueError("dispatch stopped or expired")
            event_id = str(tick.event_id)
            existing = groups.get(event_id)
            if existing:
                if existing["reservation"]["tick"] != tick.model_dump_json():
                    raise ValueError("dispatch identity reused with different input")
                if existing["uncertain"] or set(existing["results"]) != set(ARMS):
                    return dict(status="OUTCOME_UNKNOWN_NO_RESEND", execution_enabled=False)
                return self._publish(expected, event_id)
            if any("publication" not in g for g in groups.values()):
                return dict(status="UNRESOLVED_PREVIOUS_DISPATCH", execution_enabled=False)
            if (len(groups) + 1) * 2 > policy.max_calls or (
                len(groups) + 1
            ) * 2 * policy.tokens_per_call > policy.max_reserved_tokens:
                return dict(status="BUDGET_EXHAUSTED", execution_enabled=False)
            ops = Operations(policy.queue, self.clock)
            report = ops.report(policy.source_hash)
            if (
                report["pending"]
                or report["queued"] != tick.sequence - 1
                or report["status"] != "OPEN"
                or report["runner"]["status"] != "AWAITING_INPUT"
            ):
                raise ValueError("source must be drained before next dispatch")
            with closing(ops.connect()) as conn:
                binding, source_rows, _, _ = ops.load(conn, policy.source_hash)
            current = tick.source_record
            if current and current.source_id != binding.source_id:
                raise ValueError("dispatch source identity mismatch")
            if source_rows:
                first = Tick.model_validate_json(source_rows[0][2]).source_record
                if bool(first) != bool(current) or (
                    first
                    and current
                    and (first.channel, first.provenance) != (current.channel, current.provenance)
                ):
                    raise ValueError("dispatch source mode or channel changed")
            prepared = Runner(binding.runner, self.clock).prepare_selector(
                tick, binding.registration_hash
            )
            self._append(
                expected, "RESERVE", event_id, dict(tick=tick.model_dump_json(), prepared=prepared)
            )
            for arm in ARMS:
                if self.clock.now() > policy.deadline:
                    self._append(
                        expected,
                        "UNCERTAIN",
                        event_id,
                        dict(arm=arm, error_type="DISPATCH_DEADLINE_EXPIRED"),
                    )
                    return dict(status="DISPATCH_EXPIRED_NO_RESEND", execution_enabled=False)
                try:
                    outbound = json.loads(canonical(prepared["requests"][arm]))
                    outbound["dispatch_limits"] = dict(
                        tokens=policy.tokens_per_call, deadline=policy.deadline.isoformat()
                    )
                    delivery = transport(outbound)
                    delivery = Delivery.model_validate(
                        delivery.model_dump() if isinstance(delivery, Delivery) else delivery
                    )
                    reply = Reply(
                        **delivery.model_dump(),
                        request_hash=prepared["requests"][arm]["request_hash"],
                        completed_at=self.clock.now(),
                    )
                except Exception as exc:
                    self._append(
                        expected,
                        "UNCERTAIN",
                        event_id,
                        dict(arm=arm, error_type=type(exc).__name__),
                    )
                    return dict(status="OUTCOME_UNKNOWN_NO_RESEND", execution_enabled=False)
                self._append(
                    expected, "RESULT", event_id, dict(arm=arm, reply=reply.model_dump(mode="json"))
                )
                if delivery.input_tokens + delivery.output_tokens > policy.tokens_per_call:
                    self._append(
                        expected,
                        "UNCERTAIN",
                        event_id,
                        dict(arm=arm, error_type="TOKEN_RESERVATION_EXCEEDED"),
                    )
                    return dict(status="TOKEN_LIMIT_EXCEEDED", execution_enabled=False)
            return self._publish(expected, event_id)

    def _publish(self, expected, event_id):
        with closing(self.connect()) as conn:
            policy, _, groups, stopped = self.load(conn, expected)
        group = groups[event_id]
        if (
            stopped
            or self.clock.now() > policy.deadline
            or group["uncertain"]
            or set(group["results"]) != set(ARMS)
        ):
            raise ValueError("dispatch not publishable")
        reservation = group["reservation"]
        raw = json.loads(reservation["tick"])
        raw["model_batch"] = Batch(
            requested_at=reservation["prepared"]["requested_at"], replies=group["results"]
        ).model_dump(mode="json")
        receipt = Operations(policy.queue, self.clock).enqueue(
            Tick.model_validate(raw), policy.source_hash
        )
        if "publication" not in group:
            self._append(
                expected,
                "PUBLISHED",
                event_id,
                dict(sequence=receipt["sequence"], source_sha=receipt["source_sha"]),
            )
        return dict(
            status="PUBLISHED",
            sequence=receipt["sequence"],
            replayed=receipt["replayed"],
            execution_enabled=False,
        )

    def stop(self, expected):
        with status_lock(self.path.with_suffix(".dispatch.lock")):
            with closing(self.connect()) as conn:
                stopped = self.load(conn, expected)[3]
            if not stopped:
                self._append(expected, "STOP", "dispatcher", {})

    def report(self, expected, checkpoint=None):
        with closing(self.connect()) as conn:
            conn.execute("BEGIN")
            policy, rows, groups, stopped = self.load(conn, expected)
        heads = {0: expected, **{r[0]: r[6] for r in rows}}
        if checkpoint and heads.get(checkpoint["dispatch"][0]) != checkpoint["dispatch"][1]:
            raise ValueError("dispatch checkpoint rollback")
        ops = Operations(policy.queue, self.clock)
        report = ops.report(policy.source_hash, checkpoint["source"] if checkpoint else None)
        with closing(ops.connect()) as conn:
            source_rows = ops.load(conn, policy.source_hash)[1]
        for row in source_rows:
            group = groups.get(row[1])
            if not group or group["uncertain"] or set(group["results"]) != set(ARMS):
                raise ValueError("source input without completed dispatch")
            raw = json.loads(group["reservation"]["tick"])
            raw["model_batch"] = Batch(
                requested_at=group["reservation"]["prepared"]["requested_at"],
                replies=group["results"],
            ).model_dump(mode="json")
            if Tick.model_validate(raw).model_dump_json() != row[2]:
                raise ValueError("source differs from completed dispatch")
        for group in groups.values():
            if "publication" in group:
                publication = group["publication"]
                seq = publication["sequence"]
                if seq > len(source_rows) or source_rows[seq - 1][5] != publication["source_sha"]:
                    raise ValueError("published source rollback")
        replies = [r for g in groups.values() for r in g["results"].values()]
        report["checkpoint"] = dict(
            source=report["checkpoint"], dispatch=[len(rows), rows[-1][6] if rows else expected]
        )
        report["model_dispatch"] = dict(
            status="STOPPED"
            if stopped
            else "EXPIRED"
            if self.clock.now() > policy.deadline
            else "UNRESOLVED"
            if any(g["uncertain"] or len(g["results"]) != 2 for g in groups.values())
            else "OPEN",
            reserved_calls=len(groups) * 2,
            max_calls=policy.max_calls,
            reserved_tokens=len(groups) * 2 * policy.tokens_per_call,
            max_reserved_tokens=policy.max_reserved_tokens,
            completed_replies=len(replies),
            unresolved_reserved_calls=len(groups) * 2 - len(replies),
            known_reported_cost_usd=str(
                sum(
                    (
                        Decimal(r["reported_cost_usd"])
                        for r in replies
                        if r["reported_cost_usd"] is not None
                    ),
                    Decimal(0),
                )
            ),
            unknown_cost_calls=len(groups) * 2
            - sum(r["reported_cost_usd"] is not None for r in replies),
            transport_verified=False,
            execution_enabled=False,
        )
        return report
