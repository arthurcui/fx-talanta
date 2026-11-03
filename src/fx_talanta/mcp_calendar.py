"""Native MT5 calendar reads into an optional, fail-closed provider journal."""

import argparse
import json
import multiprocessing
import re
import time
from contextlib import closing
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Literal

from pydantic import AfterValidator, Field, model_validator

from fx_talanta.domain.models import FrozenModel, Hash, Timestamp, utc
from fx_talanta.mcp_client import LIMIT, Client, McpError, strict_json, validate_endpoint
from fx_talanta.mt5_calendar import ClockPolicy
from fx_talanta.provider_pipeline import Journal, digest, status_lock

SOURCE = "mt5_mcp_calendar"
CURRENCIES = ("USD", "EUR", "JPY")
TIME_EXACT = "Source publishes an exact time of an event"
MAX_VALUES = 1000
WORKER_SECONDS = 90


def uint(value, *, zero=False):
    if not isinstance(value, str) or not re.fullmatch(r"0|[1-9][0-9]{0,19}", value):
        raise ValueError("invalid native ID")
    if not (0 if zero else 1) <= int(value) < 2**64:
        raise ValueError("native ID out of range")
    return value


def wall(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d", value):
        raise ValueError("timezone-free server timestamp required")
    return datetime.fromisoformat(value)


def decode(clock, value):
    return clock.decode(int(wall(value).replace(tzinfo=UTC).timestamp()))


def encode(clock, value):
    value = utc(value)
    candidates = [s for s in clock.segments if s.utc_from <= value < s.utc_until]
    if len(candidates) != 1:
        raise ValueError("query outside clock policy")
    result = (value + timedelta(seconds=candidates[0].server_offset_seconds)).replace(tzinfo=None)
    if decode(clock, result.isoformat()) != value:
        raise ValueError("query crosses an ambiguous server time")
    return result.isoformat()


class Anchor(FrozenModel):
    value_id: Annotated[str, AfterValidator(uint)]
    event_id: Annotated[str, AfterValidator(uint)]
    scheduled_utc: Timestamp
    reference_hash: Hash


class Plan(FrozenModel):
    version: Literal["mcp-calendar-shadow/1"] = "mcp-calendar-shadow/1"
    endpoint: Annotated[str, AfterValidator(validate_endpoint)]
    terminal_identity_hash: Hash
    clock: ClockPolicy
    coverage_from: Timestamp
    coverage_until: Timestamp
    currencies: tuple[Literal["USD"], Literal["EUR"], Literal["JPY"]] = CURRENCIES
    anchors: Annotated[tuple[Anchor, ...], Field(min_length=1, max_length=8)]
    execution_enabled: Literal[False] = False

    @model_validator(mode="after")
    def bounded(self):
        if self.clock.evidence_type != "INDEPENDENT_CALENDAR_CHECK":
            raise ValueError("independently verified clock required")
        if not timedelta(0) < self.coverage_until - self.coverage_from <= timedelta(days=7):
            raise ValueError("explicit window must be at most seven days")
        if len({a.value_id for a in self.anchors}) != len(self.anchors):
            raise ValueError("duplicate anchors")
        # Reject windows spanning offset changes; ambiguous/unknown times never get guessed.
        offsets = {
            s.server_offset_seconds
            for s in self.clock.segments
            if s.utc_from < self.coverage_until and s.utc_until > self.coverage_from
        }
        if len(offsets) != 1:
            raise ValueError("split collection windows at clock transitions")
        encode(self.clock, self.coverage_from)
        encode(self.clock, self.coverage_until)
        for anchor in self.anchors:
            encode(self.clock, anchor.scheduled_utc)
        return self


def terminal_identity(terminal):
    return digest({k: terminal[k] for k in ("company", "terminal_path", "data_path")})


def clock_check(client, plan, now):
    data = client.tool("get_time_information", {})
    reported = utc(datetime.fromisoformat(data["utc_time"]))
    if abs((utc(now()) - reported).total_seconds()) > 2:
        raise ValueError("terminal UTC disagrees with receipt clock")
    server = decode(plan.clock, data["trade_server_last_known_time"])
    if abs((server - reported).total_seconds()) > 5:
        raise ValueError("last-known server time does not verify the pinned offset")
    return {"utc_time": reported.isoformat(), "server_time": data["trade_server_last_known_time"]}


def cursor_read(client, cursor, *, seed_event_id=None):
    arguments = {"change_id": cursor}
    if seed_event_id is not None:
        if cursor != "0":
            raise ValueError("only the initial cursor may use an event filter")
        arguments["event_id"] = uint(seed_event_id)
    result = client.tool("economic_calendar_list_values_last", arguments)
    if result.get("input_change_id") != cursor:
        raise ValueError("cursor response does not match request")
    new = uint(result["database_change_id"])
    if int(new) < int(cursor):
        raise ValueError("calendar cursor regressed")
    rows = result.get("values", [])
    if not isinstance(rows, list) or len(rows) >= MAX_VALUES:
        raise ValueError("unbounded calendar delta")
    if result.get("truncated") or result.get("count", len(rows)) != len(rows):
        raise ValueError("partial calendar delta")
    for row in rows:
        if int(uint(row["change_id"], zero=True)) > int(new):
            raise ValueError("value newer than returned cursor")
    return new, rows


def catalog(client):
    events, counts = {}, {}
    for currency in CURRENCIES:
        result = client.tool(
            "economic_calendar_list_events_by_currency", {"currency_code": currency}
        )
        rows = result["events"]
        if (
            not isinstance(rows, list)
            or not 0 < len(rows) < MAX_VALUES
            or result.get("count") != len(rows)
            or result.get("truncated")
        ):
            raise ValueError("partial event catalog")
        counts[currency] = len(rows)
        for raw in rows:
            identity = uint(raw["id"])
            if identity in events:
                raise ValueError("duplicate event catalog identity")
            fields = ("id", "name", "time_mode", "importance", "unit", "multiplier", "digits")
            row = {k: raw[k] for k in fields}
            if any(not isinstance(row[k], str) or len(row[k]) > 512 for k in fields[:-1]):
                raise ValueError("invalid event metadata")
            if type(row["digits"]) is not int or not 0 <= row["digits"] <= 16:
                raise ValueError("invalid precision")
            events[identity] = {
                **row,
                "currency": currency,
                "change_id": uint(raw["change_id"], zero=True),
            }
    return events, counts


def number(value):
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ValueError("invalid economic value")
    result = Decimal(str(value))
    if not result.is_finite() or abs(result) > Decimal("1e24"):
        raise ValueError("invalid economic value")
    return str(result)


def normalize(row, event, plan):
    if type(row.get("time_unknown")) is not bool or type(row.get("revision")) is not int:
        raise ValueError("invalid calendar value schema")
    if row["revision"] < 0:
        raise ValueError("invalid source revision")
    scheduled, uncertainty = None, None
    if row["time_unknown"] or event["time_mode"] != TIME_EXACT:
        uncertainty = "PROVIDER_TIME_NOT_EXACT"
    else:
        wall(row["time"])
        try:
            scheduled = decode(plan.clock, row["time"]).isoformat()
        except ValueError:
            uncertainty = "SERVER_TIME_OUTSIDE_VERIFIED_MAPPING"
    return {
        "value_id": uint(row["id"]),
        "event_id": uint(row["event_id"]),
        "currency": event["currency"],
        "name": event["name"],
        "scheduled_at": scheduled,
        "server_time": row.get("time"),
        "uncertainty": uncertainty,
        "status": "SCHEDULED",
        "impact": {
            "High importance": "HIGH",
            "Medium importance": "MEDIUM",
            "Low importance": "LOW",
        }.get(event["importance"], "UNKNOWN"),
        "source_revision": row["revision"],
        "source_change_id": uint(row["change_id"], zero=True),
        "event_change_id": event["change_id"],
        "time_mode": event["time_mode"],
        "time_unknown": row["time_unknown"],
        "reference_period_start": row.get("reference_period_start"),
        **{
            key: number(row.get(field))
            for key, field in (
                ("actual", "actual_value"),
                ("forecast", "forecast_value"),
                ("previous", "prev_value"),
                ("revised_previous", "revised_prev_value"),
            )
        },
        **{k: event[k] for k in ("unit", "multiplier", "digits")},
    }


def snapshot(client, plan, input_cursor, *, tracked_ids=(), now=lambda: datetime.now(UTC)):
    started, monotonic = utc(now()), time.monotonic()
    if not plan.clock.verified_at <= started < plan.coverage_until:
        raise ValueError("clock evidence is not current for collection")
    client.stage = "INITIALIZE_AND_TERMINAL_BINDING"
    client.start()
    terminal = client.tool("terminal_get_info", {})["terminal"]
    if (
        terminal["build"] != plan.clock.terminal_build
        or terminal_identity(terminal) != plan.terminal_identity_hash
    ):
        raise ValueError("terminal identity/build differs from plan")
    client.stage = "CLOCK_PRECHECK"
    before = clock_check(client, plan, now)
    client.stage = "INDEPENDENT_ANCHORS"
    for anchor in plan.anchors:
        value = client.tool("economic_calendar_get_value_by_id", {"value_id": anchor.value_id})[
            "value"
        ]
        if (
            value["id"] != anchor.value_id
            or value["event_id"] != anchor.event_id
            or value["time_unknown"] is not False
            or decode(plan.clock, value["time"]) != anchor.scheduled_utc
        ):
            raise ValueError("independent clock anchor mismatch")
    client.stage = "CURRENCY_CATALOGS"
    events, counts = catalog(client)
    if any(events.get(a.event_id, {}).get("time_mode") != TIME_EXACT for a in plan.anchors):
        raise ValueError("independent anchor has uncertain provider time mode")
    # Capture the initial cursor BEFORE the snapshot, then read the changes since it.
    cursor = input_cursor
    if cursor is None:
        client.stage = "INITIAL_CURSOR_SCOPED"
        # MT5's unfiltered zero-cursor call timed out in actual probes. The scoped
        # call also returns the DATABASE-wide cursor; never use filtered_change_id.
        cursor, _ = cursor_read(client, "0", seed_event_id=plan.anchors[0].event_id)
    start, end = encode(plan.clock, plan.coverage_from), encode(plan.clock, plan.coverage_until)
    client.stage = "BOUNDED_SNAPSHOT"
    full = client.tool(
        "economic_calendar_list_values",
        {"datetime_from": start, "datetime_to": end, "limit": MAX_VALUES},
    )
    rows = full["values"]
    if (
        not isinstance(rows, list)
        or len(rows) >= MAX_VALUES
        or full.get("count") != len(rows)
        or full.get("truncated") is not False
    ):
        raise ValueError("partial calendar snapshot")
    if any(not start <= row["time"] < end for row in rows):
        raise ValueError("snapshot outside requested range")
    client.stage = "CURSOR_DELTA"
    output_cursor, delta = cursor_read(client, cursor)
    retained = set(tracked_ids) | {row["id"] for row in rows}
    delta = [row for row in delta if row["id"] in retained or start <= row["time"] < end]
    client.stage = "VALUE_NORMALIZATION"
    selected = {}
    for row in [*rows, *delta]:
        identity = uint(row["id"])
        event_id = uint(row["event_id"])
        change = int(uint(row["change_id"], zero=True))
        if change > int(output_cursor):
            raise ValueError("snapshot newer than completed cursor")
        if event_id not in events:
            continue
        # Retain tracked reschedules outside the query window. Unmapped times stay
        # uncertain, so they cannot erase the previously exact blackout.
        previous = selected.get(identity)
        if previous:
            old_change = int(previous["change_id"])
            if old_change == change and previous != row:
                raise ValueError("conflicting provider value at same change ID")
            if change < old_change:
                continue
        selected[identity] = row
    normalized = [normalize(row, events[row["event_id"]], plan) for row in selected.values()]
    client.stage = "CLOCK_POSTCHECK"
    after = clock_check(client, plan, now)
    finished = utc(now())
    if abs((finished - started).total_seconds() - (time.monotonic() - monotonic)) > 2:
        raise ValueError("collection clock discontinuity")
    return {
        "provenance": "MT5_NATIVE_MCP",
        "plan_hash": digest(plan.model_dump(mode="json")),
        "input_cursor": input_cursor,
        "database_cursor": output_cursor,
        "started_at": started.isoformat(),
        "finished_at": finished.isoformat(),
        "coverage_from": plan.coverage_from.isoformat(),
        "coverage_until": plan.coverage_until.isoformat(),
        "catalog_counts": counts,
        "catalog_hash": digest(events),
        "clock_before": before,
        "clock_after": after,
        "events": normalized,
        "uncertain_time_ids": [x["value_id"] for x in normalized if x["scheduled_at"] is None],
        "qualified_for_trading": False,
        "execution_enabled": False,
    }


def checkpoint(conn):
    row = conn.execute(
        "SELECT o.payload FROM outcomes o JOIN attempts a ON a.id=o.attempt "
        "WHERE a.source=? AND o.status='OK' ORDER BY a.rowid DESC LIMIT 1",
        (SOURCE,),
    ).fetchone()
    return json.loads(row[0])["payload"] if row else None


def candidates(conn, payload, now):
    """Called inside the journal write transaction; the outcome IS the checkpoint."""
    if (
        payload["provenance"] != "MT5_NATIVE_MCP"
        or payload["execution_enabled"] is not False
        or payload["qualified_for_trading"] is not False
    ):
        raise ValueError("invalid MCP provenance or authority")
    prior = checkpoint(conn)
    if payload["input_cursor"] != (prior["database_cursor"] if prior else None):
        raise ValueError("stale checkpoint; re-read committed cursor")
    if prior and payload["plan_hash"] != prior["plan_hash"]:
        raise ValueError("plan change requires a separate journal")
    if int(uint(payload["database_cursor"])) < int(payload["input_cursor"] or "0"):
        raise ValueError("cursor rollback")
    start, end = (utc(datetime.fromisoformat(payload[k])) for k in ("started_at", "finished_at"))
    if not start <= end <= now or (end - start).total_seconds() > WORKER_SECONDS:
        raise ValueError("invalid snapshot timing")
    if prior and start < utc(datetime.fromisoformat(prior["finished_at"])):
        raise ValueError("snapshot predates committed checkpoint")
    if set(payload["catalog_counts"]) != set(CURRENCIES) or any(
        n <= 0 for n in payload["catalog_counts"].values()
    ):
        raise ValueError("currency catalog incomplete")
    result = [(uint(v["value_id"]), v) for v in payload["events"]]
    if len({i for i, _ in result}) != len(result):
        raise ValueError("duplicate release-instance identity")
    return result


def _worker(sender, export_file, raw_plan, cursor, tracked_ids):
    client = None
    try:
        plan = Plan.model_validate(raw_plan)
        client = Client(export_file, plan.endpoint)
        result = {
            "status": "OK",
            "payload": snapshot(client, plan, cursor, tracked_ids=tracked_ids),
        }
    except McpError as exc:
        result = {"status": "FAILED", "error": str(exc)}
    except Exception:
        result = {"status": "FAILED", "error": "MCP_CALENDAR_VALIDATION_OR_TRANSPORT"}
    result["stage"] = getattr(client, "stage", "CONFIGURATION")
    result["transport_attempts"] = client.attempts if client else []
    try:
        sender.send_bytes(json.dumps(result).encode())
    finally:
        sender.close()


def fetch(export_file, plan, cursor, tracked_ids):
    context = multiprocessing.get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    worker = context.Process(
        target=_worker,
        args=(sender, str(export_file), plan.model_dump(mode="json"), cursor, tracked_ids),
        daemon=True,
    )
    try:
        worker.start()
        sender.close()
        if not receiver.poll(WORKER_SECONDS):
            return {"status": "FAILED", "error": "MCP_CALENDAR_DEADLINE"}
        return strict_json(receiver.recv_bytes(2 * LIMIT))
    except Exception:
        return {"status": "FAILED", "error": "MCP_CALENDAR_WORKER_FAILED"}
    finally:
        receiver.close()
        sender.close()
        if worker.pid:
            worker.join(0.1)
            if worker.is_alive():
                worker.terminate()
                worker.join(1)
            if worker.is_alive():
                worker.kill()
                worker.join(1)
            if worker.is_alive():
                raise McpError("MCP_WORKER_DID_NOT_STOP")
            worker.close()


def collect(journal, export_file, plan, *, fetcher=fetch, now=lambda: datetime.now(UTC)):
    plan = Plan.model_validate(plan.model_dump(mode="json"))
    attempt = journal.begin(SOURCE, utc(now()))
    try:
        prior = checkpoint(journal.conn)
        if prior and prior["plan_hash"] != digest(plan.model_dump(mode="json")):
            raise ValueError("pinned calendar plan changed")
        cursor = prior["database_cursor"] if prior else None
        tracked_ids = [
            row[0]
            for row in journal.conn.execute(
                "SELECT DISTINCT identity FROM revisions WHERE source=?", (SOURCE,)
            )
        ]
        if len(tracked_ids) > 10000:
            raise ValueError("calendar retention bound")
        result = fetcher(export_file, plan, cursor, tracked_ids)
        journal.finish(attempt, result, utc(now()))
    except Exception:
        result = {"status": "FAILED", "error": "MCP_CALENDAR_COLLECTION_OR_COMMIT"}
        journal.finish(attempt, result, utc(now()))
    return {"status": result["status"], "execution_enabled": False, "qualified_for_trading": False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mcp-export", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--journal", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        with args.plan.open("rb") as stream:
            raw = stream.read(LIMIT + 1)
        if len(raw) > LIMIT:
            raise ValueError("plan bound")
        plan = Plan.model_validate(strict_json(raw))
        with status_lock(args.journal.with_suffix(".collector")):
            with closing(Journal(args.journal, create=True)) as journal:
                result = collect(journal, args.mcp_export, plan)
                result["calendar_revision_count"] = journal.conn.execute(
                    "SELECT count(*) FROM revisions WHERE source=?", (SOURCE,)
                ).fetchone()[0]
                result["cursor_committed"] = checkpoint(journal.conn) is not None
                print(json.dumps(result))
        return 0 if result["status"] == "OK" else 2
    except Exception:
        print("Native MCP calendar unavailable; entries remain blocked.")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
