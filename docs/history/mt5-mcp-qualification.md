# Native MT5 MCP qualification

The November 3, 2026 read-only probe authenticated to CMC's native MT5 MCP server
and the separate MetaTrader.com market-data service. Native calendar access is a
usable candidate without deploying an MQL5 script or service. **None of these
probes establishes sustained acceptance or authorizes trading.**

The [sanitized observed evidence](../evidence/mt5-mcp-probe-20261103.json) includes
timestamps, counts, conservative quote ages and failed requests. Credentials,
account identifiers, prices, headlines and article bodies are excluded. The copied
MCP configuration stays in an ignored local file. No client was installed into
Codex configuration, and no production adapter, service or trading path was added.

## Results

| Capability | Observed result | Qualification consequence |
| --- | --- | --- |
| CMC tick history | A 60-second window returned 120 EUR/USD and 148 USD/JPY ticks, ordered within the requested interval, with valid bid/ask relationships and neither result reaching the 1,000-row cap. | Read access works; completeness against an independent tick source and sustained recovery remain unverified. |
| CMC quotes | All 26 reads succeeded in a separate one-minute sample. EUR/USD met the five-second age ceiling in 13/13 samples; USD/JPY in 9/13, with an oldest quote age upper bound of 10.214 seconds. | MCP does not eliminate stale broker quotes. The five-second observer ceiling and stricter two-second entry rule remain unchanged. |
| CMC terminal news | No locally available news in the requested preceding 24-hour interval. | Cannot qualify a market-news feed. The tool's local, language-filtered list is not a complete server archive. |
| CMC economic calendar | Catalogs returned 248 USD, 278 EUR and 124 JPY event series. Dated JOLTS, ECB and BOJ records were readable; JOLTS lookup by value ID agreed with the range query. | Calendar transport and representative reads work; catalogs are not proof of complete dated coverage. |
| Public MetaTrader.com quotes | Both pairs' latest returned price timestamps were 17:00 UTC when queried around 17:35 UTC; no bid/ask pair was supplied. | Fails the execution freshness requirement and is not broker execution pricing. |
| Public MetaTrader.com news | Preceding-day queries returned one EUR/USD item from DailyForex, published 09:34 UTC, and zero USD/JPY items. | Sparse initial backfill does not qualify comprehensive or timely forex news. |

The public instruments were resolved through search before querying their profiles:
[EUR/USD](https://www.metatrader.com/en/symbols/eurusd) and
[USD/JPY](https://www.metatrader.com/en/symbols/usdjpy). Their public quotes are
separate from CMC terminal quotes. FOREX.com MCP was not tested or reconfigured.

## Time and update semantics

The terminal reported UTC and last-known trade-server time two hours apart at
both ends of the quote sample. Quote timestamps have second precision; the report
preserves conservative age bounds instead of inventing millisecond precision.
Tick history supplies millisecond timestamps in the observed broker time basis.

JOLTS was returned at November 3 **17:00 server time**, which normalizes to
**15:00 UTC** using that observed offset and matches the previously pinned manual
BLS calendar. This is a same-day time-conversion check after publication, not a
prospective delivery measurement. It neither replaces nor changes the separate
provider campaign's JOLTS receipt evidence. A fixed two-hour offset must not be
assumed across future timezone/DST changes without verification.

BOJ illustrates why timestamp presence is insufficient: its event-series metadata
says the exact time is specified later, while the dated value supplied a timestamp
and `time_unknown=false`. Preserve that uncertainty; the probe does not certify
the value as an exact official scheduled time.

The first unfiltered `economic_calendar_list_values_last(change_id=0)` request
timed out at the existing 12-second client bound. A later request scoped to JOLTS
returned database and filtered cursors; a follow-up using its returned database
cursor completed with zero changes. The timeout is retained. No revision arrived
during this check, and no disconnect/recovery was induced, so those behaviors
remain unqualified.

The public server initially failed discovery because the diagnostic client tried
to decode each SSE data line separately. Its response contains a JSON document
across multiple SSE data lines. Correct event assembly resolved discovery; four
single-line, multiline, notification and end-of-stream format checks passed.
This repair was confined to the isolated diagnostic client.

## Scope and next qualification work

The terminal exposed 107 tools and the public server six. Requests were restricted
to initialization, discovery and explicitly selected data reads. Order, chart,
watchlist, shell, file and service mutation tools were never called. Terminal
configuration hashes stayed unchanged. Existing collector sources, environments,
bindings, deadlines and evidence were not changed or restarted.

The subsequent [native MCP adapter](../operations/native-mcp-calendar.md) implements optional
calendar ingestion into the shared provider journal and records its actual
import/replay evidence separately from these earlier probes. Promotion still
requires normalization of unknown times, official USD/EUR/JPY reconciliation,
prospective delivery and omission evidence, revision and reconnect handling,
intended-use review and sustained reliability. The required-news gap remains
open; the manual BLS development workflow remains available. There is no new
24-hour campaign, automatic failover, custom MQL5 deployment or relaxed gate.

Official references: [MT5 MCP configuration](https://www.metatrader5.com/en/terminal/help/mcp_and_ai/configuration)
and [MT5 MCP capabilities](https://www.metatrader5.com/en/terminal/help/mcp_and_ai/capabilities).
The tool schemas discovered from the actual servers, rather than the general
capability list alone, determined which requests were made.
