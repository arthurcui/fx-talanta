"""Bounded, metadata-only news delivery observation; no trading authority."""

import argparse
import json
import math
import time
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from fx_talanta.domain.models import utc
from fx_talanta.provider_pipeline import Journal, collect_once, digest, fetch, status_lock

SOURCES = ("fed", "ecb", "boj", "bls_jobs", "bls_cpi", "bls_ppi", "bls_jolts", "eurostat")
PLAN = {
    "version": "provider-delivery/1",
    "duration_seconds": 86400,
    "interval_seconds": 300,
    "minimum_success_fraction": 0.99,
    "maximum_gap_seconds": 900,
    "maximum_delivery_seconds": 360,
    "minimum_prospective_items_per_source": 1,
    "sources": list(SOURCES),
    "source_timeout_seconds": 20,
}


def stamp(value):
    return utc(datetime.fromisoformat(value))


def create_plan(directory, inventory, now):
    """Create exclusively before observation. Existing evidence is never restarted."""
    now = utc(now)
    specification = json.loads(Path(inventory).read_text())
    if set(specification["currencies"]) != {"USD", "EUR", "JPY"}:
        raise ValueError("three-currency inventory required")
    if not specification["requirements"]:
        raise ValueError("empty inventory")
    directory.mkdir(parents=True, exist_ok=False)
    plan = {
        **PLAN,
        "run_id": str(uuid4()),
        "started_at": now.isoformat(),
        "deadline": (now + timedelta(seconds=PLAN["duration_seconds"])).isoformat(),
        "inventory": specification,
        "inventory_hash": digest(specification),
        "execution_enabled": False,
        "qualified_for_trading": False,
    }
    with (directory / "plan.json").open("x") as stream:
        json.dump(plan, stream, indent=2)
    return plan


def evaluate(plan, attempts, revisions, now, phase):
    """Separate transport availability, item delivery and independently proven coverage."""
    now = utc(now)
    start, end = stamp(plan["started_at"]), stamp(plan["deadline"])
    interval = plan["interval_seconds"]
    total = math.ceil(plan["duration_seconds"] / interval)
    due = min(total, max(0, math.floor((now - start).total_seconds() / interval) + 1))
    if now >= end:
        due = total
    results = {}
    for source in plan["sources"]:
        slots = {}
        for attempt in attempts:
            began = stamp(attempt["started"])
            if attempt["source"] != source or not start <= began < end:
                continue
            slot = int((began - start).total_seconds() // interval)
            if slot >= due:
                continue
            # First attempt owns the slot, even when it fails. No retry can erase it.
            slots.setdefault(slot, attempt)
        successes = [
            row
            for row in slots.values()
            if row["status"] == "OK"
            and row["available"]
            and stamp(row["started"]) <= stamp(row["available"]) <= min(now, end)
        ]
        receipts = sorted(stamp(r["available"]) for r in successes)
        edges = [start, *receipts, min(max(now, start), end)]
        gap = max((b - a).total_seconds() for a, b in zip(edges, edges[1:], strict=False))
        first_success = min((stamp(r["started"]) for r in successes), default=None)
        latencies, initial_backfill, later_backfill, changed = [], 0, 0, 0
        for revision in revisions:
            if revision["source"] != source or stamp(revision["available"]) > min(now, end):
                continue
            value = revision["payload"]["value"]
            publication = stamp(value["published_at"])
            arrival = stamp(revision["available"])
            if revision["revision"] != 1:
                changed += 1
            elif first_success is None or publication <= first_success:
                initial_backfill += 1
            elif publication < start or arrival < publication:
                later_backfill += 1
            else:
                # Publication age at first post-baseline receipt, not guaranteed wire latency.
                latencies.append((arrival - publication).total_seconds())
        latencies.sort()
        fraction = len(successes) / due if due else 0
        complete = phase == "COMPLETE" and now >= end
        reliability = (
            complete
            and fraction >= plan["minimum_success_fraction"]
            and gap <= plan["maximum_gap_seconds"]
        )
        results[source] = {
            "slots_due": due,
            "scheduled_slots": total,
            "attempted_slots": len(slots),
            "successful_slots": len(successes),
            "success_fraction": fraction,
            "maximum_success_gap_seconds": gap,
            "initial_backfill_items_excluded": initial_backfill,
            "other_backfill_items_excluded": later_backfill,
            "revisions_requiring_independent_time_evidence": changed,
            "prospective_first_version_items": len(latencies),
            "publication_to_receipt_seconds": {
                "p50": latencies[math.ceil(len(latencies) * 0.5) - 1] if latencies else None,
                "p95": latencies[math.ceil(len(latencies) * 0.95) - 1] if latencies else None,
                "max": max(latencies) if latencies else None,
            },
            "transport_reliability_passed": reliability,
            "sampled_delivery_passed": reliability
            and len(latencies) >= plan["minimum_prospective_items_per_source"]
            and max(latencies, default=math.inf) <= plan["maximum_delivery_seconds"],
            "required_category_delivery_qualified": False,
        }
    expected_results = []
    for event in plan["inventory"].get("expected_events", []):
        scheduled = stamp(event["scheduled_at"])
        if scheduled < start or scheduled >= end:
            continue
        matches = [
            stamp(row["available"])
            for row in revisions
            if row["source"] == event["source"]
            and row["payload"]["value"]["url"] == event["expected_archive_url"]
            and start <= stamp(row["available"]) <= min(now, end)
        ]
        arrived = min(matches) if matches else None
        delay = (arrived - scheduled).total_seconds() if arrived else None
        if delay is not None:
            state = (
                "ON_TIME"
                if 0 <= delay <= plan["maximum_delivery_seconds"]
                else ("EARLY_UNVERIFIED" if delay < 0 else "LATE")
            )
        elif now <= scheduled + timedelta(seconds=plan["maximum_delivery_seconds"]):
            state = "NOT_DUE" if now < scheduled else "AWAITING_RECEIPT"
        else:
            state = "MISSING"
        expected_results.append(
            {
                "event_id": event["event_id"],
                "source": event["source"],
                "scheduled_at": event["scheduled_at"],
                "state": state,
                "first_receipt_at": arrived.isoformat() if arrived else None,
                "schedule_to_receipt_seconds": delay,
            }
        )
    return {
        "run_id": plan["run_id"],
        "phase": phase,
        "checked_at": now.isoformat(),
        "started_at": plan["started_at"],
        "deadline": plan["deadline"],
        "plan_hash": digest(plan),
        "sources": results,
        "independent_scheduled_release_checks": expected_results,
        "coverage_gaps": [r["id"] for r in plan["inventory"]["requirements"]],
        "coverage_qualified": False,
        "qualified_for_trading": False,
        "execution_enabled": False,
        "limitation": (
            "Feed transport and prospective item-age evidence only. Independent per-category "
            "release matching, omissions, source rights, and full coverage remain separate gates."
        ),
    }


def read_report(directory, now, phase):
    plan = json.loads((directory / "plan.json").read_text())
    with closing(Journal(directory / "journal.sqlite")) as journal:
        expected = journal.conn.execute(
            "SELECT value FROM metadata WHERE id='campaign_plan_hash'"
        ).fetchone()
        if not expected or expected[0] != digest(plan):
            raise ValueError("campaign plan changed")
        attempts = [
            dict(zip(("source", "started", "available", "status"), row, strict=True))
            for row in journal.conn.execute(
                "SELECT a.source,a.started,o.available,o.status FROM attempts a "
                "LEFT JOIN outcomes o ON a.id=o.attempt ORDER BY a.rowid"
            )
        ]
        revisions = [
            {"source": s, "revision": r, "available": a, "payload": json.loads(p)}
            for s, r, a, p in journal.conn.execute(
                "SELECT source,revision,available,payload FROM revisions"
            )
        ]
    return evaluate(plan, attempts, revisions, now, phase)


def publish(directory, report):
    temporary = directory / "status.pending"
    temporary.write_text(json.dumps(report, indent=2))
    temporary.replace(directory / "status.json")


def run(directory, inventory, tls):
    plan = create_plan(directory, inventory, datetime.now(UTC))
    baseline, monotonic = stamp(plan["started_at"]), time.monotonic()
    deadline = stamp(plan["deadline"])
    next_slot = 0
    with status_lock(directory / "collector.lock"):
        with closing(Journal(directory / "journal.sqlite", create=True)) as journal:
            with journal.conn:
                journal.conn.execute(
                    "INSERT INTO metadata VALUES ('campaign_plan_hash', ?)", (digest(plan),)
                )
            try:
                while datetime.now(UTC) < deadline:
                    now = datetime.now(UTC)
                    if abs((now - baseline).total_seconds() - (time.monotonic() - monotonic)) > 1:
                        raise ValueError("clock discontinuity")
                    if (directory / "stop").exists():
                        publish(directory, read_report(directory, now, "STOPPED"))
                        return 2
                    slot = int((now - baseline).total_seconds() // plan["interval_seconds"])
                    if slot < next_slot:
                        time.sleep(min(1, max(0, (deadline - now).total_seconds())))
                        continue
                    next_slot = slot + 1

                    def bounded_fetch(source, **kwargs):
                        if datetime.now(UTC) >= deadline:
                            return {"status": "FAILED", "error": "CAMPAIGN_DEADLINE"}
                        return fetch(source, timeout=plan["source_timeout_seconds"], **kwargs)

                    collect_once(journal, SOURCES, tls=tls, fetcher=bounded_fetch)
                    # Eight sources each have a durable attempt and a 20s child watchdog.
                    now = datetime.now(UTC)
                    if abs((now - baseline).total_seconds() - (time.monotonic() - monotonic)) > 1:
                        raise ValueError("clock discontinuity")
                    publish(directory, read_report(directory, now, "RUNNING"))
                now = datetime.now(UTC)
                if abs((now - baseline).total_seconds() - (time.monotonic() - monotonic)) > 1:
                    raise ValueError("clock discontinuity")
                report = read_report(directory, now, "COMPLETE")
                publish(directory, report)
                return 0
            except Exception:
                publish(directory, read_report(directory, datetime.now(UTC), "FAILED"))
                return 2


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("run", "status"))
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--inventory", type=Path)
    parser.add_argument("--tls", choices=("default", "native"), default="default")
    args = parser.parse_args(argv)
    try:
        if args.command == "run":
            if not args.inventory:
                raise ValueError("inventory required")
            return run(args.directory, args.inventory, args.tls)
        saved = json.loads((args.directory / "status.json").read_text())
        report = read_report(args.directory, datetime.now(UTC), saved["phase"])
        report["last_status_at"] = saved["checked_at"]
        report["worker_liveness_verified"] = False
        print(json.dumps(report, indent=2))
        return 0
    except Exception:
        print("Provider observation unavailable; inspect preserved evidence. Trading disabled.")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
