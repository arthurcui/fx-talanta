# Python ingestion with native MT5 MCP calendar

Python owns collection, normalization and the journal. The optional
`mt5_mcp_calendar` source reads CMC's native terminal MCP endpoint; existing
official HTTP/RSS adapters supply news. The manual BLS upload remains available.
No MQL5 exporter, terminal service, file importer or scheduled task is installed.
Native MCP still requires the selected MT5 terminal to be running and connected.

This is a **verified shadow adapter**, not a qualified production provider.
Neither successful collection nor a complete-looking event list enables entries.
The required calendar/news coverage gates remain false, as do trading permissions.
The five-second observer ceiling and two-second entry rule are unchanged.

## Actual November 3 verification

The [sanitized evidence](../evidence/native-mcp-calendar-20261103.json) records the
actual CMC adapter and a separate development SQLite journal:

| Check | Observed result |
| --- | --- |
| Independent time anchor | Saved BLS JOLTS schedule: November 3, 15:00 UTC. Native value: 17:00 server time. The checked offset was +7,200 seconds. |
| Catalogs | 248 USD, 278 EUR and 124 JPY event series. Catalog counts do not certify dated coverage. |
| Explicit collection window | November 3 00:00 through November 6 00:00 UTC, exclusive end. |
| Imported instances | 72 total: 31 USD, 32 EUR and 9 JPY. Ten retain uncertain times. |
| Restart/replay | Two successful CLI invocations in separate processes; the second resumed the committed cursor and added zero duplicate revisions. |
| Direct news in the same journal | Fed 15, ECB 15 and BOJ 42 metadata records; all three collection attempts succeeded. These are initial backfill. |
| Entry assessment | EUR/USD and USD/JPY remained blocked; calendar/news qualification and execution remain false. |

The first unfiltered zero-cursor call failed after approximately 12 seconds. Its
failed outcome and transport diagnostic remain in the journal; no values or
cursor were committed. Initialization now scopes the zero-cursor query to the
independently identified anchor and uses its **database-wide** cursor, never its
filtered cursor. Both subsequent full-window/delta reads succeeded. The terminal
reason for the original unfiltered failure remains unproven.

The first local preflight needed host access to reach the existing loopback
listener. A verification helper initially referenced the wrong news-model field;
it was corrected and rerun against the already committed journal without
recollecting or replacing evidence. Neither issue is counted as successful
collection. No broker campaign or provider campaign supplied these new records.

## Idempotency and failures

Calendar release-instance identity is `(source, native value ID)`. Native event ID
identifies the series, so separate releases are never collapsed by title. Native
value and event change IDs, source revision, uncertain-time flags, unit, multiplier
and numeric values remain explicit. Missing numbers remain null. An ambiguous or
unverified server timestamp is never converted into an invented UTC time.

The initial database cursor is read before the full snapshot; an unfiltered delta
then catches concurrent changes. Subsequent polls reread the bounded window and
the committed cursor's delta. This also detects changed event-series metadata.
Tracked reschedules outside the window remain recorded; unqualified times do not
erase an earlier exact blackout. Omission alone never means cancellation.

An attempt is durable before retrieval. Revisions and the successful outcome are
committed in one SQLite transaction, with a cursor comparison under the write
lock. That immutable outcome is the checkpoint. A failed commit cannot advance it.
Restart uses the last successful checkpoint; an interrupted attempt stays visible.
Repeated identical data adds no revision and does not refresh first-observed time.
Corrections append revisions; old assessments remain reproducible at their cutoff.

Different providers keep separate identities and provenance. Cross-source aliases
are not inferred from headlines or timestamps. The independently checked JOLTS
anchor corroborates one release; this adapter does not claim a complete canonical
mapping across BLS, FRED and MT5 or silently fail over between sources.

The transport permits six named read tools at a pinned loopback `/mcp` endpoint.
It follows no redirects and uses no HTTP proxy. Responses are bounded to 2 MiB,
socket waits to 12 seconds, and the whole poll to a 90-second child-process
watchdog. Multiline SSE messages are assembled before JSON parsing. Errors retain
fixed diagnostic codes, collection stage and request timing, without credentials
or raw server error text. No automatic retry is performed.

## Running a bounded development poll

Use a development checkout and journal separate from qualification campaigns.
Keep MT5's complete MCP Copy export in an ignored local file. A reviewed plan pins
the endpoint, terminal identity/build, USD/EUR/JPY, explicit UTC window, independently
checked clock intervals and at least one official-calendar anchor.

`fx_talanta.mcp_calendar.Plan` validates the plan. Its JSON fields are:

- `version`: `mcp-calendar-shadow/1`.
- `endpoint`: the copied terminal endpoint, restricted to
  `http://127.0.0.1:<port>/mcp`.
- `terminal_identity_hash`: `terminal_identity(terminal_get_info()['terminal'])`.
- `clock`: retained `ClockPolicy` fields `version`, `bridge_id` (a local alias),
  `terminal_build`, `evidence_type=INDEPENDENT_CALENDAR_CHECK`, `evidence_hash`,
  `verified_at`, and `segments` containing UTC bounds and verified offset seconds.
- `coverage_from`, `coverage_until`: aware UTC timestamps, at most seven days
  apart and within a single verified offset interval.
- `currencies`: exactly `['USD', 'EUR', 'JPY']`.
- `anchors`: native `value_id`, `event_id`, independently verified `scheduled_utc`
  and the official reference bytes' `reference_hash` for each anchor.
- `execution_enabled`: `false`.

The reference schedule must be checked independently before constructing the plan;
do not use an MT5 timestamp as its own reference. Current terminal UTC/server time
and anchor agreement are checked before every poll, then terminal time again after
collection. A changed terminal, build, clock mapping or plan fails closed. A new
plan requires a separate journal; future DST offsets are not inferred from this
same-day verification. The original verified development plan remains private.

The actual local verification used these commands from the isolated checkout:

```powershell
$env:PYTHONPATH = (Resolve-Path src).Path
python -m fx_talanta.mcp_calendar --mcp-export C:/SideProjects/fx-talanta/.local/mt5-mcp-export.txt --plan C:/SideProjects/fx-talanta/.local/mcp-calendar-dev/plan.json --journal C:/SideProjects/fx-talanta/.local/mcp-calendar-dev/journal.sqlite
python -m fx_talanta.provider_pipeline --journal C:/SideProjects/fx-talanta/.local/mcp-calendar-dev/journal.sqlite --collect --sources fed ecb boj --tls native --symbol EURUSD
python -m fx_talanta.provider_pipeline --journal C:/SideProjects/fx-talanta/.local/mcp-calendar-dev/journal.sqlite --symbol USDJPY
```

Use the isolated environment's Python executable. `--tls native` requires the
already documented provider-probe dependencies; never install into an active
collector's environment. Each MCP invocation performs one bounded poll. Exit zero
means the poll committed, not provider qualification. The dated plan expires;
subsequent development needs a freshly checked plan rather than an extended clock
policy. No unattended deployment or new 24-hour campaign is started by this change.

## Validation and remaining qualification

Local validation passed 316 tests; 119 PostgreSQL-dependent tests were skipped
locally to preserve active broker environments. Focused tests include atomic
cursor/revision rollback, restart replay, identity/version conflicts, uncertainty,
omissions, clock/anchor mismatch, partial responses, invalid endpoints, timeout and
server-error sanitization, multiline SSE, and coexistence with news in one journal.
A successful MCP request retains its transport result as the snapshot ages;
the filter evaluates freshness and coverage separately and continues blocking entries.
CI runs the full PostgreSQL, Docker/container and profile checks on the PR commit.

Real release revisions and terminal disconnect recovery have not yet been observed.
Two successful reads do not establish sustained reliability or publication latency.
Official USD/EUR/JPY category reconciliation, intended-use scope and broader news
coverage remain open in [provider acceptance](../engineering/provider-acceptance.md). The ongoing
campaigns retain their original sources, environments, gates, evidence and deadlines.
