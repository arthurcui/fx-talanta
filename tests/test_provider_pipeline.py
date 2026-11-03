import json
import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from fx_talanta.clock import FakeClock
from fx_talanta.domain.models import Environment
from fx_talanta.gateway.offline import Gateway
from fx_talanta.offline_fixtures import make_intent, market_at, warmup
from fx_talanta.provider_pipeline import Journal, JournalGate, collect_once, parse_news
from fx_talanta.storage.config import fixture_account

NOW = datetime(2026, 11, 2, 12, tzinfo=UTC)


def rss(title="first", stamp="Mon, 02 Nov 2026 11:00:00 GMT"):
    return f"<rss><channel><item><guid>one</guid><link>https://www.federalreserve.gov/new.htm</link><title>{title}</title><pubDate>{stamp}</pubDate></item></channel></rss>".encode()


@pytest.mark.parametrize(
    "source,host", [("bls_jolts", "www.bls.gov"), ("eurostat", "ec.europa.eu")]
)
def test_new_statistical_feeds_retain_news_provenance_and_fail_closed(tmp_path, source, host):
    raw = (
        '<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>release-one</id>'
        f'<link href="https://{host}/release"/><title>private fixture title</title>'
        "<published>2026-11-02T12:00:00+01:00</published></entry></feed>"
    ).encode()
    rows = parse_news(source, raw, NOW)
    with closing(Journal(tmp_path / "feeds.sqlite", create=True)) as journal:
        attempt = journal.begin(source, NOW)
        journal.finish(attempt, {"status": "OK", "payload": rows}, NOW)
        inputs = journal.inputs(NOW)
        assert len(inputs.news) == 1
        assert inputs.news[0].item.published_at.hour == 11
        assert "private fixture title" not in inputs.model_dump_json()
        result = journal.evaluate("EURUSD", NOW)
        assert not result.execution_enabled and not result.news_ok


def ingest(journal, at, raw=None):
    attempt = journal.begin("fed", at)
    rows = parse_news("fed", raw or rss(), at)
    journal.finish(attempt, {"status": "OK", "payload": rows}, at)


def test_publication_evidence_does_not_freshen_or_revise_items(tmp_path):
    evidence = []
    plain = parse_news("fed", rss(), NOW)
    captured = parse_news("fed", rss(), NOW, timestamp_evidence=evidence)
    assert plain == captured
    assert evidence == [
        {
            "item_id": plain[0]["item_id"],
            "field": "pubDate",
            "original": "Mon, 02 Nov 2026 11:00:00 GMT",
            "normalized_utc": "2026-11-02T11:00:00+00:00",
        }
    ]
    with closing(Journal(tmp_path / "timestamps.sqlite", create=True)) as journal:
        for offset in (0, 1):
            at = NOW + timedelta(seconds=offset)
            attempt = journal.begin("fed", at)
            journal.finish(
                attempt,
                {
                    "status": "OK",
                    "payload": captured,
                    "receipt_evidence": {
                        "publication_timestamps": evidence,
                        "received_at": at.isoformat(),
                    },
                },
                at,
            )
        assert journal.conn.execute("SELECT count(*) FROM revisions").fetchone()[0] == 1
        outcomes = journal.conn.execute("SELECT payload FROM outcomes").fetchall()
        assert all(
            json.loads(row[0])["receipt_evidence"]["publication_timestamps"] == evidence
            for row in outcomes
        )


def test_restart_revisions_availability_and_metadata_only(tmp_path):
    path = tmp_path / "feeds.sqlite"
    with closing(Journal(path, create=True)) as journal:
        ingest(journal, NOW)
        ingest(journal, NOW + timedelta(seconds=1))
        assert len(journal.inputs(NOW + timedelta(seconds=1)).news) == 1
    with closing(Journal(path)) as journal:
        ingest(journal, NOW + timedelta(seconds=2), rss("revised"))
        old = journal.inputs(NOW)
        new = journal.inputs(NOW + timedelta(seconds=2))
        assert len(old.news) == 1 and len(new.news) == 2
        assert new.news[-1].item.revision == 2
        assert new.news[-1].item.first_observed_at == NOW
        assert new.news[-1].item.published_at == old.news[0].item.published_at
        assert "revised" not in new.model_dump_json()
        result = journal.evaluate("EURUSD", NOW + timedelta(seconds=2))
        assert result.provenance == "PROVIDER_SHADOW"
        assert not result.calendar_ok and not result.news_ok and not result.execution_enabled
        assert "PROVIDER_QUALIFICATION_PENDING" in result.reasons
        with pytest.raises(sqlite3.IntegrityError):
            journal.conn.execute("DELETE FROM revisions")
        journal.conn.rollback()


def test_pending_failure_recovery_and_replayed_content_do_not_claim_coverage(tmp_path):
    with closing(Journal(tmp_path / "feeds.sqlite", create=True)) as journal:
        ingest(journal, NOW)
        pending = journal.begin("fed", NOW + timedelta(seconds=1))
        assert journal.inputs(NOW + timedelta(seconds=1)).checks[-1].connection == "FAILED"
        journal.finish(
            pending, {"status": "THROTTLED", "error": "HTTP_429"}, NOW + timedelta(seconds=3)
        )
        assert journal.inputs(NOW + timedelta(seconds=2)).checks[-1].connection == "FAILED"
        assert journal.inputs(NOW + timedelta(seconds=3)).checks[-1].connection == "THROTTLED"
        ingest(journal, NOW + timedelta(seconds=4))
        check = journal.inputs(NOW + timedelta(seconds=4)).checks[-1]
        assert check.connection == "OK" and not check.complete and check.verified_through is None
        assert len(journal.inputs(NOW + timedelta(seconds=4)).news) == 1
        with pytest.raises(ValueError, match="rollback"):
            journal.begin("fed", NOW)


@pytest.mark.parametrize(
    "raw",
    [
        b"<!DOCTYPE x><rss/>",
        b"<html/>",
        rss(stamp="Mon, 02 Nov 2026 13:00:00 GMT"),
        rss().replace(b"https://www.federalreserve.gov", b"https://example.com"),
        rss().replace(
            b"</channel>", rss().split(b"<channel>")[1].split(b"</channel>")[0] + b"</channel>"
        ),
    ],
)
def test_untrusted_feed_rejected(raw):
    with pytest.raises((ValueError, TypeError)):
        parse_news("fed", raw, NOW)


def test_failed_collection_is_durable_and_sanitized(tmp_path):
    with closing(Journal(tmp_path / "feeds.sqlite", create=True)) as journal:

        def fail(*args, **kwargs):
            raise RuntimeError("secret API credential")

        assert collect_once(journal, ["fed"], fetcher=fail) == {"fed": "FAILED"}
        payload = journal.conn.execute("SELECT payload FROM outcomes").fetchone()[0]
        assert "secret" not in payload and json.loads(payload)["status"] == "FAILED"


def test_boj_http_attribution_is_preserved_but_never_fetched():
    raw = rss().replace(b"https://www.federalreserve.gov", b"http://www.boj.or.jp")
    item = parse_news("boj", raw, NOW)[0]
    assert item["original_url"] == "http://www.boj.or.jp/new.htm"
    assert item["url"] == "https://www.boj.or.jp/new.htm"


def test_calendar_omission_is_not_cancellation_and_replay_is_stable(tmp_path):
    from fx_talanta.bls_calendar import BlsEvent, BlsSnapshot

    with closing(Journal(tmp_path / "feeds.sqlite", create=True)) as journal:
        event = BlsEvent(
            uid="employment",
            sequence=1,
            release_id=50,
            scheduled_at=NOW + timedelta(minutes=10),
            status="CONFIRMED",
        )

        def save(at, events):
            snapshot = BlsSnapshot(
                source_hash="a" * 64, imported_at=at, provenance="MANUAL_FILE", events=events
            )
            attempt = journal.begin("bls", at)
            journal.finish(
                attempt, {"status": "OK", "payload": snapshot.model_dump(mode="json")}, at
            )

        save(NOW, (event,))
        before = journal.evaluate("EURUSD", NOW)
        assert before.event_blackout
        save(NOW + timedelta(seconds=1), ())
        assert journal.evaluate("EURUSD", NOW + timedelta(seconds=1)).event_blackout
        save(
            NOW + timedelta(seconds=2),
            (event.model_copy(update={"sequence": 2, "status": "CANCELLED"}),),
        )
        assert not journal.evaluate("EURUSD", NOW + timedelta(seconds=2)).event_blackout
        assert journal.evaluate("EURUSD", NOW) == before
        with pytest.raises(ValueError, match="regressed or conflicts"):
            save(NOW + timedelta(seconds=3), (event,))


def test_revision_conflict_rolls_back_all_items(tmp_path):
    with closing(Journal(tmp_path / "feeds.sqlite", create=True)) as journal:
        ingest(journal, NOW)
        with pytest.raises(ValueError, match="publication time changed"):
            ingest(journal, NOW + timedelta(seconds=1), rss(stamp="Mon, 02 Nov 2026 10:00:00 GMT"))
        assert len(journal.inputs(NOW + timedelta(seconds=1)).news) == 1


@pytest.mark.integration
def test_automatic_entry_gate_and_restart_cannot_bypass(settings, tmp_path):
    path = tmp_path / "feeds.sqlite"
    with closing(Journal(path, create=True)) as journal:
        ingest(journal, NOW)
    gate, clock, run = JournalGate(path), FakeClock(NOW), uuid4()
    args = (settings.runtime_dsn(Environment.PAPER), fixture_account(Environment.PAPER), run, clock)
    with closing(Gateway(*args, news_gate=gate)) as gateway:
        warmup(gateway, clock)
        entry = gateway.submit(make_intent(gateway), market_at(clock.now()))
        assert entry.state == "REJECTED" and not gateway.broker.book.positions
        with closing(Journal(path)) as journal:
            assert journal.conn.execute("SELECT count(*) FROM assessments").fetchone()[0] > 0
        # A missing source journal must still reject entries rather than disable the gate.
        path.rename(tmp_path / "preserved.sqlite")
        restricted = gateway._restrict_news(market_at(clock.now()), "EURUSD")
        assert not restricted.news_ok and not restricted.calendar_ok
    with pytest.raises(ValueError, match="cannot remove or change"):
        Gateway(*args)


@pytest.mark.integration
def test_gate_is_rechecked_before_send_and_does_not_stop_exits(settings, tmp_path, monkeypatch):
    path = tmp_path / "feeds.sqlite"
    Journal(path, create=True).close()
    gate, clock = JournalGate(path), FakeClock(NOW)
    calls = []

    def changing(market, symbol, cutoff):
        calls.append(cutoff)
        return market if len(calls) == 1 else market.model_copy(update={"news_ok": False})

    monkeypatch.setattr(gate, "restrict", changing)
    args = (
        settings.runtime_dsn(Environment.PAPER),
        fixture_account(Environment.PAPER),
        uuid4(),
        clock,
    )
    with closing(Gateway(*args, news_gate=gate)) as gateway:
        warmup(gateway, clock)
        result = gateway.submit(make_intent(gateway), market_at(clock.now()))
        assert result.state == "REJECTED" and len(calls) == 2
        assert not gateway.broker.book.positions
    # A synthetic healthy feed permits a fixture position; a later outage must
    # leave protective exits operational under the same persisted gate.
    monkeypatch.setattr(gate, "restrict", lambda market, *args: market)
    clock = FakeClock(NOW)
    args = (
        settings.runtime_dsn(Environment.PAPER),
        fixture_account(Environment.PAPER),
        uuid4(),
        clock,
    )
    with closing(Gateway(*args, news_gate=gate)) as gateway:
        warmup(gateway, clock)
        intent = make_intent(gateway)
        assert gateway.submit(intent, market_at(clock.now())).state == "PROTECTED"
        monkeypatch.undo()
        clock.advance(timedelta(seconds=31))
        restricted = gateway._restrict_news(market_at(clock.now()), "EURUSD")
        assert not restricted.news_ok
        gateway.reconcile(restricted)
        assert gateway.entry(intent.intent_id).state == "COMPLETED"
