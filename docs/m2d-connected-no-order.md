# M2D bounded connection, observations and recovery

This extends the [initial shadow transport](m2d-shadow-transport.md) in the same
PR. It implements a separate, explicitly bounded `connected_shadow` path and
`mql5/connected/ConnectedEA.mq5`. Every result is a HOLD. Neither an observation,
an authenticated exchange nor a successful test authorizes an order.

## Current evidence

The [November 4 evidence](evidence/m2d-connected-20261104.json) preserves the
actual attempts, source hashes and native results. The Python/PostgreSQL
regression passed **775 tests, no skips** in two disjoint groups (773 plus two
evidence checks); Ruff lint and formatting passed. Historical November 3
evidence and its sources are retained unchanged.

| Gate | Evidence and limit |
| --- | --- |
| Native clock and durable inbox | 49 new high-resolution-clock assertions passed; 32 unchanged legacy-clock and 36 protocol/inbox assertions retained (117 total, not 117 new runs). New host/harness compiled with zero errors/warnings |
| Real broker inputs | FOREX read-only capture observed EURUSD/USDJPY quotes, account state, symbol specifications, calculation outputs and CAD conversion; both normalized results remain HOLD |
| Original policy and failures | Original policy was expired. The first FOREX capture failed because its derived lower bound excluded recent ticks. Fixed wrapper and a separate successful attempt retained; original binding unchanged |
| CMC capture | Preflight did not verify Algo Trading disabled. No CMC native HTTPS session or setting change was made |
| HTTPS listener | Actual Python TLS tests cover trust rejection and absolute TLS/header/body deadlines; they do not prove native MT5 WebRequest |
| Recovery and authority | PostgreSQL process competition, worker crash, database outage and archive/restore tests; independent processes on one host, not two physical hosts |
| Native terminal HTTPS | Three stopped attempts preserved. Attempts 02/03 authenticated 5/9 signed CLOCK responses respectively; no native receipts or ACKs completed. Attempt 03 clock bounds 116–134 ms exceeded the unchanged 100 ms gate |
| Broker execution | Disabled in every new component; no sender, new account, campaign or order test |

The original broker and provider campaigns remain concluded without a pass.
These short observations do not reopen or qualify M1 or complete M2D connected
PAPER acceptance.

The [native HTTPS report](evidence/m2d-native-https-20261104.json) independently
reconciles all three stopped journals. Attempt 01 had WebRequest 4014 failures
before the allowlist correction. Attempt 02 had a clock rejection and a separate
status-file `PermissionError`; both are preserved. Attempt 03 reached its original
deadline with nine authenticated CLOCK replies but no accepted native clock.
Its native quote-read branch was never reached: these results do **not** show
broker quote lag. See the [source-backed freshness review](ea-quote-freshness-review.md).
The [EA event lifecycle review](ea-event-lifecycle-review.md) additionally identifies
reinitialization, no-tick management and reconciliation-retry gaps; component
test counts do not qualify those runtime paths.
The actual post-stop FOREX check found Algo Trading off and zero positions/pending
orders. CMC and the concluded campaigns were not changed.

The original [pre-HTTPS report](evidence/m2d-connected-20261104-before-native-https.json)
is retained byte-for-byte. Status-write cutoff/final-report hardening after attempt
03 is covered by the later Python regression; it is not relabeled as that run's code.

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

The deployed no-order host uses an authenticated, uncached server sample and raw
`GetMicrosecondCount()` measurements. `HighResolutionClock.mqh` rounds the RTT
bound outward, adds a 2 ms counter/conversion allowance, and charges the existing
100 ppm rate allowance for both RTT and subsequent projection. These are declared
counter assumptions, not a certificate of physical timer accuracy. The coarse
`Clock.mqh` implementation and its original evidence remain preserved: its 32 ms
allowance belonged to its coarse `GetTickCount64()` counter model, but consumed too
much of the measured budget in the second actual connection attempt. Switching
counter sources does not change the 100 ms ceiling or select a more favorable
NTP result. [MetaQuotes documents the counter distinction](https://www.mql5.com/en/book/common/timing/timing_count).

Scheduling and the stop timer still use the separate coarse counter. Native UTC
projection uses only raw microseconds and expires after five seconds. Clock error
above 100 ms rejects. The **two-second
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
Accepted sockets disable Nagle coalescing for the small clock responses; actual
measured RTT still counts in full. Status snapshots retry Windows sharing/access
denials within a 100 ms retry budget, retaining the old complete snapshot until
replacement succeeds. An exhausted budget keeps the complete pending bytes and
fails explicitly; it never extends clock, lease, observation or session deadlines.
The actual persistent-lock check took 101.53 ms of retry time because scheduling
can exceed the configured budget. This is not a hard operating-system wall-time guarantee.
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
inputs once and publishes both pair observations. Its configured observation
deadline is at most 300 seconds, with separately bounded startup/shutdown and an
external supervisor; this is not a 300-second whole-process wall-time guarantee.
Supervise the process externally; any failure preserves evidence and does not
restart a terminal or session. Fresh clocks, broker identity, global trading
disabled and explicit bootstrap remain mandatory.

Native attachment must use a new chart; do not replace the existing quote-stream
EA. Allow only the explicit localhost HTTPS origin in FOREX's WebRequest list.
In this terminal build, this is **Tools → Options → Experts**, between Trade and
GPU, rather than the Toolbox's Experts log. Check **Allow WebRequest for listed
URL** and add exactly `https://127.0.0.1:8443`; keep **Allow algorithmic trading**
and the EA's **Allow Algo Trading** unchecked. Port 8443 is the loopback Python
listener's configured HTTPS port, and `/v1/connected-shadow` is its only route.
The first actual attempt preserved eight WebRequest 4014 errors; direct inspection
then showed the FOREX checkbox disabled and its allowlist empty. The second
attempt established authenticated HTTPS after that exact setting was corrected.
No trust bypass or HTTP fallback is supported. Preserve the terminal's existing
account, broker environment, old journals and campaign sources.

Remaining connected gates include a completed native receipt/ACK handoff, broker-authoritative
timestamp mapping, real cost/loss/provider qualification, independent-host fencing
and broker protection/reconciliation timing. Demo orders need separate explicit
authorization after their prerequisites; this PR supplies none.

Reference: [MetaQuotes WebRequest](https://www.mql5.com/en/docs/network/webrequest)
requires the terminal URL allowlist and is unavailable in Strategy Tester.
