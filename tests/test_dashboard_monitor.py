import json
from datetime import timedelta
from uuid import uuid4

import pytest
from test_bls_calendar import calendar
from test_dashboard import TOKEN, chat

from fx_talanta.clock import FakeClock
from fx_talanta.dashboard.app import Dashboard
from fx_talanta.dashboard.demo import AT, demo
from fx_talanta.dashboard.monitor import Telemetry


@pytest.fixture
def bound(tmp_path):
    path = tmp_path / "telemetry.json"
    run = uuid4()
    app = Dashboard(
        demo(), tmp_path / "state", TOKEN, FakeClock(AT), telemetry=path, telemetry_run=run
    )
    payload = Telemetry(
        account=demo().account,
        run_id=run,
        sequence=1,
        generated_at=AT,
        provenance="SIMULATED",
        channels=demo().channels,
    )
    path.write_text(payload.model_dump_json(), encoding="utf-8")
    yield app, path, payload
    app.close()


def test_missing_invalid_and_recovery_preserve_evidence_and_deduplicate(bound):
    app, path, payload = bound
    first = app.overview()
    assert first["telemetry_source"]["status"] == "RECENT"
    assert first["channels"][0]["freshness"] == "FRESH"
    assert app.overview()["incidents"]["total"] == first["incidents"]["total"]
    digest = first["telemetry_source"]["sha256"]
    path.unlink()
    absent = app.overview()
    assert absent["telemetry_source"]["status"] == "MISSING"
    assert absent["telemetry_source"]["sha256"] == digest
    assert absent["channels"][0]["freshness"] == "SOURCE_UNAVAILABLE"
    path.write_text("{", encoding="utf-8")
    assert app.overview()["telemetry_source"]["status"] == "INVALID"
    path.write_text(payload.model_dump_json(), encoding="utf-8")
    restored = app.overview()
    assert restored["telemetry_source"]["status"] == "RECENT"
    states = [
        e["state"] for e in restored["incidents"]["events"] if e["kind"] == "telemetry-source"
    ]
    assert states == ["RECENT", "INVALID", "MISSING", "RECENT"]
    assert app.repo.conn.execute("SELECT count(*) FROM telemetry").fetchone()[0] == 1
    assert not any(c["entry_ready"] for c in restored["channels"])


@pytest.mark.parametrize(
    "change",
    [
        "run",
        "account",
        "sequence",
        "conflict",
        "future",
        "timestamp",
        "oversize",
        "live",
        "enabled",
    ],
)
def test_reject_untrusted_revisions(bound, change):
    app, path, payload = bound
    app.overview()
    value = payload.model_dump(mode="json")
    value["sequence"] = 2
    if change == "run":
        value["run_id"] = str(uuid4())
    if change == "account":
        value["account"]["login"] = "another"
    if change == "sequence":
        value["sequence"] = 0
    if change == "conflict":
        value["sequence"] = 1
        value["provenance"] = "RECORDED"
    if change == "future":
        value["generated_at"] = (AT + timedelta(seconds=1)).isoformat()
    if change == "timestamp":
        value["channels"][0]["quote_at"] = (AT - timedelta(seconds=5)).isoformat()
    if change == "live":
        value["account"]["environment"] = "LIVE"
    if change == "enabled":
        value["execution_enabled"] = True
    path.write_text("x" * 65537 if change == "oversize" else json.dumps(value), encoding="utf-8")
    result = app.overview()
    assert result["telemetry_source"]["status"] == "INVALID"
    assert result["telemetry_source"]["sequence"] == 1
    assert app.repo.conn.execute("SELECT count(*) FROM telemetry").fetchone()[0] == 1


def test_restart_binding_highwater_and_saved_answers(bound):
    app, path, payload = bound
    app.overview()
    answer = app.chat(chat())
    app.close()
    resumed = Dashboard(
        demo(),
        app.state,
        "new-token" * 8,
        FakeClock(AT),
        telemetry=path,
        telemetry_run=payload.run_id,
    )
    try:
        assert resumed.history()["answers"] == [answer]
        assert resumed.overview()["telemetry_source"]["sequence"] == 1
        with pytest.raises(PermissionError):
            resumed.authorize(TOKEN)
        resumed.clock.advance(timedelta(seconds=20))
        assert resumed.overview()["telemetry_source"]["status"] == "STALE"
        resumed.clock = FakeClock(AT)
        with pytest.raises(ValueError, match="rollback"):
            resumed.overview()
    finally:
        resumed.close()
    with pytest.raises(ValueError, match="rebound"):
        Dashboard(demo(), app.state, TOKEN, FakeClock(AT), telemetry=path, telemetry_run=uuid4())


def test_new_sequence_cannot_refresh_old_quote_and_calendar_shows_events(bound):
    app, path, payload = bound
    app.overview()
    app.clock.advance(timedelta(seconds=10))
    value = payload.model_copy(update={"sequence": 3, "generated_at": app.clock.now()})
    path.write_text(value.model_dump_json(), encoding="utf-8")
    result = app.overview()
    assert result["telemetry_source"]["status"] == "RECENT"
    assert result["channels"][0]["freshness"] == "STALE"
    assert result["channels"][0]["quote_age_ms"] == 10450
    app.upload_calendar(calendar(start="20261206T083000"))
    events = app.overview()["calendar_events"]
    assert events["total"] == events["shown"] == 1
    assert events["events"][0]["release"] == "Employment Situation"
    assert events["events"][0]["scheduled_at"].startswith("2026-12-06T13:30:00")


@pytest.mark.parametrize("include_case", [True, False])
def test_lesson_eligibility_requires_visible_evidence(tmp_path, include_case):
    from fx_talanta.domain.models import Lesson, Record

    snapshot = demo()
    case = snapshot.records[2]
    lesson = Record(
        account=snapshot.account,
        recorded_at=AT,
        correlation_id=uuid4(),
        body=Lesson(
            hypothesis="fixture",
            status="QUALIFIED",
            supporting_cases=(case.record_id,),
            sample_size=1,
            uncertainty="fixture",
            activated_at=AT,
        ),
    )
    snapshot = snapshot.model_copy(
        update={"records": (case, lesson) if include_case else (lesson,)}
    )
    app = Dashboard(snapshot, tmp_path, TOKEN, FakeClock(AT))
    try:
        row = next(r for r in app.overview()["records"] if r["kind"] == "lesson")
        # A QUALIFIED label cannot compensate for a missing supporting case.
        assert row["memory_eligible"] is include_case
    finally:
        app.close()
