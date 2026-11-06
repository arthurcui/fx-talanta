import hashlib
import http.client
import json
import threading
from datetime import timedelta
from uuid import uuid4

import pytest
from test_bls_calendar import calendar

from fx_talanta.clock import FakeClock
from fx_talanta.dashboard.app import Dashboard
from fx_talanta.dashboard.demo import AT, demo
from fx_talanta.dashboard.import_records import convert
from fx_talanta.dashboard.models import Channel, Snapshot
from fx_talanta.dashboard.server import make_server

TOKEN = "dashboard-test-only-" + "x" * 40


def test_import_existing_history_preserves_record_hashes_and_unknown_channels():
    records = demo().records
    raw = json.dumps([r.model_dump(mode="json") for r in records]).encode()
    snapshot = convert(raw, "Recorded test")
    assert snapshot.records == records and snapshot.channels == ()
    assert snapshot.source == "RECORDED_SIMULATOR"
    with pytest.raises(ValueError):
        convert(b"[]", "Empty")
    with pytest.raises(ValueError):
        convert(b"{}", "Invalid")


@pytest.fixture
def app(tmp_path):
    result = Dashboard(demo(), tmp_path / "inspection", TOKEN, FakeClock(AT))
    yield result
    result.close()


def chat(**changes):
    return dict(
        request_id=str(uuid4()),
        question="Why is trading disabled?",
        record_id=None,
        language="en",
        **changes,
    )


def test_channels_do_not_conflate_connection_age_or_delay(app):
    source_hash = hashlib.sha256(app.snapshot.model_dump_json().encode()).hexdigest()
    ea, py, mcp = app.overview()["channels"]
    assert ea["freshness"] == "FRESH" and ea["quote_age_ms"] == 450
    assert ea["transport_delay_ms"] == 30 and not ea["entry_ready"]
    assert py["connection"] == "CONNECTED" and py["freshness"] == "STALE"
    assert mcp["quote_age_ms"] is None and mcp["telemetry_status"] == "UNKNOWN"
    app.clock.advance(timedelta(seconds=20))
    later = app.overview()["channels"][0]
    assert later["freshness"] == "STALE" and later["telemetry_status"] == "STALE"
    assert later["transport_delay_ms"] == 30
    assert hashlib.sha256(app.snapshot.model_dump_json().encode()).hexdigest() == source_hash


@pytest.mark.parametrize(
    "uncertainty,offset,expected",
    [
        (0, 2, "FRESH"),
        (1, 2, "STALE"),
        (101, 0.1, "CLOCK_UNVERIFIED"),
        (None, 0.1, "CLOCK_UNVERIFIED"),
        (0, -0.1, "CLOCK_UNVERIFIED"),
    ],
)
def test_clock_bound_and_exact_two_second_ceiling(uncertainty, offset, expected):
    c = Channel(
        name="EA", quote_at=AT - timedelta(seconds=offset), clock_uncertainty_ms=uncertainty
    )
    assert c.metrics(AT)["freshness"] == expected
    assert not c.metrics(AT)["entry_ready"]


def test_m4_citations_rationale_retry_and_no_commands(app):
    data = chat()
    data["record_id"] = str(app.snapshot.records[0].record_id)
    data["language"] = "zh"
    result = app.chat(data)
    assert (
        result["citations"][0]["sha256"]
        == hashlib.sha256(app.snapshot.records[0].model_dump_json().encode()).hexdigest()
    )
    assert "以下" in result["text"] and "incomplete news" in result["rationale"]
    assert result["rationale_label"] == "ORIGINAL_RECORDED_TEXT_UNTRUSTED_QUOTATION"
    assert app.chat(data) == result
    with pytest.raises(ValueError, match="conflict"):
        app.chat({**data, "question": "different request"})
    command = chat()
    command["question"] = "Buy EURUSD now"
    assert "does not" in app.chat(command)["text"]
    assert app.advisor.gateway is None and app.advisor._transport is None
    assert not result["execution_enabled"]


def test_snapshot_scope_unknown_record_and_session_expiry(app):
    data = demo().model_dump(mode="json")
    data["account"]["login"] = "another-account"
    with pytest.raises(ValueError):
        Snapshot.model_validate(data)
    data = chat()
    data["record_id"] = str(uuid4())
    with pytest.raises(ValueError):
        app.chat(data)
    with pytest.raises(PermissionError):
        app.authorize("wrong" * 10)
    app.clock.advance(timedelta(hours=8))
    with pytest.raises(PermissionError):
        app.authorize(TOKEN)


def test_calendar_upload_isolated_deduplicated_and_failure_preserves_evidence(app):
    raw = calendar(start="20261206T083000")
    first = app.upload_calendar(raw)
    assert not first["qualified_for_trading"]
    app.clock.advance(timedelta(days=8))
    again = app.upload_calendar(raw)
    assert again["source_hash"] == first["source_hash"]
    assert again["last_reviewed_at"] == first["last_reviewed_at"]
    assert "REVIEW_OVERDUE" in again["reasons"]
    with pytest.raises(ValueError):
        app.upload_calendar(b"not a calendar")
    saved = app.overview()["calendar"]
    assert saved["source_hash"] == first["source_hash"]
    assert "LAST_UPLOAD_FAILED_OR_INTERRUPTED" in saved["reasons"]


def test_inspection_receipts_survive_restart_and_bind_snapshot(tmp_path):
    state = tmp_path / "state"
    a = Dashboard(demo(), state, TOKEN, FakeClock(AT))
    data = chat()
    result = a.chat(data)
    a.close()
    b = Dashboard(demo(), state, TOKEN, FakeClock(AT))
    assert b.chat(data) == result
    b.close()
    with pytest.raises(ValueError, match="another snapshot"):
        Dashboard(demo().model_copy(update={"label": "different"}), state, TOKEN, FakeClock(AT))


def test_http_auth_origin_paths_body_limits_and_no_order_routes(app):
    server = make_server(app)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    def request(method, path, body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
        conn.request(method, path, body, headers or {})
        response = conn.getresponse()
        content = response.read()
        result = (response.status, dict(response.headers), content)
        conn.close()
        return result

    auth = {"Authorization": "Bearer " + TOKEN}
    try:
        assert request("GET", "/api/overview")[0] == 403
        for path in (
            "/api/report",
            "/api/incidents?q=EA",
            "/api/trace/" + str(app.snapshot.records[0].record_id),
        ):
            assert request("GET", path)[0] == 403
            assert request("GET", path, headers=auth)[0] == 200
        assert request("GET", "/api/incidents?before=no", headers=auth)[0] == 400
        assert request("GET", "/api/incidents?q=a&q=b", headers=auth)[0] == 400
        assert request("GET", "/api/trace/" + str(uuid4()), headers=auth)[0] == 400
        assert (
            request("GET", "/api/overview", headers={**auth, "Origin": "https://evil.example"})[0]
            == 403
        )
        assert request("GET", "/api/overview", headers={**auth, "Host": "evil.example"})[0] == 403
        status, headers, raw = request("GET", "/api/overview", headers=auth)
        assert status == 200 and not json.loads(raw)["execution_enabled"]
        assert "frame-ancestors 'none'" in headers["Content-Security-Policy"]
        assert request("POST", "/api/order", headers=auth)[0] == 404
        assert request("GET", "/../app.py")[0] == 404
        assert (
            request("POST", "/api/chat", "x" * 4097, {**auth, "Content-Type": "application/json"})[
                0
            ]
            == 413
        )
        assert (
            request(
                "POST",
                "/api/chat",
                json.dumps(chat()),
                {**auth, "Content-Type": "application/json"},
            )[0]
            == 200
        )
        assert TOKEN.encode() not in raw
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
