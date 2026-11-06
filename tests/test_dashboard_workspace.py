import hashlib
import json
from datetime import timedelta
from uuid import uuid4

import pytest
from test_dashboard import TOKEN

from fx_talanta.clock import FakeClock
from fx_talanta.dashboard.app import Dashboard
from fx_talanta.dashboard.demo import AT, demo
from fx_talanta.dashboard.trace import trace
from fx_talanta.domain.models import EvidenceLink


@pytest.fixture
def app(tmp_path):
    value = Dashboard(demo(), tmp_path, TOKEN, FakeClock(AT))
    yield value
    value.close()


def test_trace_explicit_links_excludes_unlinked_health():
    snapshot = demo()
    result = trace(snapshot, str(snapshot.records[0].record_id))
    assert {r["kind"] for r in result["nodes"]} == {"decision", "risk", "experience"}
    assert len(result["links"]) == 2 and result["missing"] == []
    assert all(link["resolved"] for link in result["links"])
    assert not result["execution_enabled"]
    index = {str(r.record_id): r for r in snapshot.records}
    for node in result["nodes"]:
        assert (
            node["sha256"]
            == hashlib.sha256(index[node["id"]].model_dump_json().encode()).hexdigest()
        )


def test_missing_links_cycles_and_correlation_are_not_inferred():
    snapshot = demo()
    decision, risk, case, health = snapshot.records
    missing = uuid4()
    decision = decision.model_copy(
        update={
            "references": (
                EvidenceLink(record_id=missing, relation="NEWS"),
                EvidenceLink(record_id=risk.record_id, relation="CASE"),
            )
        }
    )
    health = health.model_copy(
        update={"references": (EvidenceLink(record_id=missing, relation="NEWS"),)}
    )
    snapshot = snapshot.model_copy(update={"records": (decision, risk, case, health)})
    result = trace(snapshot, str(decision.record_id))
    assert len(result["nodes"]) == 3  # cycle terminates; shared missing target does not bridge
    assert result["missing"] == [str(missing)]
    assert sum(not link["resolved"] for link in result["links"]) == 1
    with pytest.raises(ValueError):
        trace(snapshot, str(uuid4()))
    with pytest.raises(ValueError):
        trace(snapshot, "../state")


def test_incident_literal_search_and_stable_cursor(app):
    now = app.clock.now()
    for i in range(205):
        app.monitor.transitions(
            {"fixture": f"event-{i}"}, now + timedelta(seconds=i), {"default": "fixture"}
        )
    first = app.incidents("fixture")
    assert first["total"] == 205 and first["shown"] == 100
    cursor = first["next_before"]
    app.monitor.transitions(
        {"fixture": "new-event"}, now + timedelta(seconds=206), {"default": "fixture"}
    )
    second = app.incidents("fixture", cursor)
    third = app.incidents("fixture", second["next_before"])
    ids = [e["id"] for page in (first, second, third) for e in page["events"]]
    assert len(ids) == len(set(ids)) == 205
    assert third["next_before"] is None and third["shown"] == 5
    assert app.incidents("%")["total"] == 0
    assert app.incidents("' OR 1=1 --")["total"] == 0
    assert app.incidents("EVENT-1")["total"] == 111
    with pytest.raises(ValueError):
        app.incidents("x" * 129)


def test_export_hash_bounds_and_no_credentials(app):
    report = app.report()
    payload = report["payload"]
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    assert hashlib.sha256(raw.encode()).hexdigest() == report["sha256"]
    assert TOKEN not in raw and str(app.state) not in raw
    assert "session_expires_at" not in raw and "login" not in raw
    assert payload["scope"] == "OFFLINE_INSPECTION_NOT_QUALIFICATION"
    assert payload["overview"]["positions_status"] == "NOT_RECONCILED"
    assert payload["limits"]["incident_events"] == 100
    assert not payload["execution_enabled"]
    assert app.report() == report
