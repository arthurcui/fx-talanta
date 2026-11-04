# EA quote freshness and latency review

> Historical review: the subsequent [lifecycle remediation](m2d-lifecycle-remediation.md) records fixes and actual bounded test results. Findings below retain their original review context.

Reviewed November 4, 2026 after the owner's challenge to the clock assumptions.
This is a design review, not a changed acceptance policy or an additional run.
Trading remains disabled. The two-second entry ceiling remains unchanged, and
the three actual native HTTPS attempts retain their original outcomes.
The [event lifecycle review](ea-event-lifecycle-review.md) covers initialization,
reinitialization, skipped/coalesced notifications, cleanup and concrete code gaps.

## Correction to the diagnosis

The 100 ms clock-error ceiling is an FX-Talanta design choice, present in its
gateway, safety fence and connected protocol. It is not a MetaQuotes requirement
for EAs, and crossing it does not establish broker quote lag. Attempt 03 measured
63.225–99.002 ms **local MT5-to-Python request RTT**, not broker-to-terminal delay.
Its combined native clock intervals were 116–134 ms, so the implementation rejected
them. Authentication succeeded; no HOLD receipt or ACK completed. The
[actual evidence](../evidence/m2d-native-https-20261104.json) remains incomplete.

Concentrating on getting this exchange below 100 ms before completing any
read-only handoff conflates application clock qualification with transport
availability. The threshold must not be weakened retrospectively to pass that
attempt. Its role in a future design should be justified separately from quote
freshness, telemetry and connection health.

## What the platform actually promises

* [`SymbolInfoTick`](https://www.mql5.com/en/docs/marketinformation/symbolinfotick)
  returns the symbol's latest price snapshot, including the last-update time.
  Re-reading it does not request a newly generated quote or make cached data fresh.
  [`MqlTick`](https://www.mql5.com/en/docs/constants/structures/mqltick) carries
  `time_msc` and flags; unchanged Bid or Ask alone is not proof that no tick arrived.
* [`OnTick`](https://www.mql5.com/en/docs/event_handlers/ontick) applies to the
  attached chart's symbol. Events are processed serially, and another NewTick is
  not queued while one is already queued or being processed. This is a market-state
  notification, not a lossless callback for every broker tick.
* [`CopyTicks`](https://www.mql5.com/en/docs/series/copyticks) is the mechanism for
  retrieving recorded ticks when every available update matters. Initial history
  synchronization can wait up to 45 seconds in an EA. Backfill therefore belongs
  outside an entry-critical handler, with cursor/replay handling and recorded gaps;
  history recovery does not prove original real-time delivery latency.
* [`WebRequest`](https://www.mql5.com/en/docs/network/webrequest) is synchronous.
  Moving it from `OnTick` to `OnTimer` in the **same EA** does not create a second
  execution thread. The platform processes the EA's events serially. A separate
  worker/program or a bounded nonblocking transport is needed if communication
  must not delay that EA's quote or protection work.
* [`TimeCurrent`](https://www.mql5.com/en/docs/dateandtime/timecurrent) is the last
  known quote-related server time. Outside `OnTick`, it can come from another
  Market Watch symbol. It is not an independently advancing per-symbol clock;
  subtracting a silent symbol's tick time from it can be misleading.
* [`TimeTradeServer`](https://www.mql5.com/en/docs/dateandtime/timetradeserver) is
  estimated by the terminal and depends on the computer's time settings. It is
  not an independent sub-millisecond broker clock. A
  [`GetMicrosecondCount`](https://www.mql5.com/en/docs/common/getmicrosecondcount)
  delta measures elapsed time within one MQL program, not UTC or time elapsed
  before that program observed a tick. Its origin must not be compared directly
  with another process's counter.
* MetaQuotes explicitly separates
  [connection state from data synchronization](https://www.mql5.com/en/book/common/environment/env_connectivity).
  `TERMINAL_CONNECTED` and `TERMINAL_PING_LAST` describe the connection and last
  known broker ping. They do not certify a particular quote's age or delivery time.

## Measure different quantities separately

| Quantity | Useful observation | What it cannot prove alone |
| --- | --- | --- |
| Time since this EA observed the latest update | Local elapsed counter recorded on a new observation | Source-to-terminal latency before observation |
| EA processing and buffering delay | Counter deltas and queue/drop counters in the same program | Whether an upstream quote was already old |
| EA/Python channel delay | Request RTT or acknowledged sequence progress | Broker feed latency; one-way delay without a defensible clock relation |
| Broker connection health | Connected state, synchronization state, last ping, reconnects | Every requested symbol has a recent quote |
| Source timestamp age | Validated timestamp semantics and a bounded clock relationship | An arbitrary timestamp subtraction without validating those assumptions |

A quiet interval can mean an unchanged market, a closed session, event handling
delay or a feed problem. One old timestamp cannot identify which. A quote can
remain the latest available market snapshot while failing our chosen two-second
entry policy. That should produce entry HOLD plus an explicit reason, not an
unsupported conclusion that the broker connection failed.

## Comparison with the implementation

`mql5/readonly/QuoteStream.mq5` already uses a small per-symbol `OnTick` capture,
a bounded buffer, sequence/drop accounting and separate INITIAL/TICK/HEARTBEAT
records. It contains no HTTP or trading calls. That foundation is appropriate.
Its timer performs file writes/flushes on the same EA thread, so their cost and
event coalescing still need measurement. A heartbeat is not a new quote, and the
publisher's first sample does not establish a fresh source event.

`mql5/connected/ConnectedEA.mq5` is a separate no-order diagnostic EA. Its
synchronous HTTPS exchange is isolated from the quote publisher, but it should
not become the future executor's blocking hot path. It checks its UTC interval
before fetching or acknowledging HOLD work; therefore the 100 ms gate prevents
even non-actionable receipts when clock qualification fails.

`Service.exchange` samples the backend clock before authority and journal
transactions and returns only after durable exchange persistence. Its full
request RTT includes application/transaction work as well as TLS and local
transport. The records do not contain a per-stage timing breakdown, so the exact
share attributable to each stage is unproven. Relabeling that RTT as network-only
or broker latency would be incorrect.

The native gateway's `FxNativeContext` uses `TimeCurrent()*1000+999` and zero clock
error in its **Tester-only** path. `FixedGateway.OnInit` refuses a non-Tester
environment. That fixture convention is not an acceptable production clock
qualification and must not be copied into a connected executor.

## Recommended direction and acceptance boundaries

Keep Python responsible for proposals and bounded risk allowances. The native EA
should obtain the latest symbol snapshot and revalidate price/spread, risk, session,
instruction expiry and freshness immediately before any future authorized order.
An earlier Python observation must not substitute for this final local check.
Keep blocking network/database/research work outside that entry/protection path.
The canonical baseline generates candidates on completed M15 bars with H1
context; high-frequency execution is explicitly outside its scope. There is no
demonstrated strategy requirement here to reject every read-only control exchange
whose clock interval exceeds 100 ms. That is separate from the owner's explicit
two-second entry-price restriction.

Preserve the two-second entry restriction. Measure local residence/processing with
elapsed counters and expire instructions locally after a validated handoff. When
the rule refers to age since a source timestamp, account for source-time mapping
and uncertainty as well. **Do not silently redefine source age as time since first
local observation.** If the necessary source-age bound is unknown, say unknown and
HOLD; a monotonic counter cannot manufacture the missing upstream evidence.

A reviewed protocol revision should allow authenticated read-only health and
clock-unqualified diagnostic records to be journaled independently of entry
eligibility. Such records must never mint execution authority or revive expired
leases. Cross-process expiry, authority fencing and audit still need explicit
time/ordering semantics; local timers alone do not solve distributed authority.

Acceptance should separately establish channel availability, per-symbol update
observation, bounded local processing, supported source-age interpretation,
entry-time rejection and independent order/receipt reconciliation. UI indicators
for EA, Python and MCP should present channel health, quote age, local lag and
clock uncertainty separately. Unknown values must stay unknown. No universal
100 ms EA requirement or unconditional two-second broker service guarantee was
found in the cited MetaQuotes API contracts.

These are recommendations for the timing/telemetry boundary. This review neither
implements that protocol revision nor authorizes another terminal test, campaign
or broker order.
