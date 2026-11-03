# Required FX provider qualification

Status: implementation and bounded collection verified; **required coverage and
ongoing release delivery are not yet qualified**. This document supersedes the
older provider notes' PR statuses and proposed MT5-calendar route. PRs #8, #10,
#11 and #12 have merged. The manual BLS workflow remains the accepted development
calendar; no MT5 calendar collector or automatic BLS ICS downloader is restored.

## Scope and evidence

[The versioned inventory](provider-inventory.json) makes each USD/EUR/JPY release
family and its remaining gap explicit. A source URL is a candidate, not a passing
coverage result. Initial scope includes policy decisions/minutes, inflation,
employment, growth, activity, official speeches and unscheduled announcements.
Broader geopolitical/private-sector news and MOF intervention coverage remain
unresolved. There is no silent reduction of the existing required-news gate.

The bounded native preflight on November 3 retrieved and parsed eight feeds:
Fed policy (15 items), ECB announcements (15), BOJ updates (44), BLS jobs/CPI/PPI/
JOLTS (12 each) and Eurostat releases (11). Metadata and content hashes are retained;
article text/headlines are not archived. These are initial backfill counts, never
prospective latency evidence. The original three feeds and new statistical feeds
remain optional shadow inputs; execution stays disabled.
See the [sanitized actual preflight](evidence/required-providers-preflight-20261103.json).

- [BLS's published RSS directory](https://www.bls.gov/feed/) links the four feeds.
  These RSS requests succeeded even though earlier direct ICS requests failed.
  This does not certify automatic ICS refresh or revisions to the manual file.
- [Eurostat's RSS directory](https://ec.europa.eu/eurostat/en/web/rss/) links a release
  Atom feed. The separate catalogue feed's twice-daily dataset updates are not
  substituted for release announcements.
- [BEA's calendar formats](https://www.bea.gov/news/schedule/icalendar) link its
  keyless JSON. It contains offset-aware timestamps, duplicate dates and a
  `file_last_updated` metadata field. The probe reports duplicate counts and
  normalizes UTC without inventing a time for a date-only value. Next GDP and
  Personal Income and Outlays both normalize to November 25, 13:30 UTC in this
  capture. Their [official schedule](https://www.bea.gov/news/schedule) independently
  lists November 25, 08:30; repeated prospective revision checks remain pending.
- ECB, BOJ, Eurostat, Japanese CPI/GDP/labour schedule pages returned HTTP 200.
  HTTP success does not establish event extraction or current horizon completeness.
  HTML normalization for these calendars is still missing. Japanese CPI's schedule
  lists dates without exact times; BOJ mixes exact and approximate times. Unknown
  times must remain unknown rather than being inferred from a customary hour.

The first attempt used an environment without `truststore`; its worker failures
are retained as local setup failures, not counted as provider outages. A separate
provider-only environment resolved that dependency without changing broker Python.
The first native BEA parser rejected its metadata field; that failure was retained
before fixing and testing the schema handling.

## Bounded prospective delivery campaign

`python -m fx_talanta.provider_campaign run --directory <new-directory>
--inventory docs/provider-inventory.json --tls native` creates an exclusive,
24-hour plan before any collection. Install `requirements-provider-probe.txt`
in the separate provider environment for native TLS. Eight feeds are polled every
300 seconds, at most 288 scheduled attempts per source (2,304 total), with a
20-second child-process watchdog per fetch. There are no immediate retries or
catch-up bursts. Every source attempt/outcome is committed to an isolated SQLite
journal; neither account PostgreSQL database is used. No API key is needed.

The plan, source set and inventory hash are pinned in the append-only journal.
Existing campaign directories cannot be reused. Changing a plan invalidates its
report. A stopped/failed process does not restart or move the original deadline.
Clock discontinuities over one second fail the run; the collector never adjusts
the host clock. Both broker campaign checkouts stay frozen and untouched.

The inventory also pins six upcoming BLS release instances from the user's
already-imported ICS and its original hash. JOLTS is scheduled for November 3 at
15:00 UTC, inside this first window. Exact source/archive-URL matching records
schedule-to-first-receipt delay separately from the feed's own publication time,
and reports NOT_DUE, AWAITING_RECEIPT, ON_TIME, LATE, MISSING or EARLY_UNVERIFIED.
The expected archive URLs are matching patterns, not evidence that unpublished
releases already exist. Importing the reference for this test does not renew the
manual review deadline. A missing match cannot become a successful coverage claim.

Predeclared transport gates: full 86,400-second elapsed window, at least 99% of
scheduled polls successful per source, and no success gap exceeding 900 seconds.
Missing slots count against the fixed denominator. The first attempt owns a slot,
so a duplicate success cannot repair its failure. Initial/trailing gaps count.
Late outcomes beyond the deadline do not improve availability. A complete window
does not itself mean the gates passed.

Delivery reporting excludes the initial backfill and separates later revisions.
For new first-version items published after the initial successful fetch it reports
publication-to-first-receipt p50/p95/max. The preliminary sampled-delivery gate also
requires at least one such item and a maximum of 360 seconds. No new item means
insufficient delivery evidence, not a fresh or failed publisher. These measurements
are item ages at first receipt; publisher clock granularity and independent release
matching still matter. A future revision cannot rewrite an earlier decision.

This first 24-hour campaign is a bounded availability/delivery observation, **not
full provider acceptance**. It cannot observe monthly releases that occur later.
Required-category coverage always remains false in this tool until a separate
reviewed qualification path supplies independent expected-release matching,
omissions, timing, revision/recovery and intended-use evidence. The existing
`JournalGate` remains fail-closed. No synthetic success promotes a provider.

## Closing the remaining gaps

1. Normalize and independently reconcile the official calendar sources against
   the declared families, including dates with unknown times and schedule revisions.
2. Match actual notices with independently recorded expected releases. At least
   one relevant release per selected category must be witnessed prospectively;
   quiet hours and historical backfill cannot prove delivery latency or omissions.
3. Record publisher failures, replay/empty responses, throttling and recovery;
   validate equivalent Windows/Linux semantics and the retained-field/use scope.
4. Resolve explicitly uncovered news categories before required-input promotion.
   Free access remains first choice; no subscription is purchased or message sent.

Use `python -m fx_talanta.provider_campaign status --directory <directory>` to
rebuild the report from journal rows. The command does not prove process liveness;
check the host process and last status timestamp separately. Final sanitized
evidence is added after the real deadline, without rewriting failed attempts.
