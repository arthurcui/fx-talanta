import json
from datetime import UTC, datetime, timedelta

import pytest

from fx_talanta.provider_campaign import PLAN, create_plan, evaluate, read_report
from fx_talanta.provider_pipeline import Journal, digest

START = datetime(2026, 11, 3, tzinfo=UTC)


def plan():
    return {
        **PLAN,
        "run_id": "fixture",
        "started_at": START.isoformat(),
        "deadline": (START + timedelta(days=1)).isoformat(),
        "inventory": {"requirements": [{"id": "USD_POLICY"}, {"id": "JPY_INFLATION"}]},
    }


def attempts():
    return [
        {
            "source": source,
            "started": (START + timedelta(seconds=slot * 300)).isoformat(),
            "available": (START + timedelta(seconds=slot * 300 + 1)).isoformat(),
            "status": "OK",
        }
        for source in PLAN["sources"]
        for slot in range(288)
    ]


def revision(published, arrived, number=1):
    return {
        "source": "fed",
        "revision": number,
        "available": arrived.isoformat(),
        "payload": {"value": {"published_at": published.isoformat()}},
    }


def test_full_transport_cannot_certify_silent_feed_or_currency_coverage():
    report = evaluate(plan(), attempts(), [], START + timedelta(days=1), "COMPLETE")
    assert all(s["transport_reliability_passed"] for s in report["sources"].values())
    assert not any(s["sampled_delivery_passed"] for s in report["sources"].values())
    assert report["coverage_gaps"] == ["USD_POLICY", "JPY_INFLATION"]
    assert not report["coverage_qualified"] and not report["qualified_for_trading"]


def test_short_run_and_stopped_worker_never_pass_elapsed_gate():
    for now, phase in (
        (START + timedelta(minutes=5), "COMPLETE"),
        (START + timedelta(days=1), "RUNNING"),
        (START + timedelta(days=2), "STOPPED"),
    ):
        report = evaluate(plan(), attempts(), [], now, phase)
        assert not report["sources"]["fed"]["transport_reliability_passed"]


def test_failed_slots_and_missing_tail_cannot_be_repaired_with_duplicate_attempts():
    rows = attempts()
    failed = [dict(r, status="FAILED") for r in rows if r["source"] == "fed"]
    report = evaluate(plan(), failed + rows, [], START + timedelta(days=1), "COMPLETE")
    assert report["sources"]["fed"]["successful_slots"] == 0
    assert not report["sources"]["fed"]["transport_reliability_passed"]
    missing = [r for r in rows if r["source"] != "fed" or stamp_seconds(r) < 85000]
    report = evaluate(plan(), missing, [], START + timedelta(days=1), "COMPLETE")
    assert report["sources"]["fed"]["maximum_success_gap_seconds"] > 900
    assert not report["sources"]["fed"]["transport_reliability_passed"]


def stamp_seconds(row):
    return (datetime.fromisoformat(row["started"]) - START).total_seconds()


def test_initial_backfill_and_revisions_are_not_new_release_latency():
    news = [
        revision(START - timedelta(days=1), START + timedelta(seconds=1)),
        revision(START + timedelta(seconds=50), START + timedelta(seconds=301)),
        revision(START - timedelta(days=1), START + timedelta(seconds=601), 2),
    ]
    report = evaluate(plan(), attempts(), news, START + timedelta(days=1), "COMPLETE")
    fed = report["sources"]["fed"]
    assert fed["initial_backfill_items_excluded"] == 1
    assert fed["revisions_requiring_independent_time_evidence"] == 1
    assert fed["prospective_first_version_items"] == 1
    assert fed["publication_to_receipt_seconds"]["max"] == 251
    assert fed["sampled_delivery_passed"]
    assert not fed["required_category_delivery_qualified"]


def test_late_new_item_fails_delivery_even_when_all_polls_succeed():
    news = [revision(START + timedelta(seconds=1), START + timedelta(seconds=901))]
    report = evaluate(plan(), attempts(), news, START + timedelta(days=1), "COMPLETE")
    fed = report["sources"]["fed"]
    assert fed["transport_reliability_passed"]
    assert not fed["sampled_delivery_passed"]


def test_independent_schedule_detects_missing_and_late_despite_successful_polls():
    manifest = plan()
    manifest["inventory"]["expected_events"] = [
        {
            "event_id": "bls-example",
            "source": "bls_jolts",
            "scheduled_at": (START + timedelta(hours=2)).isoformat(),
            "expected_archive_url": "https://www.bls.gov/news.release/archives/jolts_11032026.htm",
        }
    ]
    row = {
        "source": "bls_jolts",
        "revision": 1,
        "available": (START + timedelta(hours=2, minutes=8)).isoformat(),
        "payload": {
            "value": {
                "url": manifest["inventory"]["expected_events"][0]["expected_archive_url"],
                "published_at": (START + timedelta(hours=2)).isoformat(),
            }
        },
    }
    for rows, state in (([], "MISSING"), ([row], "LATE")):
        result = evaluate(manifest, attempts(), rows, START + timedelta(days=1), "COMPLETE")
        assert result["sources"]["bls_jolts"]["transport_reliability_passed"]
        assert result["independent_scheduled_release_checks"][0]["state"] == state
        assert not result["qualified_for_trading"]


def test_plan_is_exclusive_and_its_hash_is_bound_to_journal(tmp_path):
    inventory = tmp_path / "inventory.json"
    inventory.write_text(
        json.dumps({"currencies": ["USD", "EUR", "JPY"], "requirements": [{"id": "USD_POLICY"}]})
    )
    directory = tmp_path / "campaign"
    manifest = create_plan(directory, inventory, START)
    with pytest.raises(FileExistsError):
        create_plan(directory, inventory, START)
    journal = Journal(directory / "journal.sqlite", create=True)
    with journal.conn:
        journal.conn.execute(
            "INSERT INTO metadata VALUES ('campaign_plan_hash', ?)", (digest(manifest),)
        )
    journal.close()
    assert not read_report(directory, START, "RUNNING")["qualified_for_trading"]
    manifest["minimum_success_fraction"] = 0
    (directory / "plan.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="plan changed"):
        read_report(directory, START, "COMPLETE")
