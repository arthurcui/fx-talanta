# Disabled demo execution integration

PR #22 was merged after its exact-head CI passed. This increment carries the
complete M2A request through the authenticated backend and native dispatcher.
Trading remains disabled, including protective mutations. No terminal deployment,
broker order, new account or 24-hour campaign was performed. Full M2 acceptance
is **not passed**: reviewed activation and actual demo-order acceptance remain.

## One request through the system

| Boundary | Authority and durable evidence | Failure behavior |
|---|---|---|
| Operating inputs and publisher | Existing M0/M2 operating-evidence loader and account authority; original envelope, snapshot hash, release/policy, reservation, sequence and loss ledger | Missing qualification, stale evidence, lost lease or conflicting checkpoint refuses publication |
| Demo transport | `DemoCoordinator`, protocol-specific backend binding, original full `ea-demo/1` frame plus reference-risk packet inside the existing HMAC/TLS frame | Wrong account, protocol, digest, nonce or epoch/authority refuses; HTTP cannot enqueue work |
| Native admission | `DemoKernel` persists the reference receipt before dispatch. `DemoRuntime` validates the same full request and actual native context; gateway journals refusal or READY and native check facts | A refusal consumes its sequence; identical ID/hash replays; changed hash refuses. A crash between receipt intent and outcome reports INTERRUPTED and never silently dispatches |
| Fixed dispatcher | Fixed native port prepares ENTER/CLOSE/TIGHTEN_STOP/CANCEL, persists SUBMITTING before a call, refreshes checks after journal/OrderCheck work, narrows volume, and checks clock/quote age immediately before the fixed call boundary | `FX_DEMO_SUBMISSION_AUTHORIZED=false`; no request, model output, terminal toggle or input can override this release gate. Ambiguous replies remain OUTCOME_UNKNOWN and cannot be resent |
| Broker reconciliation | Resumable order/deal/position scan; positive order identity, owned deal history, position balance, cancellation or stop confirmation | Query failures, changed snapshots, ambiguous matches, manual contamination and incomplete history remain unresolved; no closure inferred from missing data |
| Protection | Separately checkpointed monotonic state and sticky halt; final native evidence can settle protection/closure. Suppressed repair/exit recommendations preserve actual state | Disk/clock/restart problems block mutation. An unsent recommendation is never recorded as an executed repair/exit. Deadline qualification defaults to missing, not invented production values |
| Backend receipt/read model | Reference risk result and native execution result are separate. Report intent is committed before processing; nonce reply and request-level result survive restart | Disabled release rejects claims of a submission/fill. Lost ACK replay returns the original response. Conflicting native results refuse; repeated identical reports do not duplicate the displayed outcome |

A reference-risk ACCEPTED result is **not** execution authority. For management,
that reference describes the supplied snapshot; native ownership, state version,
zero additional risk and no-loosening checks determine eligibility. The public
native fixture actually returned reference ACCEPTED and native
TRADING_DISABLED/REJECTED. Python independently validates that recorded receipt,
including through PostgreSQL and bounded loopback HTTPS tests.

The native audit record retains request/digest, source-risk hash, actual clock and
tick times, uncertainty, approved amount, bid/ask, volume/stop specifications,
position/order/version, accepted protection and ownership/veto facts. These are
private operational records. The checked-in artifacts contain synthetic facts only.
A native ACK is not a fill, and native internal management state is not a substitute
for an independently reconstructed M2A broker ExecutionState.

## Native lifecycle and safety

`DemoEA.mq5` is a bounded, default-off host (maximum 300 seconds). OnInit binds
account/client/release/policy and opens risk, execution, outcome and protection
journals with explicit bootstrap or separately retained checkpoints. Bootstrap
requires a flat demo account. Incomplete bootstrap is not automatically reset.
OnTimer drives HTTPS delivery and reconciliation; it does not depend on OnTick.
OnTradeTransaction invalidates the scan so its work is re-queried. OnDeinit closes
the journals and clock. No EA was attached to either broker terminal in this work.

The two-second entry ceiling applies to both the original source observation and
the bounded native quote context; it is checked again after persistence. A newer
cached quote cannot refresh the original snapshot's age. There is no change to the
five-second observer ceiling. Transport health remains separate from quote age;
EA/Python/MCP latency and channel indicators remain required UI work.

The history cursor advances across timer calls, up to 128 rows per call and 10,000
selected orders/deals, with 1,024 journal entries/exposures as hard bounds. These
are work bounds, **not** a claim that a synchronous terminal API can be preempted
within a particular number of milliseconds. Larger/changed histories refuse until
explicitly reconciled. Missing or unqualified time mapping, operating evidence,
loss state, protection deadlines or current native facts cannot authorize entry.

## Validation

[Source-pinned evidence](evidence/m2-demo-execution.json) includes the full native
include dependency closure, native compiler results, 30 native fixture checks,
actual native receipt and test artifact hashes. The Tester-only port double
exercises dispatch, replay, uncertain replies, post-flush stale quotes, ownership,
partial fills, cursor progress, partial close, retained checkpoints and deadlines.
The full Python/PostgreSQL/loopback HTTPS regression passed **820 tests with zero skips**.
The real native port remains hard-disabled in those tests. No synthetic call count
is presented as a broker-order count.

Earlier compiler and sandbox/Tester failures are retained privately and summarized
in the report. Historical qualification reports remain byte-for-byte unchanged;
archived source files allow their original hashes to be verified after shared
code changes. The old fault harness now explicitly identifies when its native
reference is historical rather than a current-source certification.

## Remaining M2D acceptance

The disabled delivery/dispatch/recovery route is implemented. The current host
intentionally reports no-order outcomes and suppresses protective dispatch. A
separately reviewed activation must wire enabled protective actions and full broker
state reporting through the same durable boundaries, with qualified operating
inputs and an explicit finite demo order/risk budget. Merely changing the constant
or turning on Algo Trading is not an activation procedure.

Then independently verify actual demo fills/partials, SL rejection and bounded
repair/exit, lost replies, duplicate requests, terminal/backend/database restart
and loss, stale quotes, wrong account, unexpected positions and closed-market exit.
Retain every original M1 failure/provider gap. These are actual-order acceptance
gates, not another 24-hour campaign and not permission granted by this PR.
