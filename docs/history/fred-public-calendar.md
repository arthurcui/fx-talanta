# FRED public-calendar time qualification

The isolated `fx_talanta.fred_calendar_html` collector tests the public FRED
calendar as a source of exact release times. It never changes broker state,
source health or execution permission. PR #10 remains on merge hold.

## Findings on November 2, 2026

Two bounded collection passes each retrieved five daily calendar pages using
normal verified Python HTTPS. Both matched every requested release against the
user-downloaded BLS ICS: JOLTS November 3 and December 1 at 15:00 UTC; jobs
November 6, CPI November 10 and PPI November 13 at 13:30 UTC. Each pass used a
fresh authenticated FRED API date snapshot. The second pass detected no schedule
change from the first.

The [first report](../evidence/fred-html-first-20261102.json) and
[repeat report](../evidence/fred-html-repeat-20261102.json) contain actual UTC
collection timestamps, normalized times, source hashes and comparison outcomes.
Reports retain no API key or raw HTML. The second report links to the first by
SHA-256 of its sorted-key JSON representation.

An initial strict parser rejected the page because it included both a results
table and an unrelated pagination table. The parser now selects only the
`table-standard-theme` table inside `release-dates-pager`. It does not treat
dropdown release names as event evidence. A regression test includes both tables.

**Outcome: automatic FRED time retrieval works for these five events in two
short passes. This is not sustained refresh qualification.** BLS direct refresh
still has the separately recorded HTTP 403 limitation. Its manually downloaded
file is a static comparison reference, not a continuously fresh second feed.
FRED HTML is also not a documented stable API or a guaranteed low-latency feed.
Successful comparison always retains `block_entries=true`,
`qualified_for_trading=false` and `execution_enabled=false`.

## Usage

From the isolated worktree, with its `src` directory on `PYTHONPATH`, first collect
a fresh date snapshot using the [FRED API adapter](fred-calendar-adapter.md):

```powershell
python -m fx_talanta.fred_calendar_html --fred .local/fred-snapshot-001.json --bls C:/SideProjects/fx-talanta/.local/bls.ics --output .local/fred-html-001.json
```

For a second observation, supply a fresh API snapshot, a new output path and
`--previous .local/fred-html-001.json`. Outputs cannot be overwritten. Exit zero
means this comparison passed, not that the calendar is approved for trading.
No scheduler or automatic retries are installed.

## Validation rules

- Require successful, complete four-release date inventory, agreement with the
  BLS dates within the requested window, and API evidence no older than 120 seconds.
  Future/unavailable inputs fail before fetching pages. At most ten daily pages
  may be fetched in one pass; each has a 15-second socket timeout and 1 MiB limit.
- Use fixed official HTTPS URLs with certificate and hostname verification,
  an identified User-Agent and no redirects, browser cookies or retries.
- Check exact requested date markers, one results table, one matching day header,
  the US Central timezone notice, exact release links and names, and explicit
  times. Missing/N/A times, duplicate rows, changed schema or unknown labels fail.
- Convert Central civil time using `America/Chicago`, rejecting ambiguous and
  nonexistent DST times. Compare UTC with the independently parsed Eastern BLS
  timestamps, requiring one confirmed matching event.
- Record all failures. No previous success is reused after a failed request.
  Data that ages out during collection fails. Any normalized schedule change
  from the previous report requires review and preserves both reports.

Tests simulate HTTP 403/429/500, stale/future inputs, schema drift, dropdown-only
pages, duplicate rows, DST and changed release times. These are fault simulations,
not evidence of a real reschedule or outage recovery. Remaining work is a
separately declared sustained freshness/recovery qualification and broader event
coverage before considering required calendar-source health. The two broker
24-hour tests remain separate and untouched.
