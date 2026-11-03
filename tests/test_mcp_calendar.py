import io
import json
import sqlite3
import time
from contextlib import closing
from copy import deepcopy
from datetime import UTC, datetime, timedelta

import pytest

from fx_talanta import mcp_calendar as mcp
from fx_talanta.mcp_client import Client, McpError, credential, read_sse, strict_json
from fx_talanta.provider_pipeline import Journal, digest

NOW = datetime(2026, 11, 3, 12, tzinfo=UTC)
TERMINAL = {
    "build": 6295,
    "company": "fixture",
    "terminal_path": "/fixture",
    "data_path": "/fixture/data",
}


def plan():
    return mcp.Plan(
        endpoint="http://127.0.0.1:22346/mcp",
        terminal_identity_hash=mcp.terminal_identity(TERMINAL),
        clock={
            "version": "fixture/1",
            "bridge_id": "fixture",
            "terminal_build": 6295,
            "evidence_type": "INDEPENDENT_CALENDAR_CHECK",
            "evidence_hash": "a" * 64,
            "verified_at": NOW - timedelta(hours=1),
            "segments": [
                {
                    "utc_from": NOW - timedelta(days=1),
                    "utc_until": NOW + timedelta(days=2),
                    "server_offset_seconds": 7200,
                }
            ],
        },
        coverage_from=NOW - timedelta(hours=1),
        coverage_until=NOW + timedelta(days=1),
        anchors=[
            {
                "value_id": "100",
                "event_id": "900",
                "scheduled_utc": NOW + timedelta(minutes=10),
                "reference_hash": "b" * 64,
            }
        ],
    )


def event(identity="900", **updates):
    return {
        "id": identity,
        "change_id": "8",
        "name": "Release",
        "time_mode": mcp.TIME_EXACT,
        "importance": "High importance",
        "unit": "Percent",
        "multiplier": "None",
        "digits": 2,
        **updates,
    }


def value(**updates):
    return {
        "id": "100",
        "event_id": "900",
        "change_id": "9",
        "time": "2026-11-03T14:10:00",
        "time_unknown": False,
        "revision": 0,
        "reference_period_start": "2026-10-01T00:00:00",
        "actual_value": None,
        "forecast_value": 1.25,
        "prev_value": -0.2,
        "revised_prev_value": None,
        **updates,
    }


class Fake:
    def __init__(self, *, rows=None, delta=None, new_cursor="10", fail=None):
        self.rows = [value()] if rows is None else rows
        self.delta = [] if delta is None else delta
        self.new_cursor, self.fail = new_cursor, fail
        self.calls = []

    def start(self):
        pass

    def tool(self, name, args):
        self.calls.append((name, args))
        if name == self.fail:
            raise RuntimeError("private fixture credential")
        if name == "terminal_get_info":
            return {"terminal": TERMINAL}
        if name == "get_time_information":
            return {
                "utc_time": NOW.isoformat(),
                "trade_server_last_known_time": "2026-11-03T14:00:00",
            }
        if name == "economic_calendar_get_value_by_id":
            return {"value": value()}
        if name == "economic_calendar_list_events_by_currency":
            identity = {"USD": "900", "EUR": "901", "JPY": "902"}[args["currency_code"]]
            return {"count": 1, "events": [event(identity)]}
        if name == "economic_calendar_list_values":
            return {"count": len(self.rows), "truncated": False, "values": self.rows}
        if name == "economic_calendar_list_values_last":
            return {
                "input_change_id": args["change_id"],
                "database_change_id": self.new_cursor,
                "filtered_change_id": "8",
                "values": [] if args["change_id"] == "0" else self.delta,
                "count": 0 if args["change_id"] == "0" else len(self.delta),
            }
        raise AssertionError(name)


def capture(client=None, cursor=None):
    return mcp.snapshot(client or Fake(), plan(), cursor, now=lambda: NOW)


def save(journal, payload, at=NOW):
    attempt = journal.begin(mcp.SOURCE, at)
    journal.finish(attempt, {"status": "OK", "payload": payload}, at)
    return attempt


def test_snapshot_brackets_cursor_and_reconciles_mid_snapshot_revision():
    fake = Fake(delta=[value(change_id="11", forecast_value=1.5)], new_cursor="11")
    result = capture(fake)
    names = [n for n, _ in fake.calls]
    first = names.index("economic_calendar_list_values_last")
    assert fake.calls[first][1] == {"change_id": "0", "event_id": "900"}
    assert fake.calls[first + 2][1] == {"change_id": "11"}
    assert names[first : first + 3] == [
        "economic_calendar_list_values_last",
        "economic_calendar_list_values",
        "economic_calendar_list_values_last",
    ]
    row = result["events"][0]
    assert row["scheduled_at"] == (NOW + timedelta(minutes=10)).isoformat()
    assert row["forecast"] == "1.5" and row["previous"] == "-0.2"
    assert row["actual"] is None and row["reference_period_start"] == "2026-10-01T00:00:00"
    assert not result["execution_enabled"] and not result["qualified_for_trading"]


def test_replay_restart_and_revisions_preserve_first_availability(tmp_path):
    path = tmp_path / "calendar.sqlite"
    with closing(Journal(path, create=True)) as journal:
        save(journal, capture())
        original = journal.inputs(NOW)
        repeated = capture(cursor="10")
        save(journal, repeated, NOW + timedelta(seconds=1))
        assert journal.conn.execute("SELECT count(*) FROM revisions").fetchone()[0] == 1
        assert mcp.checkpoint(journal.conn)["database_cursor"] == "10"
        journal.begin(mcp.SOURCE, NOW + timedelta(seconds=2))  # process dies before commit
    with closing(Journal(path)) as journal:
        assert mcp.checkpoint(journal.conn)["database_cursor"] == "10"
        changed = capture(
            Fake(delta=[value(change_id="11", time="2026-11-03T14:20:00")], new_cursor="11"), "10"
        )
        save(journal, changed, NOW + timedelta(seconds=3))
        records = [
            json.loads(p)
            for (p,) in journal.conn.execute("SELECT payload FROM revisions ORDER BY revision")
        ]
        assert (
            len(records) == 2
            and records[0]["first_observed_at"]
            == records[1]["first_observed_at"]
            == NOW.isoformat()
        )
        assert journal.inputs(NOW) == original
        assert len({r.event_id for r in journal.inputs(NOW + timedelta(seconds=3)).calendar}) == 1


def test_cursor_and_values_rollback_together_on_commit_failure(tmp_path):
    with closing(Journal(tmp_path / "calendar.sqlite", create=True)) as journal:
        save(journal, capture())
        journal.conn.execute(
            "CREATE TRIGGER fixture_failure BEFORE INSERT ON outcomes "
            "BEGIN SELECT RAISE(ABORT,'injected commit failure'); END"
        )
        changed = capture(
            Fake(delta=[value(change_id="11", forecast_value=2)], new_cursor="11"), "10"
        )
        with pytest.raises(sqlite3.IntegrityError):
            save(journal, changed, NOW + timedelta(seconds=1))
        assert journal.conn.execute("SELECT count(*) FROM revisions").fetchone()[0] == 1
        assert mcp.checkpoint(journal.conn)["database_cursor"] == "10"
        journal.conn.execute("DROP TRIGGER fixture_failure")
        save(journal, changed, NOW + timedelta(seconds=2))
        assert journal.conn.execute("SELECT count(*) FROM revisions").fetchone()[0] == 2
        assert mcp.checkpoint(journal.conn)["database_cursor"] == "11"


def test_failure_is_durable_sanitized_and_does_not_advance_cursor(tmp_path):
    with closing(Journal(tmp_path / "calendar.sqlite", create=True)) as journal:
        save(journal, capture())

        def failed(*args):
            raise RuntimeError("private fixture credential")

        assert (
            mcp.collect(
                journal, "ignored", plan(), fetcher=failed, now=lambda: NOW + timedelta(seconds=1)
            )["status"]
            == "FAILED"
        )
        assert mcp.checkpoint(journal.conn)["database_cursor"] == "10"
        payload = journal.conn.execute(
            "SELECT payload FROM outcomes ORDER BY rowid DESC LIMIT 1"
        ).fetchone()[0]
        assert "private" not in payload
        check = next(
            c for c in journal.inputs(NOW + timedelta(seconds=1)).checks if c.source == mcp.SOURCE
        )
        assert check.connection == "FAILED" and not check.complete


@pytest.mark.parametrize(
    "field,changed", [("database_cursor", "9"), ("input_cursor", "8"), ("plan_hash", "c" * 64)]
)
def test_cursor_cas_rollback_and_plan_changes_rejected(tmp_path, field, changed):
    with closing(Journal(tmp_path / "calendar.sqlite", create=True)) as journal:
        save(journal, capture())
        candidate = capture(cursor="10")
        candidate[field] = changed
        with pytest.raises(ValueError):
            save(journal, candidate, NOW + timedelta(seconds=1))
        assert mcp.checkpoint(journal.conn)["database_cursor"] == "10"


def test_same_version_conflict_or_source_revision_regression_rolls_back(tmp_path):
    with closing(Journal(tmp_path / "calendar.sqlite", create=True)) as journal:
        save(journal, capture())
        candidate = capture(cursor="10")
        candidate["events"][0]["forecast"] = "2"
        with pytest.raises(ValueError, match="conflicts"):
            save(journal, candidate, NOW + timedelta(seconds=1))
        assert journal.conn.execute("SELECT count(*) FROM revisions").fetchone()[0] == 1


def test_unknown_times_and_omissions_never_erase_exact_blackout(tmp_path):
    with closing(Journal(tmp_path / "calendar.sqlite", create=True)) as journal:
        save(journal, capture())
        assert journal.evaluate("EURUSD", NOW).event_blackout
        uncertain = capture(
            Fake(rows=[value(change_id="11", time_unknown=True)], new_cursor="11"), "10"
        )
        assert uncertain["events"][0]["scheduled_at"] is None
        save(journal, uncertain, NOW + timedelta(seconds=1))
        save(journal, capture(Fake(rows=[], new_cursor="11"), "11"), NOW + timedelta(seconds=2))
        result = journal.evaluate("EURUSD", NOW + timedelta(seconds=2))
        assert result.event_blackout and not result.calendar_ok and not result.news_ok
        assert not result.execution_enabled


def test_boj_date_mode_overrides_false_time_unknown_flag():
    row = mcp.normalize(
        value(),
        {
            **event(time_mode="Source publishes the event day; exact time is specified later"),
            "currency": "JPY",
        },
        plan(),
    )
    assert row["scheduled_at"] is None and row["uncertainty"] == "PROVIDER_TIME_NOT_EXACT"


@pytest.mark.parametrize(
    "raw",
    [
        dict(time="2026-11-03T14:10:00Z"),
        dict(change_id="-1"),
        dict(revision=True),
        dict(actual_value=float("inf")),
    ],
)
def test_malformed_values_rejected(raw):
    with pytest.raises(ValueError):
        capture(Fake(rows=[value(**raw)]))


def test_changed_terminal_anchor_and_truncated_results_fail():
    class Broken(Fake):
        def __init__(self, target):
            super().__init__()
            self.target = target

        def tool(self, name, args):
            out = deepcopy(super().tool(name, args))
            if name == self.target:
                if name == "terminal_get_info":
                    out["terminal"]["build"] += 1
                elif name == "economic_calendar_get_value_by_id":
                    out["value"]["time"] = "2026-11-03T14:11:00"
                elif name == "get_time_information":
                    out["trade_server_last_known_time"] = "2026-11-03T13:00:00"
                else:
                    out["truncated"] = True
            return out

    for tool in (
        "terminal_get_info",
        "economic_calendar_get_value_by_id",
        "get_time_information",
        "economic_calendar_list_values",
    ):
        with pytest.raises(ValueError):
            capture(Broken(tool))


def test_out_of_window_reschedule_retains_identity_as_uncertain():
    f = Fake(rows=[], delta=[value(change_id="11", time="2026-12-03T14:10:00")], new_cursor="11")
    result = mcp.snapshot(f, plan(), "10", tracked_ids=["100"], now=lambda: NOW)
    assert result["events"][0]["scheduled_at"] is None
    assert result["events"][0]["value_id"] == "100"


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://example.com/mcp",
        "http://localhost:22346/mcp",
        "http://127.0.0.1:22346/mcp?token=x",
        "http://user:pass@127.0.0.1:22346/mcp",
    ],
)
def test_endpoint_restrictions(endpoint):
    raw = plan().model_dump(mode="json")
    raw["endpoint"] = endpoint
    with pytest.raises(ValueError):
        mcp.Plan.model_validate(raw)


def test_export_exact_endpoint_no_extra_headers_and_mutation_refused(tmp_path):
    path = tmp_path / "export.txt"
    endpoint = plan().endpoint
    path.write_text(
        "JSON:\n"
        + json.dumps(
            {
                "mcpServers": {
                    "terminal": {
                        "url": endpoint,
                        "headers": {"Authorization": "Bearer fixture-token", "X-Other": "ignored"},
                    }
                }
            }
        )
        + "\nTOML example follows"
    )
    assert credential(path, endpoint) == "Bearer fixture-token"
    client = Client(path, endpoint)
    with pytest.raises(McpError, match="READ_ONLY"):
        client.tool("trade_send_market_order", {})
    with pytest.raises(McpError):
        credential(path, "http://127.0.0.1:22347/mcp")


@pytest.mark.parametrize(
    "raw",
    [
        b'data: {"jsonrpc":"2.0","id":1,"result":{}}\n\n',
        b':keepalive\n\ndata: {\ndata: "jsonrpc":"2.0",\ndata: "id":1,\n'
        b'data: "result":{}\ndata: }\n\n',
        b'data: {"method":"notice"}\n\ndata: {"jsonrpc":"2.0","id":1,"result":{}}',
    ],
)
def test_multiline_sse_and_notifications(raw):
    assert read_sse(io.BytesIO(raw), 1, time.monotonic() + 1)["result"] == {}


def test_duplicate_json_and_expired_sse_are_rejected():
    with pytest.raises(ValueError):
        strict_json('{"id":1,"id":2}')
    with pytest.raises(ValueError):
        strict_json('{"value":NaN}')
    with pytest.raises(ValueError):
        strict_json('{"value":1e999}')
    with pytest.raises(McpError):
        read_sse(io.BytesIO(b""), 1, time.monotonic() - 1)


@pytest.mark.parametrize("kind", ["wrong_id", "boolean_id", "tool_error", "rpc_error", "timeout"])
def test_transport_failures_do_not_expose_server_messages(tmp_path, kind):
    from fx_talanta.mcp_client import NoRedirect

    path = tmp_path / "export.txt"
    path.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "terminal": {
                        "url": plan().endpoint,
                        "headers": {"Authorization": "Bearer fixture-token"},
                    }
                }
            }
        )
    )
    client = Client(path, plan().endpoint)

    class Response(io.BytesIO):
        status = 200
        headers = {"Content-Type": "application/json"}

    class Opener:
        def open(self, request, timeout):
            assert request.full_url == plan().endpoint and timeout <= 12
            if kind == "timeout":
                raise TimeoutError("private fixture credential")
            body = {"jsonrpc": "2.0", "id": 1, "result": {}}
            if kind == "wrong_id":
                body["id"] = 2
            if kind == "boolean_id":
                body["id"] = True
            if kind == "tool_error":
                body["result"] = {"isError": True, "content": "private fixture credential"}
            if kind == "rpc_error":
                body["error"] = {"message": "private fixture credential"}
            return Response(json.dumps(body).encode())

    client.opener = Opener()
    with pytest.raises(McpError) as error:
        client.rpc("tools/call", {"name": "get_time_information", "arguments": {}})
    assert "private" not in str(error.value) and "private" not in json.dumps(client.attempts)
    assert NoRedirect().redirect_request(None, None, 302, None, None, "https://example.com") is None


def test_native_revision_regression_and_clock_change_do_not_update_cursor(tmp_path):
    with closing(Journal(tmp_path / "calendar.sqlite", create=True)) as journal:
        save(journal, capture(Fake(rows=[value(revision=1)])))
        older = capture(Fake(rows=[value(revision=0, change_id="11")], new_cursor="11"), "10")
        with pytest.raises(ValueError, match="regressed"):
            save(journal, older, NOW + timedelta(seconds=1))
        assert mcp.checkpoint(journal.conn)["database_cursor"] == "10"


def test_existing_news_and_mcp_share_journal_without_false_coverage(tmp_path):
    from fx_talanta.provider_pipeline import parse_news

    with closing(Journal(tmp_path / "calendar.sqlite", create=True)) as journal:
        save(journal, capture())
        raw = (
            b"<rss><channel><item><guid>jolts</guid>"
            b"<link>https://www.bls.gov/news.release/example.htm</link>"
            b"<pubDate>Tue, 03 Nov 2026 11:00:00 GMT</pubDate></item></channel></rss>"
        )
        attempt = journal.begin("bls_jolts", NOW)
        journal.finish(attempt, {"status": "OK", "payload": parse_news("bls_jolts", raw, NOW)}, NOW)
        inputs = journal.inputs(NOW)
        assert len(inputs.calendar) == 1 and len(inputs.news) == 1
        assert {x.source for x in inputs.checks} == {mcp.SOURCE, "bls_jolts"}
        assert not journal.evaluate("EURUSD", NOW).calendar_ok
        assert not journal.evaluate("USDJPY", NOW).news_ok
        assert digest(plan().model_dump(mode="json")) == mcp.checkpoint(journal.conn)["plan_hash"]
