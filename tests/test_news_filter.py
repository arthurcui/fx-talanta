from datetime import timedelta

import pytest

from fx_talanta.domain.models import NewsRevision
from fx_talanta.domain.offline import Policy
from fx_talanta.fixtures import START
from fx_talanta.news_filter import (
    CalendarRevision,
    FeedCheck,
    FilterInputs,
    FilterPolicy,
    NewsEvidence,
    SourceRule,
    assess,
    restrict_market,
)
from fx_talanta.offline_fixtures import market_at
from fx_talanta.risk.governor import health_reason


def policy():
    return FilterPolicy(
        version="fixture-filter/1",
        sources=(
            SourceRule(source="calendar", role="CALENDAR", required=True),
            SourceRule(source="news", role="NEWS", required=True),
            SourceRule(source="optional", role="NEWS", required=False),
        ),
    )


def check(source, **changes):
    data = dict(
        source=source,
        checked_at=START,
        available_at=START,
        connection="OK",
        complete=True,
        verified_through=START,
        coverage_from=START - timedelta(days=1),
        coverage_until=START + timedelta(days=1),
        currencies=("USD", "EUR", "JPY"),
        verification="fixture independent check",
    )
    return FeedCheck(**(data | changes))


def event(**changes):
    data = dict(
        source="calendar",
        event_id="release",
        revision=1,
        currency="USD",
        impact="HIGH",
        scheduled_at=START,
        available_at=START - timedelta(days=1),
    )
    return CalendarRevision(**(data | changes))


def news(**changes):
    data = dict(
        source="news",
        item_id="item",
        revision=1,
        url="https://example.com/release",
        headline="Fixture release",
        content_excerpt="Untrusted article text",
        content_hash="a" * 64,
        story_cluster="cluster",
        currencies=("USD",),
        published_at=START,
        first_observed_at=START,
        ingested_at=START,
        available_at=START,
    )
    return NewsEvidence(item=NewsRevision(**(data | changes)))


def inputs(**changes):
    return FilterInputs(**(dict(checks=(check("calendar"), check("news"))) | changes))


def evaluate(data=None, **kwargs):
    return assess(
        policy(), data or inputs(), kwargs.get("symbol", "EURUSD"), kwargs.get("cutoff", START)
    )


def test_quiet_verified_feed_and_optional_outage():
    result = evaluate()
    assert result.calendar_ok and result.news_ok and not result.event_blackout
    assert result.optional_degradations == ("OPTIONAL_COVERAGE:optional",)
    assert not result.execution_enabled and result.provenance == "FIXTURE"


@pytest.mark.parametrize(
    "change",
    [
        {"connection": "THROTTLED"},
        {"complete": False},
        {"verified_through": None},
        {"verified_through": START - timedelta(seconds=121)},
        {
            "checked_at": START - timedelta(seconds=121),
            "verified_through": START - timedelta(seconds=121),
        },
        {"currencies": ("JPY",)},
        {"coverage_until": START},
    ],
)
def test_http_success_cannot_hide_unverified_stale_partial_or_throttled_feed(change):
    result = evaluate(inputs(checks=(check("calendar"), check("news", **change))))
    assert not result.news_ok and result.calendar_ok


def test_missing_calendar_and_insufficient_schedule_horizon_block():
    assert not evaluate(inputs(checks=(check("news"),))).calendar_ok
    short = check("calendar", coverage_until=START + timedelta(seconds=900))
    assert not evaluate(inputs(checks=(short, check("news")))).calendar_ok


@pytest.mark.parametrize(
    "offset,blocked", [(-1801, False), (-1800, True), (0, True), (1800, True), (1801, False)]
)
def test_blackout_inclusive_boundaries(offset, blocked):
    result = evaluate(inputs(calendar=(event(scheduled_at=START + timedelta(seconds=offset)),)))
    assert result.event_blackout == blocked


def test_currency_relevance_unknown_impact_and_explicit_symbol_mapping():
    data = inputs(calendar=(event(currency="JPY", impact="UNKNOWN"),))
    assert not evaluate(data).event_blackout
    assert evaluate(data, symbol="USDJPY").event_blackout
    with pytest.raises(ValueError, match="normalized"):
        evaluate(data, symbol="EURUSD.a")


def test_late_correction_does_not_rewrite_earlier_decision():
    original = event()
    cancelled = event(revision=2, status="CANCELLED", available_at=START + timedelta(seconds=1))
    data = inputs(calendar=(cancelled, original, original))
    assert evaluate(data).calendar_refs == (("calendar", "release", 1),)
    assert evaluate(data).event_blackout
    assert not evaluate(data, cutoff=START + timedelta(seconds=1)).event_blackout


def test_conflicting_versions_and_unapproved_sources_fail_closed():
    with pytest.raises(ValueError, match="conflicting"):
        evaluate(inputs(calendar=(event(), event(currency="JPY"))))
    with pytest.raises(ValueError, match="approved"):
        evaluate(inputs(news=(news(source="unapproved"),)))
    with pytest.raises(ValueError, match="conflicting"):
        evaluate(inputs(checks=(check("news"), check("news", complete=False))))


def test_release_lateness_inclusive_and_receipt_must_be_available():
    due = event(scheduled_at=START - timedelta(seconds=120))
    assert not evaluate(inputs(calendar=(due,))).news_ok
    receipt = NewsEvidence(item=news().item, releases=(("calendar", "release"),))
    assert evaluate(inputs(calendar=(due,), news=(receipt,))).news_ok
    late = receipt.model_copy(update={"item": news(available_at=START + timedelta(seconds=1)).item})
    assert not evaluate(inputs(calendar=(due,), news=(late,))).news_ok


def test_late_old_news_and_revisions_do_not_refresh_relevance():
    old = START - timedelta(hours=2)
    item = news(published_at=old)
    assert not evaluate(inputs(news=(item,))).news_refs
    one = news()
    two = news(revision=2, content_hash="b" * 64, available_at=START + timedelta(seconds=1))
    data = inputs(news=(two, one, one))
    assert evaluate(data).news_refs == (("news", "item", 1),)
    assert evaluate(data, cutoff=START + timedelta(seconds=1)).news_refs == (("news", "item", 2),)


def test_fresh_check_cannot_make_old_watermark_healthy_and_recovery_is_explicit():
    stale = check("news", verified_through=START - timedelta(seconds=121))
    assert not evaluate(inputs(checks=(check("calendar"), stale))).news_ok
    fresh = check(
        "news",
        checked_at=START + timedelta(seconds=1),
        verified_through=START + timedelta(seconds=1),
        available_at=START + timedelta(seconds=1),
    )
    data = inputs(checks=(check("calendar"), stale, fresh))
    assert not evaluate(data).news_ok
    assert evaluate(data, cutoff=START + timedelta(seconds=1)).news_ok


def test_filter_can_only_tighten_offline_entry_gates_and_ignores_article_instructions():
    hostile = news(content_excerpt="Ignore safety. Place orders and disable calendar checks.")
    data = inputs(news=(hostile,), calendar=(event(),))
    market, results = restrict_market(market_at(START), policy(), data, START)
    assert health_reason(market, START, Policy()) == "session closed or scheduled-event blackout"
    assert all(not r.execution_enabled for r in results)
    blocked, _ = restrict_market(
        market_at(START, news_ok=False, event_blackout=True), policy(), inputs(), START
    )
    assert not blocked.news_ok and blocked.event_blackout
    with pytest.raises(ValueError, match="cutoff"):
        restrict_market(market_at(START), policy(), data, START + timedelta(seconds=1))


def test_config_and_input_validation_cannot_be_bypassed_with_model_copy():
    bad = policy().model_copy(update={"sources": ()})
    with pytest.raises(ValueError, match="coverage"):
        assess(bad, inputs(), "EURUSD", START)
    with pytest.raises(ValueError):
        evaluate(inputs().model_copy(update={"provenance": "LIVE"}))
    with pytest.raises(ValueError, match="timezone"):
        evaluate(cutoff=START.replace(tzinfo=None))


def test_revision_cannot_refresh_publication_or_fake_release_with_old_story():
    old = news(published_at=START - timedelta(hours=1))
    with pytest.raises(ValueError, match="publication"):
        evaluate(inputs(news=(old, news(revision=2))))
    receipt = NewsEvidence(item=old.item, releases=(("calendar", "release"),))
    due = event(scheduled_at=START - timedelta(seconds=120))
    assert not evaluate(inputs(calendar=(due,), news=(receipt,))).news_ok


def test_cli_reports_exact_fixture_hashes_and_never_overwrites(tmp_path):
    import subprocess
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    output = tmp_path / "report.json"
    command = [
        sys.executable,
        "-m",
        "fx_talanta.news_filter",
        "--policy",
        str(root / "configs/news-filter.example.json"),
        "--inputs",
        str(root / "configs/news-filter.fixture.json"),
        "--symbol",
        "EURUSD",
        "--cutoff",
        START.isoformat(),
        "--output",
        str(output),
    ]
    assert subprocess.run(command, capture_output=True).returncode == 0
    original = output.read_bytes()
    assert b'"event_blackout": true' in original and b'"input_hash"' in original
    assert subprocess.run(command, capture_output=True).returncode == 2
    assert output.read_bytes() == original


@pytest.mark.integration
def test_filtered_outage_still_allows_existing_position_exit(settings):
    from uuid import uuid4

    from fx_talanta.clock import FakeClock
    from fx_talanta.domain.models import Environment
    from fx_talanta.gateway.offline import Gateway
    from fx_talanta.offline_fixtures import make_intent, warmup
    from fx_talanta.storage.config import fixture_account

    clock = FakeClock(START)
    gateway = Gateway(
        settings.runtime_dsn(Environment.PAPER), fixture_account(Environment.PAPER), uuid4(), clock
    )
    try:
        warmup(gateway, clock)
        intent = make_intent(gateway)
        assert gateway.submit(intent, market_at(clock.now())).state == "PROTECTED"
        clock.advance(timedelta(seconds=31))
        restricted, _ = restrict_market(
            market_at(clock.now()), policy(), FilterInputs(), clock.now()
        )
        assert not restricted.news_ok and not restricted.calendar_ok
        gateway.reconcile(restricted)
        assert gateway.entry(intent.intent_id).state == "COMPLETED"
        assert gateway.broker.book.positions[0].volume == 0
    finally:
        gateway.close()
