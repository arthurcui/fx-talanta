# Calendar and news filtering

This increment implements deterministic, fixture-based entry restrictions while
the independent CMC and FOREX.com observation runs continue. It has no network,
broker, credential, model, order or database access. It does not qualify a real
calendar/news provider or complete M1 ingestion. Inputs and reports are explicitly
labelled FIXTURE; execution authority is always false.

## Policy and decisions

`FilterPolicy` declares approved source IDs, their calendar/news role, required or
optional status, currency coverage and freshness limits. Required sources must
cover USD, EUR and JPY in both roles. Missing required coverage blocks entries;
an optional failure is recorded without silently substituting another source.

The default blackout is **30 minutes before through 30 minutes after** an affected
currency's high-impact event, inclusive at both boundaries, as specified in the
architecture. Unknown impact is treated conservatively like high impact. EURUSD
uses EUR/USD events; USDJPY uses USD/JPY events. Broker suffixes require explicit
normalization by a future adapter; the filter does not guess them.

Fixture defaults use 120-second check/watermark freshness, a 120-second expected
release lateness tolerance and a one-hour publication-based news relevance window.
These timing values require provider-specific qualification before production use.
Policy version and complete policy/input hashes are included in each report.

Calendar and news revisions are selected using availability at the decision cutoff.
Later cancellations, reschedules or corrections cannot rewrite an earlier result.
Identical duplicates collapse; conflicting immutable versions are rejected. Exact
source/item/revision references remain in the assessment. A revised story cannot
reset its original publication time to regain relevance. Article text is never
executed or interpreted as policy, account selection or instructions.

## Coverage and release evidence

A successful connection alone is insufficient. A source needs a fresh check,
fresh independently verified coverage watermark, complete pagination/coverage,
the relevant currencies and a valid coverage interval. Calendar coverage must
include the full blackout look-back/look-ahead window. Future/unavailable checks
are excluded; stale, missing, unknown, failed or throttled checks cannot pass.

An empty feed may be healthy when coverage is explicitly verified. Replayed old
watermarks cannot become healthy just because another request succeeded. The
fixture recovery rule is one new complete, verified check; live recovery policy
must be qualified independently. No automatic provider failover is implemented.

High/unknown-impact scheduled releases from required calendar sources block news
health once their lateness threshold is reached unless an available release from
a healthy approved news source links to that event. The release must concern the
event currency and have a publication time at or after the scheduled event. An
unrelated old article does not satisfy the expectation. Retain outstanding release
expectations until explicitly resolved; omitting them from a rolling input window
would make that window incomplete. Corrections and cancellations remain versioned.

Provider adapters must establish these facts independently. A `complete` flag,
watermark or verification description supplied by an article or model is not a
trusted attestation. This fixture implementation has no real-provider trust boundary.

## Reproduce and retain an assessment

From a checkout containing this increment:

```powershell
.venv\Scripts\python -m fx_talanta.news_filter --policy configs/news-filter.example.json --inputs configs/news-filter.fixture.json --symbol EURUSD --cutoff 2026-01-05T12:00:00Z --output .local/news-filter-report.json
```

Create the output directory first. The example is historical synthetic evidence,
not current market news. The command creates a new report exclusively and refuses
to overwrite an existing report. Keep the exact policy and input snapshots with
it for reproduction. Omit `--output` to print JSON. Exit zero means a valid
assessment, not permission to enter a trade; inspect the restrictions. Invalid
inputs or an inaccessible/existing output path return exit code 2. Input files
are bounded to 8 MiB and collection arrays to 10,000 items.

The reusable `assess` API returns per-pair restrictions and evidence references.
`restrict_market` applies them to an existing offline `Market` at the same cutoff.
It can only tighten existing calendar/news/blackout flags. Because the simulator
currently has global flags, one affected instrument blocks new entries across
that snapshot. Protective management and exits continue through the existing
gateway; the integration test verifies an existing position closes despite a
complete required-feed outage. This is an explicit adapter, not an installed
collector or an automatic hook into either broker observer.

## Remaining M1 work

Qualify calendar and news/search sources for coverage, original attribution,
timestamps/revisions, retention rights, rate limits and outage behavior. Then add
bounded read-only collection, immutable storage of every attempt (including empty
responses and errors), independent coverage verification, unresolved-release
tracking, restart recovery and provider-specific freshness/recovery policies.
Bind that evidence to the trusted entry gate before any connected trading. No
live-provider access or broader news sentiment interpretation is claimed here.
