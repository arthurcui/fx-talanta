import json
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from fx_talanta.mt5_calendar import ClockPolicy, import_file, normalize, parse
from fx_talanta.provider_pipeline import Journal

NOW = datetime(2026, 11, 2, 12, tzinfo=UTC)
EPOCH = int(NOW.timestamp())
MISSING = "-9223372036854775808"


def policy(**changes):
    data = dict(
        version="test-calendar-clock/1",
        bridge_id="fixture_calendar",
        terminal_build=123,
        evidence_type="INDEPENDENT_CALENDAR_CHECK",
        evidence_hash="a" * 64,
        verified_at=NOW - timedelta(hours=2),
        segments=[
            dict(
                utc_from=NOW - timedelta(days=1),
                utc_until=NOW + timedelta(days=2),
                server_offset_seconds=7200,
            )
        ],
    )
    return ClockPolicy(**{**data, **changes})


def value(**changes):
    return dict(
        value_id="100",
        event_id="900",
        currency="USD",
        server_time=EPOCH + 7200 + 600,
        period_server_time=EPOCH - 86400,
        source_revision=0,
        time_mode="CALENDAR_TIMEMODE_DATETIME",
        importance="CALENDAR_IMPORTANCE_HIGH",
        unit="CALENDAR_UNIT_PERCENT",
        multiplier="CALENDAR_MULTIPLIER_NONE",
        digits=2,
        actual_raw=MISSING,
        forecast_raw="1234567",
        previous_raw="-1000000",
        revised_previous_raw=MISSING,
        **changes,
    )


def export(events=None, **changes):
    events = [value()] if events is None else events
    data = dict(
        schema_version=1,
        bridge_id="fixture_calendar",
        terminal_build=123,
        mode="FULL_SNAPSHOT",
        status="COMPLETE",
        error_code=0,
        server_from=EPOCH + 7200 - 3600,
        server_until=EPOCH + 7200 + 86400,
        started_utc=EPOCH,
        finished_utc=EPOCH + 1,
        elapsed_ms=1000,
        counts={c: sum(v["currency"] == c for v in events) for c in ("USD", "EUR", "JPY")},
        values=events,
        execution_enabled=False,
    )
    return json.dumps({**data, **changes}).encode()


def changed(**changes):
    return {**value(), **changes}


def test_exact_utc_decimal_and_missing_values():
    result = normalize(export(), policy(), NOW + timedelta(seconds=2))
    event = result["events"][0]
    assert event["scheduled_at"] == (NOW + timedelta(minutes=10)).isoformat()
    assert event["actual"] is None and event["revised_previous"] is None
    assert event["forecast"] == "1.234567" and event["previous"] == "-1"
    assert result["available_at"] == (NOW + timedelta(seconds=2)).isoformat()
    assert not result["qualified_for_trading"] and not result["execution_enabled"]
    assert result["raw_snapshot"]["values"][0]["period_server_time"] == EPOCH - 86400


@pytest.mark.parametrize(
    "update",
    [
        dict(status="FAILED", error_code=5401),
        dict(error_code=5400),
        dict(elapsed_ms=31000),
        dict(counts={"USD": 0, "EUR": 0, "JPY": 0}),
        dict(counts={"USD": 1}),
        dict(finished_utc=EPOCH - 1),
        dict(finished_utc=EPOCH + 20),
        dict(mode="INCREMENTAL"),
        dict(server_until=0),
    ],
)
def test_partial_error_clock_or_inventory_is_rejected(update):
    with pytest.raises(ValueError):
        parse(export(**update))


def test_duplicate_ids_keys_and_bad_integer_ranges_rejected():
    for raw in (
        export([value(), value()]),
        export().replace(b'"schema_version": 1', b'"schema_version": 1, "schema_version": 1'),
        export([changed(actual_raw=str(2**63))]),
        export([changed(value_id=str(2**64))]),
        export([changed(server_time=True)]),
    ):
        with pytest.raises(ValueError):
            parse(raw)


def test_ambiguous_and_nonexistent_dst_and_scope_rejected():
    transition = NOW
    autumn = policy(
        segments=[
            dict(
                utc_from=NOW - timedelta(days=1), utc_until=transition, server_offset_seconds=7200
            ),
            dict(
                utc_from=transition, utc_until=NOW + timedelta(days=1), server_offset_seconds=3600
            ),
        ]
    )
    with pytest.raises(ValueError, match="ambiguous"):
        autumn.decode(EPOCH + 5400)
    spring = policy(
        segments=[
            dict(
                utc_from=NOW - timedelta(days=1), utc_until=transition, server_offset_seconds=3600
            ),
            dict(
                utc_from=transition, utc_until=NOW + timedelta(days=1), server_offset_seconds=7200
            ),
        ]
    )
    with pytest.raises(ValueError, match="nonexistent"):
        spring.decode(EPOCH + 5400)
    assert spring.decode(EPOCH + 7200) == NOW
    with pytest.raises(ValueError):
        policy().decode(EPOCH + 86400 * 10)


def test_unknown_times_never_become_midnight_events_and_empty_is_not_coverage():
    result = normalize(
        export([changed(time_mode="CALENDAR_TIMEMODE_DATE")]), policy(), NOW + timedelta(seconds=2)
    )
    assert not result["events"] and result["uncertain_time_ids"] == ["100"]
    result = normalize(export([]), policy(), NOW + timedelta(seconds=2))
    assert not result["qualified_for_trading"] and not result["events"]


@pytest.mark.parametrize(
    "mapping",
    [
        policy(terminal_build=124),
        policy(bridge_id="other"),
        policy(verified_at=NOW + timedelta(seconds=1)),
        policy(evidence_type="SYNTHETIC"),
    ],
)
def test_mapping_identity_and_verification_required(mapping):
    with pytest.raises(ValueError):
        normalize(export(), mapping, NOW + timedelta(seconds=2))


def test_reimport_keeps_export_age_and_revisions_are_point_in_time(tmp_path):
    with closing(Journal(tmp_path / "feeds.sqlite", create=True)) as journal:
        first = NOW + timedelta(seconds=2)
        import_file(journal, export(), policy(), first)
        before = journal.evaluate("EURUSD", first)
        assert before.event_blackout and not before.calendar_ok
        old = import_file(journal, export(), policy(), NOW + timedelta(seconds=300))
        assert not old["transport_fresh"]
        assert len(journal.inputs(NOW + timedelta(seconds=300)).calendar) == 1
        revised = export(
            [changed(server_time=EPOCH + 7200 + 7200)],
            started_utc=EPOCH + 301,
            finished_utc=EPOCH + 302,
        )
        import_file(journal, revised, policy(), NOW + timedelta(seconds=303))
        after = journal.evaluate("EURUSD", NOW + timedelta(seconds=303))
        assert not after.event_blackout and not after.calendar_ok
        assert journal.evaluate("EURUSD", first) == before
        assert len(journal.inputs(NOW + timedelta(seconds=303)).calendar) == 2
        with pytest.raises(ValueError, match="failure preserved"):
            import_file(journal, export(), policy(), NOW + timedelta(seconds=304))


def test_regression_new_clock_or_partial_import_is_atomic_and_durable(tmp_path):
    with closing(Journal(tmp_path / "feeds.sqlite", create=True)) as journal:
        import_file(
            journal, export([changed(source_revision=2)]), policy(), NOW + timedelta(seconds=2)
        )
        for index, (raw, mapping) in enumerate(
            [
                (export(error_code=5400), policy()),
                (
                    export(
                        [changed(source_revision=1)],
                        started_utc=EPOCH + 10,
                        finished_utc=EPOCH + 11,
                    ),
                    policy(),
                ),
                (
                    export(started_utc=EPOCH + 20, finished_utc=EPOCH + 21),
                    policy(version="new-policy"),
                ),
            ]
        ):
            with pytest.raises(ValueError):
                import_file(journal, raw, mapping, NOW + timedelta(seconds=30 + index))
        assert (
            journal.conn.execute("SELECT count(*) FROM outcomes WHERE status='FAILED'").fetchone()[
                0
            ]
            == 3
        )
        assert len(journal.inputs(NOW + timedelta(seconds=35)).calendar) == 1


def test_exporter_has_no_trade_network_or_dll_capabilities():
    source = (Path(__file__).resolve().parents[1] / "bridges/mt5/CalendarExport.mq5").read_text()
    for forbidden in (
        "OrderSend(",
        "OrderSendAsync(",
        "CTrade",
        "#import",
        "WebRequest(",
        "FILE_COMMON",
        "FILE_REWRITE",
    ):
        assert forbidden not in source
    assert "CalendarValueHistory" in source and "ACCOUNT_TRADE_MODE_DEMO" in source
