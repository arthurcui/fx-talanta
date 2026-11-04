# Read-only EA quote stream

This is a bounded diagnostic quote transport, not the M2 execution EA or an entry
authority. It does not complete M1, replace broker reconciliation, or change the
five-second observer ceiling and two-second entry ceiling. CMC and all original
broker/provider campaign evidence remain untouched.

## Components and safety

* `mql5/readonly/QuoteStream.mq5`: one instance on each dedicated symbol chart.
  Pins demo login, server and exact chart symbol. Refuses initialization, and
  removes itself during operation, if terminal Algo Trading is enabled or the
  binding changes. Contains no order, network, DLL/import or account-switch API.
* `OnTick` reads the latest `MqlTick` into a 1,024-element ring. A 50ms timer
  writes at most 256 buffered samples per flush to the terminal common-files
  sandbox. The local file transport avoids a network service or custom DLL.
  File writes remain synchronous; the ring does not make disk I/O asynchronous.
* Each record carries schema/run/symbol, event type, sequence, original broker
  millisecond timestamp, bid/ask, capture/emission system uptime, local UTC
  seconds, drop count and connection state. One-second heartbeat records never
  advance the quote timestamp. A final STOP record distinguishes graceful exit.
* Native inputs limit lifetime to 10–900 seconds, with a 600-second default.
  Run tokens are bounded safe strings. Existing files cannot be overwritten.
  Broker-symbol dots are mapped to underscores **only in filenames**; payload
  symbols retain the exact broker spelling. Each broker needs a different token.
* `observer/quote_stream.py` rejects wrong run/symbol/schema, invalid quotes,
  sequence discontinuities, truncation/replacement and invalid counters. The
  comparison additionally stops on drops, stopped/disconnected publishers,
  inconsistent uptime, a stale heartbeat or a failed polling worker.

These are local files within a trusted Windows user session, not authenticated
cross-machine transport. A successful parse alone must never grant execution
permission. No production observer/risk/gateway is switched to this stream.

## Bounded comparison method

**November 4 review correction:** the recorded EA arrival timestamp is at parent
consumer receipt, while the polling timestamp is in the SDK child before IPC and
parent ingestion. The matched delay therefore is not a symmetric delivery-latency
measurement; startup caches also differ. Original evidence is retained, but these
metrics must not be presented as a like-for-like transport benchmark. The
`entry_fresh` count below is diagnostic and omits clock uncertainty; it does not
grant entry permission. See the [freshness review](../history/ea-quote-freshness-review.md)
and [event lifecycle findings](../history/ea-event-lifecycle-review.md) for the precise limits.

`tools/qualification/compare_quote_stream.py` tails both EA files every approximately 10ms.
A separate Python process reads the same terminal's latest quotes at one-second
cadence, checking the pinned identity/build, clock-policy window, disabled trading
and flat account. This compares transport against a lightweight quote poller;
it is not a full replay of the existing 30-second account/history observer.

Both latest-quote caches are assessed at the same approximately 100ms times.
The report retains missing startup samples, actual assessment count and lateness;
missed times are not synthesized. Original tick timestamps use the binding's
explicit server-to-UTC offset. Freshness is `0 <= age <= 2 seconds`; a heartbeat,
receipt timestamp, or connection success cannot make an old quote fresh.

EA delivery delay uses capture-to-Python-receipt Windows system uptime, independent
of broker UTC conversion. Quote identity for matching is `(time_msc, bid, ask)`;
positive polling-minus-EA receipt delay means the EA delivered that identity first.
EA-only and polling-only identities remain visible. Identical quote identities
are not a count of every exchange/broker tick.

MetaQuotes documents that [OnTick events can coalesce and are chart-specific](https://www.mql5.com/en/docs/event_handlers/ontick).
Therefore this stream is latest-quote capture, **not a lossless tick archive**.
Zero ring-buffer drops does not prove zero terminal-side coalescing. A future
lossless requirement would need history reconciliation and independent evidence.
[GetTickCount64](https://www.mql5.com/en/docs/common/gettickcount64) normally has
10–16ms resolution; reported millisecond differences are quantized measurements.
This does not establish network latency from the broker or independently prove
the broker's timestamp clock accuracy.

## Deployment for a short diagnostic

1. Use an isolated development checkout. Do not change campaign sources,
   environments, databases or bindings. Preserve the original failed evidence.
2. Compile with that broker's MetaEditor and retain the compiler log/source/binary
   hashes privately. Install only under that terminal's `MQL5/Experts` directory.
3. Verify current host clock offset read-only, the clock-policy window, exact
   terminal identity/build, demo mode and no open positions/orders. Do not adjust
   the host clock. Turn terminal Algo Trading **off** and leave it off.
4. Create dedicated EURUSD/USDJPY charts, attach only this reviewed publisher,
   leave per-EA Algo Trading permission unchecked, and load private `.set` inputs
   with the pinned identity, exact symbol, unique token and bounded lifetime.
   Do not replace an EA on a pre-existing chart. Use another broker's MCP endpoint
   neither for deployment nor as an implicit fallback.
5. Wait for both files and current heartbeats. Run the comparison for 300 seconds
   with `--binding`, `--stream-dir`, `--token`, a new private `--output` directory
   and `--seconds 300`. Never reuse an output directory or overwrite evidence.
6. Close only the two dedicated charts after capture, which unloads their EAs.
   Verify both STOP records, stable file sizes and disabled terminal trading;
   archive raw files and hashes privately. Keep prices/account details out of git.

Example command (paths and token are supplied by the operator):

```powershell
python tools/qualification/compare_quote_stream.py --binding <private-binding.json> `
  --stream-dir <terminal-common-files/FXTalantaQuotes> --token <unique-token> `
  --output <new-private-evidence-directory> --seconds 300
```

## Actual verification

The November 3 native startup found and corrected two setup problems: terminal
Algo Trading had been enabled (the EA correctly refused to start), and a trailing
broker-symbol dot produced a double-dot filename rejected with native error 5002.
The filename mapping fixes the latter without changing payload identity. A Python
uptime type-name typo was corrected before collection began. Failed startup/output
directories are retained; none is counted as completed comparison evidence.

The corrected native build compiled with zero errors and warnings. The
[sanitized report](../evidence/forex-ea-quote-comparison-20261103.json) records the
completed 300-second FOREX capture starting at **2026-11-03 20:07:50 UTC**:

| Metric | EURUSD | USDJPY |
| --- | --- | --- |
| EA delivery median / p95 | 47 / 63ms | 47 / 78ms |
| Matched identities | 107 | 113 |
| Median polling receipt minus EA receipt | 359ms | 375ms |
| Unique EA / polling quote identities | 194 / 118 | 195 / 113 |
| EA-only / polling-only identities | 87 / 11 | 82 / 0 |
| EA fresh at two seconds, all 2,994 assessments | 49.83% | 45.72% |
| Polling fresh at two seconds, same denominator | 38.01% | 35.30% |
| EA / polling quote-age p95 | 8.888 / 9.398s | 14.458 / 15.158s |
| Ring drops / sequence errors | 0 / 0 | 0 / 0 |

Polling delivered some matched identities first (minimum polling-minus-EA delay
-63ms / -31ms); the EA is not universally faster. Eleven EURUSD identities appeared
only in polling during the recorded comparison. Their absence is not silently
treated as successful lossless delivery. There were 298 actual polling cycles;
four initial assessment samples lacked a polling quote. Assessment lateness reached
0.609 seconds once; the actual 2,994 assessments are retained instead of inventing
3,000 perfect slots. The short sample is not representative of every session.

**Conclusion:** streaming reduces local delivery delay and improves sampled
freshness, but does not solve quote freshness by itself. Both paths still expose
long-aged terminal quotes. This evidence does not isolate broker/network/terminal
cache behavior or independently validate the broker clock. Keep the two-second
entry block, Python account/reconciliation reads, and this publisher as a diagnostic
shadow path until a reviewed integration and its acceptance evidence exist.

Post-capture verification confirmed both STOP records, zero ring drops, the four
original charts restored, demo mode, terminal trading disabled, and zero open
positions/orders. Raw captures, native files, source/binary hashes and failed
startup directories remain private. Freshness counts were independently rebuilt
and every assessment's inferred tick timestamp checked against raw native/polling
evidence. The published Python formatting has the same AST as the captured source.
Host clock checks measured 22–23ms before and 24–27ms after, without adjustment.
Local regression: 334 passed, 119 PostgreSQL-dependent tests skipped. No new
24-hour campaign was started and no sustained acceptance verdict changed.
