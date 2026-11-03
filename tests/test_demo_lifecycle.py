from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from fx_talanta.demo_lifecycle import DemoSchedule, ExpiryEvidence, LifecycleStore, evaluate
from fx_talanta.domain.models import AccountIdentity

START = datetime(2026, 11, 2, 12, tzinfo=UTC)
EXPIRY = START + timedelta(days=90)


@pytest.fixture
def schedule():
    return DemoSchedule(
        campaign_id=uuid4(),
        signup_at=START,
        account=AccountIdentity(
            environment="PAPER",
            venue="BROKER_DEMO",
            broker="FOREX.com Canada",
            server="test-demo",
            login="123",
        ),
    )


@pytest.mark.parametrize(
    "offset,state",
    [
        (0, "ACTIVE"),
        (76 * 86400 - 1, "ACTIVE"),
        (76 * 86400, "REPLACEMENT_DUE"),
        (83 * 86400, "HANDOFF_DUE"),
        (90 * 86400, "EXPIRED"),
    ],
)
def test_estimate_and_exact_utc_boundaries(schedule, offset, state):
    result = evaluate(schedule, START + timedelta(seconds=offset))
    assert result["state"] == state and result["expiry_basis"] == "ESTIMATED"
    assert result["effective_expiry"] == EXPIRY.isoformat()
    assert (
        not result["execution_enabled"]
        and not result["handoff_authorized"]
        and not result["cmc_affected"]
    )


def test_confirmed_unknown_conflicting_and_future_evidence(schedule):
    evidence = ExpiryEvidence(
        expires_at=START + timedelta(days=60), observed_at=START, source="test support reply"
    )
    s = schedule.model_copy(update={"confirmed_expiries": (evidence,)})
    result = evaluate(s, START + timedelta(days=47))
    assert result["state"] == "REPLACEMENT_DUE" and result["expiry_basis"] == "CONFIRMED"
    other = evidence.model_copy(update={"expires_at": START + timedelta(days=61)})
    result = evaluate(s.model_copy(update={"confirmed_expiries": (evidence, other)}), START)
    assert result["state"] == "CONFLICTING_EXPIRY" and result["secondary_pause_required"]
    assert result["effective_expiry"] == evidence.expires_at.isoformat()
    assert (
        evaluate(schedule.model_copy(update={"signup_at": None}), START)["state"]
        == "UNKNOWN_EXPIRY"
    )
    assert evaluate(schedule, START - timedelta(seconds=1))["state"] == "INVALID_TIMELINE"
    future = evidence.model_copy(update={"observed_at": START + timedelta(days=1)})
    assert (
        evaluate(s.model_copy(update={"confirmed_expiries": (future,)}), START)["state"]
        == "INVALID_TIMELINE"
    )


def test_timezone_normalization_and_bad_inputs(schedule):
    obj = schedule.model_dump(mode="json")
    obj["signup_at"] = "2026-11-02T04:00:00-08:00"
    assert DemoSchedule.model_validate(obj).signup_at == START
    obj["signup_at"] = "2026-11-02T12:00:00"
    with pytest.raises(ValueError):
        DemoSchedule.model_validate(obj)
    with pytest.raises(ValueError):
        DemoSchedule.model_validate(schedule.model_dump() | {"notice_days": 7, "handoff_days": 7})
    with pytest.raises(ValueError):
        DemoSchedule.model_validate(schedule.model_dump() | {"password": "must not be accepted"})


def test_email_time_is_explicitly_estimated_signup(schedule):
    with pytest.raises(ValueError, match="source reference"):
        DemoSchedule.model_validate(schedule.model_dump() | {"signup_at_estimated": True})
    estimated = DemoSchedule.model_validate(
        schedule.model_dump()
        | {
            "signup_at_estimated": True,
            "signup_source": "Confirmation email timestamp",
        }
    )
    result = evaluate(estimated, START)
    assert result["signup_at_estimated"] and result["expiry_basis"] == "ESTIMATED"


@pytest.mark.parametrize(
    "update", [{"environment": "LIVE"}, {"venue": "BROKER_LIVE"}, {"broker": "other"}]
)
def test_account_scope_is_demo_forex_only(schedule, update):
    with pytest.raises(ValueError):
        DemoSchedule.model_validate(
            schedule.model_dump(mode="json")
            | {
                "account": schedule.account.model_dump(mode="json") | update,
            }
        )


def test_replacement_does_not_grant_handoff_or_reset_deadline(schedule):
    with pytest.raises(ValueError):
        evaluate(schedule.model_copy(update={"replacement": schedule.account}), START)
    successor = schedule.account.model_copy(update={"login": "456"})
    with pytest.raises(ValueError):
        evaluate(
            schedule.model_copy(update={"replacement": successor, "replacement_ready": True}), START
        )
    s = schedule.model_copy(
        update={
            "replacement": successor,
            "replacement_ready": True,
            "replacement_evidence": "synthetic readiness evidence",
        }
    )
    result = evaluate(s, EXPIRY - timedelta(days=7))
    assert result["secondary_pause_required"] and not result["handoff_authorized"]
    assert result["effective_expiry"] == EXPIRY.isoformat()


def test_durable_outbox_dedup_ack_escalation_and_daily_readiness(schedule, tmp_path):
    db = tmp_path / "lifecycle.sqlite3"
    store = LifecycleStore(db)
    assert store.check(schedule, START)["pending_alert_ids"] == []
    due = EXPIRY - timedelta(days=14)
    first = store.check(schedule, due)
    alert = first["pending_alert_ids"][0]
    store = LifecycleStore(db)  # restart does not lose pending delivery
    assert store.check(schedule, due)["pending_alert_ids"] == [alert]
    assert store.acknowledge(schedule, alert) == "ACKNOWLEDGED"
    assert store.acknowledge(schedule, alert) == "ACKNOWLEDGED"
    assert store.check(schedule, due + timedelta(days=1))["pending_alert_ids"] == []
    escalated = store.check(schedule, EXPIRY - timedelta(days=7))
    assert len(escalated["pending_alert_ids"]) == 1 and escalated["pending_alert_ids"] != [alert]
    with store.connect() as conn:
        assert conn.execute("SELECT count(*) FROM events").fetchone()[0] == 3
        assert conn.execute("SELECT count(*) FROM daily_checks").fetchone()[0] == 4
    with pytest.raises(ValueError, match="backwards"):
        store.check(schedule, START)


def test_supersedes_pending_alert_without_deleting_evidence(schedule, tmp_path):
    store = LifecycleStore(tmp_path / "lifecycle.sqlite3")
    old = store.check(schedule, EXPIRY - timedelta(days=14))["pending_alert_ids"][0]
    current = store.check(schedule, EXPIRY)["pending_alert_ids"][0]
    assert current != old and store.acknowledge(schedule, old) == "SUPERSEDED"
    other = schedule.model_copy(update={"campaign_id": uuid4()})
    with pytest.raises(ValueError, match="account/campaign"):
        store.acknowledge(other, current)
    with store.connect() as conn:
        assert conn.execute("SELECT count(*) FROM events").fetchone()[0] == 2


def test_concurrent_checks_create_one_alert(schedule, tmp_path):
    store = LifecycleStore(tmp_path / "lifecycle.sqlite3")
    now = EXPIRY - timedelta(days=14)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: store.check(schedule, now), range(8)))
    assert len({r["pending_alert_ids"][0] for r in results}) == 1
    with store.connect() as conn:
        assert conn.execute("SELECT count(*) FROM events").fetchone()[0] == 1
