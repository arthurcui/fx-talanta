# FRED calendar adapter (qualification only)

The isolated `fx_talanta.fred_calendar` adapter retrieves dates for Employment
Situation (50), CPI (10), PPI (46), and JOLTS (192). It has no broker, database,
order or observer integration. PR #10 remains on merge hold.

## Run locally

Use the isolated checkout's `src` on `PYTHONPATH`, with the project's Python
environment. Put `FRED_API_KEY` in a private, ignored env file. Never pass the key
on the command line. For example, from the isolated checkout in PowerShell:

```powershell
$env:PYTHONPATH = Join-Path (Get-Location).Path 'src'
python -m fx_talanta.fred_calendar --env-file C:/SideProjects/fx-talanta/.local/fred.env --start 2026-11-02 --end 2026-12-02 --output .local/fred-snapshot-001.json
```

Use a new output filename each time. `--previous PATH` links the next snapshot
to the previous snapshot's SHA-256. Every collection retains its actual UTC
availability, requested window, normalized dates and response hashes. Old
snapshots are never overwritten; they preserve what was observed at that time.
Date changes are not silently mapped onto an old release instance or treated as
a cancellation: FRED dates do not identify the underlying statistical period.
Retain the complete snapshot chain for later comparison.

Requests use standard verified HTTPS, no redirects, 15-second socket timeouts,
1 MiB response limits, at most ten pages per release and a maximum 62-day window.
Future releases without data are explicitly requested. All pages must agree on
counts and offsets; duplicates, missing pages, wrong IDs or out-of-window dates
fail the entire collection. There are no automatic retries, including on 429.
HTTP errors are sanitized; URLs containing the API key and response bodies are
never logged. Exit 0 means collection succeeded, **not permission to trade**.

## Time verification and restrictions

The [official API](https://fred.stlouisfed.org/docs/api/fred/release_dates.html)
provides dates, not intraday times. No default 08:30 time is inferred.
Optional `--time-evidence PATH` accepts a JSON array matching `TimeEvidence`:
release ID, date, local `HH:MM`, `America/New_York` or `America/Chicago`, UTC
`available_at`/`valid_until`, official BLS and FRED schedule URLs and SHA-256
hashes of both checked source documents. An operator must actually compare the
source rows before creating this evidence; hashes and URLs alone do not prove
agreement. This version does not automatically parse or reconcile HTML.

Time evidence must match each exact release ID/date and be available and unexpired
at the assessment cutoff. Conflicting times, unknown times and missing release
inventory block entries conservatively across the requested window. A rescheduled
date cannot reuse time evidence from the old date. ZoneInfo handles DST; ambiguous
or nonexistent civil times are rejected. A verified event blocks inclusively for
30 minutes before and after release.

`restrictions()` is an additional veto, not the existing fixture filter's health
input. It rejects failed, future/unavailable or stale snapshots (120 seconds by
default), and insufficient date windows. Even when it returns `block_entries=false`,
`calendar_coverage_complete` and `execution_enabled` remain false. Four USD release
types do not cover all economic events, EUR/JPY or broader news. No live data is
relabeled as fixture input and no current trading/observation flow is changed.

## Actual authenticated probe — November 2, 2026

The adapter successfully retrieved all four releases in four requests, with five
dates in the November 2–December 2 window: jobs November 6, CPI November 10,
PPI November 13, and JOLTS November 3 and December 1.
The [sanitized snapshot](evidence/fred-adapter-20261102.json) contains response
hashes and actual timestamps, never credentials. Intraday time evidence is still
incomplete, so this is successful collection, **not trading qualification**.

Tests cover complete pagination, count changes, duplicates, malformed responses,
HTTP 403/429/500 redaction, DST, unknown/conflicting/stale/future time evidence,
rescheduling, blackout boundaries and immutable output. Broker qualification
results remain independent. Both active 24-hour runs were left untouched.
