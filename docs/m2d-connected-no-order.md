# M2D bounded connection, observations and recovery

This extends the [initial shadow transport](m2d-shadow-transport.md) in the same
PR. It implements a separate, explicitly bounded `connected_shadow` path and
`mql5/connected/ConnectedEA.mq5`. Every result is a HOLD. Neither an observation,
an authenticated exchange nor a successful test authorizes an order.

## Current evidence

The [November 4 evidence](evidence/m2d-connected-20261104.json) preserves the
actual attempts, source hashes and native results. The complete Python/PostgreSQL
regression passed **767 tests, no skips**; Ruff lint and formatting passed. Historical November 3
evidence and its sources are retained unchanged.

| Gate | Evidence and limit |
| --- | --- |
| Native clock and durable inbox | Actual account-free mathematical Tester: 32 clock and 36 protocol/inbox assertions passed; all three programs compiled with zero errors/warnings |
| Real broker inputs | FOREX read-only capture observed EURUSD/USDJPY quotes, account state, symbol specifications, calculation outputs and CAD conversion; both normalized results remain HOLD |
| Original policy and failures | Original policy was expired. The first FOREX capture failed because its derived lower bound excluded recent ticks. Fixed wrapper and a separate successful attempt retained; original binding unchanged |
| CMC capture | Refused because the terminal reported Algo Trading enabled. No CMC connection test or setting change was made |
| HTTPS listener | Actual Python TLS tests cover trust rejection and absolute TLS/header/body deadlines; they do not prove native MT5 WebRequest |
| Recovery and authority | PostgreSQL process competition, worker crash, database outage and archive/restore tests; independent processes on one host, not two physical hosts |
| Native terminal HTTPS | Pending the explicit FOREX WebRequest URL permission and local certificate setup; no native connected pass claimed |
| Broker execution | Disabled in every new component; no sender, new account, campaign or order test |

The original broker and provider campaigns remain concluded without a pass.
These short observations do not reopen or qualify M1 or complete M2D connected
PAPER acceptance.

## Input and clock authority

`inputs.capture_once` checks the pinned, already-running demo terminal and its
account/build/currency identity before read-only SDK calls. It does not log in,
select symbols, change subscriptions, or enable algorithmic trading. Quotes,
positions/orders, symbol constraints and broker calculation outputs are private
evidence. The normalizer has no zero-cost, zero-loss or healthy-news defaults.
Missing mandate, costs, loss baseline/exposure, session and provider evidence
produce explicit missing codes and no actionable safety snapshot.

`scripts/connected_capture.py` records the expired original policy's refusal,
checks fresh host NTP and advancing ticks against the already-pinned offset,
and creates a separate provisional interval. The interval includes the observed
five-second window and lasts exactly 15 minutes. This does not change the
original binding or infer authoritative broker UTC. Successful captures retain
`TIMESTAMP_MAPPING_UNQUALIFIED` and cannot authorize entry. Failed attempts are
kept in separate directories; the wrapper never retries or changes the offset.

`HostClock` brackets wall-clock reads with monotonic samples. Scheduling delay
adds uncertainty; actual disjoint intervals invalidate the clock. Host evidence
expires after 60 seconds, with fresh NTP required for a new interval. NTP is
unauthenticated corroboration, not proof of long-term clock discipline.

The native clock uses an authenticated, uncached server sample, measured round
trip, a 32 ms Windows timer-granularity allowance and drift growth. Its interval
expires after five seconds. Clock error above 100 ms rejects. The **two-second
entry ceiling remains unchanged**: source and native tick ages must fit after
adding uncertainty, and future timestamps reject. The five-second observation
consistency check never grants entry freshness credit. No host clock is adjusted.

## Wire, local authority and evidence

The exact HTTPS POST route is `/v1/connected-shadow`; it shares the authenticated
`shadow/1` frame format but uses separate `connected/1` payloads and journals.
Only SYNC, PULL and REPORT are available. There is no remotely callable claim,
publish, retire, restore or execution operation.

SYNC requires the pinned, unretired authority and durable journal. Its nonce is
journaled and cannot be replayed as a new clock measurement. An expired but
unreplaced owner may synchronize and report an old receipt; neither operation
renews its lease. PULL requires a current lease. Changed nonce content rejects;
duplicate PULL/REPORT can return only their original response and expiry.

Trusted local publication retains the full private capture and its digest. The
wire projection carries symbol, source tick time, uncertainty, binding, missing
evidence, sequence and immutable expiry. The EA independently reads its native
tick, writes and flushes a HOLD receipt, and uploads it. Python recomputes the
receipt before committing it and returning a receipt-hash ACK. Loss of the ACK
does not duplicate a receipt or refresh an observation. Transport health and
historical quote ages are distinct; a healthy channel does not establish current
broker readiness, Python readiness or MCP readiness.

The development listener binds only IPv4 loopback, requires TLS 1.2 or later,
limits workers, and has a two-second absolute accepted-connection deadline
covering handshake, headers and body. It is not a public deployment service.
The EA is disabled by default, requires global Algo Trading disabled, verifies
demo identity, and enforces both a UTC and monotonic stop deadline. It cannot
place orders or adjust the terminal's account/settings.

## Coordinated recovery

PostgreSQL serializes an account-scoped authority stream independently of a
session's backend stream. All local authority times use the conservative UTC
upper bound. Expiry never grants automatic takeover, including to the old
client. A replacement requires explicit retirement and a paired checkpoint;
PostgreSQL re-reads the actual backend checkpoint while holding the authority
lock rather than trusting a caller-supplied backend value.

The native checkpoint pins exact journal bytes, scope, incarnation, epoch,
sequence, receipt digest and ACK state. The independent Python verifier checks
the native hash chain, binding/key fingerprint and receipt semantics. The
journal is hash chained, not HMAC signed; authenticated wire frames are a
separate boundary. A missing ACK is retained as missing. Administrator rollback
of both files is detectable only against an independently retained checkpoint.

Backend and native journals permanently pin their original epoch/incarnation.
Restoring them preserves that evidence; it does not rebind them to a new owner.
After verified, explicit retirement, a replacement uses a **new session stream
and new native journal**, linked through the retained paired checkpoint. There
is no seamless cross-epoch continuation or automatic release of restored state.
The database archive alone is not a complete native backup.

## Bounded operation

Use only an existing demo, a separate private output directory and a dedicated
disabled `fx_connected_*` database namespace. Runtime code receives only that namespace's writer
DSN, never an administrative credential. Compile the connected EA separately;
keep its private config, key and journals out of Git. The prepared local TLS
certificate is not automatically installed or trusted.

`scripts/connected_session.py` prepares one new private native config and starts
one bounded loopback session. It permits at most 60 seconds for initial native
attachment, with explicitly journaled startup renewals. After the first
authenticated exchange, only native PULL renews the lease. It captures broker
inputs once, publishes both pair observations, and stops within 300 seconds.
Supervise the process externally; any failure preserves evidence and does not
restart a terminal or session. Fresh clocks, broker identity, global trading
disabled and explicit bootstrap remain mandatory.

Native attachment must use a new chart; do not replace the existing quote-stream
EA. Allow only the explicit localhost HTTPS origin in FOREX's WebRequest list.
No trust bypass or HTTP fallback is supported. Preserve the terminal's existing
account, broker environment, old journals and campaign sources.

Remaining connected gates include actual native HTTPS behavior, broker-authoritative
timestamp mapping, real cost/loss/provider qualification, independent-host fencing
and broker protection/reconciliation timing. Demo orders need separate explicit
authorization after their prerequisites; this PR supplies none.

Reference: [MetaQuotes WebRequest](https://www.mql5.com/en/docs/network/webrequest)
requires the terminal URL allowlist and is unavailable in Strategy Tester.
