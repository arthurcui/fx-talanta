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
| Protection | Separately checkpointed monotonic state and sticky halt; final native evidence can settle protection/closure. Fixed local repair/exit dispatch journals an attempt before calling the port and preserves actual state while disabled | Disk/clock/restart problems block mutation. An unsent recommendation is never recorded as an executed repair/exit. Deadline qualification defaults to missing, not invented production values |
| Backend receipt/read model | Reference risk result and native execution result are separate. Report intent is committed before processing; nonce reply and request-level result survive restart | Submission-attempt receipts and positive broker-query states are separately recorded. Unexpected attempts/fills in this disabled release add a sticky halt. Lost ACK replay is idempotent; old revisions never replace newer state |

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

`DemoEA.mq5` is a default-off host with an entry window of at most 300 seconds.
Expiry closes admission and drains reconciliation/report delivery before shutdown. OnInit binds
account/client/release/policy and opens risk, execution, outcome, broker-state outbox and protection
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
include dependency closure, native compiler results, 69 native fixture checks,
actual native receipt and test artifact hashes. The Tester-only port double
exercises dispatch, replay, uncertain replies, post-flush stale quotes, ownership,
partial fills, cursor progress, partial close, retained checkpoints and deadlines.
The full Python/PostgreSQL/loopback HTTPS regression passed **844 tests with zero
skips**. The initial 820-test result is preserved separately and is not used to
certify these changes.
The real native port remains hard-disabled in those tests. No synthetic call count
is presented as a broker-order count.

Earlier compiler and sandbox/Tester failures are retained privately and summarized
in the report. Historical qualification reports remain byte-for-byte unchanged;
archived source files allow their original hashes to be verified after shared
code changes. The old fault harness now explicitly identifies when its native
reference is historical rather than a current-source certification.

## Completed protective dispatch and state delivery

The bounded host now invokes `DemoProtect` after positive reconciliation. It
constructs only a local TIGHTEN_STOP or CLOSE derived from an owned original ENTER,
with zero additional risk, its current state version and a short local expiry.
It does not invent a new backend signature, reuse the entry expiry for a new
entry, or consume another backend sequence. The original digest, derived action
and native facts are journaled before the fixed call. Native preparation and
post-persistence validation can narrow or veto it. The real port stays disabled.

There is at most one repair attempt and one controlled-exit attempt per entry.
A definite stop rejection can lead to the controlled exit; an ambiguous reply
or crash after the durable attempt requires reconciliation and cannot resend.
A broker acknowledgement does not settle protection or close the position.
Positive broker queries must establish the result. Exit rejection is a sticky
halt. A known final-barrier refusal settles the unsent entry protection record
with NO_CALL rather than inventing an unresolved broker submission.

A separate `.states` outbox records positive entry and management observations,
including partial fill, open/remaining volume, accepted stop, order/position IDs,
UTC observation and uncertainty, and a native broker-witness fingerprint. The
private execution journal retains the matching order/deal/position witnesses.
This outbox requires its own retained checkpoint on restore. It sends the
original payload until acknowledged, prioritizes the execution receipt first,
and prevents another work pull while reports are pending. Reconciliation after
a crash can reconstruct a missing state report when a positive query is still
available, including a closed entry. If a management confirmation can no longer
be re-established (for example, the tightened position has subsequently closed),
the native journal must be audited; absence is never promoted to confirmation.

Backend REPORT handling atomically persists the authenticated native claim and
canonical M2A `ExecutionState` / `ReconciliationResult`, linked to the original
request/reservation and predecessor hashes. Entry observations carry both types;
CLOSE, TIGHTEN_STOP and CANCEL confirmations carry a `ReconciliationResult` plus
the actual observed position remainder. A partial close can leave a position
larger than the amount closed; it is not forced into an entry-fill quantity model.
A separate management request is blocked while the parent protective action is
in flight or unknown. Conflicting revisions, future times,
regressing fills and reopened closed executions refuse. An identical old revision
receives an ACK without replacing the latest read model. Reservations are **not**
released by this reporting path. An unexpected native attempt/fill adds a sticky
entry halt in the disabled release.

The report is labelled `EA_BROKER_RECONCILIATION` and
`independently_verified=false`: a signed EA observation is not an independent
acceptance audit. State reports are emitted on lifecycle changes; their timestamp
is the last reported positive observation, not a fresh quote or a heartbeat.
Transport health and original quote age remain separate indicators.

The actual native synthetic attempt receipt and state report are checked in
alongside the no-order receipt. Python independently decodes them. PostgreSQL
and loopback HTTPS tests exercise durable delivery, lost replies and restart.
The [initial PR evidence](evidence/m2-demo-execution-initial.json) remains intact;
changed original source/artifact bytes are retained by hash for verification.

## Remaining M2D acceptance

Protective dispatch and broker-state delivery are implemented and fixture-tested;
they are no longer deferred wiring tasks. Reviewed activation with qualified
operating inputs and an explicit finite demo order/risk budget remains separate.
Merely changing the compile-time constant or turning on Algo Trading is not an
activation procedure, and this PR grants no order permission.

Actual demo acceptance must independently verify fills/partials, SL rejection and
bounded repair/exit, lost replies, duplicate requests, terminal/backend/database
restart and loss, stale quotes, wrong account, unexpected positions and
closed-market exit. Retain all native witness journals, reports and checkpoints
for independent reconstruction. Preserve every original M1 failure/provider gap.
These are actual-order acceptance gates, not another 24-hour campaign. PR #23
remains unmerged pending review.

## November 4 order-gate preflight

The [retained preflight report](evidence/m2-gate-preflight-20261104.json)
records a new bounded, read-only FOREX.com check against the existing demo account.
It is **HOLD**, not actual-order acceptance. Algo Trading stayed off, no order API
was called, no campaign was started, and CMC was not modified.

The final capture had a 53 ms host-clock uncertainty bound. The account uses CAD;
the broker conversion symbol is `USDCAD.`. An earlier attempt using `USDCAD`
returned `READER_FAILED` and remains recorded. The corrected capture resolves the
missing CAD-conversion input. A separate read-only history query found one funding
record, zero trade deals, zero positions and zero pending orders. These observations
do not constitute a qualified production day-loss baseline.

The capture helper deliberately supplies no operating context. Its remaining
MANDATE, COSTS, BASELINE_AND_EXPOSURE, SESSION and PROVIDERS missing groups therefore
mean that facts were not supplied to this capture, not that every fact is necessarily
unobtainable. The helper explicitly marks broker timestamp mapping unqualified;
short empirical consistency cannot be relabelled as a qualified UTC mapping.
The original private binding was preserved in every capture.

### Proposed bounded execution-only acceptance scope

The owner selected a bounded execution-only demo gate, with M1 qualification gaps
preserved and strategy trading blocked. This does not itself enable the native
dispatcher or certify any broker/provider qualification. It would distinguish execution validation
from the unresolved M1 strategy/provider qualification and keep strategy entries
blocked. Proposed limits are two entry attempts, at most 0.02 lot per entry,
one position at a time, at most 0.25% planned risk per entry and 0.50% cumulative planned risk.
Those are prospective limits, not a claim that an activation controller exists or
that planned loss is a guaranteed loss cap.

Before any order, implement and test a durable, account-bound activation controller
that charges attempted/uncertain submissions once, cannot reset its budget after a
restart, and rejects entries after its finite entry window. Retain the two-second
entry rule, qualified timestamp/clock checks, ownership checks, native final risk
validation and independent broker reconciliation. Unknown results forbid resending;
management authority must remain narrow enough to resolve only already-owned risk.
A deadline cannot be reported as successful shutdown with unresolved exposure.

Archive private native witnesses and independently reconstruct each observed order,
deal and position against the backend journal. Restore Algo Trading off after
confirmed flatness. Retain fixture-only, unavailable and unobserved fault scenarios
as such: partial close is not partial fill; a short normal fill does not establish
closed-market recovery or any broader provider qualification. No gate is marked
passed by this preflight or this proposed scope.

## Bounded acceptance budget implementation

`demo.acceptance_budget` implements a dedicated, checkpointed budget journal with
at most two entries, 0.02 lot per entry, 0.25% planned risk per entry and 0.50% total.
Its immutable account/plan binding permits an entry window of at most five minutes.
No rejection, uncertain response, closure or restart refunds a charge. Lost journals,
stale checkpoints, valid-prefix rollback and competing stale instances refuse.
One unresolved charge blocks another entry. Positive independently audited entry
and exit quantities, a flat account and no pending orders are required to record
closure; position absence and EA-reported confirmation alone are insufficient.
Reconciliation may be recorded after the entry window expires.

`demo.bounded.BoundedDemoCoordinator` wires charging into the existing trusted
publication path. Its immutable backend binding includes the budget fingerprint;
restoring it as an ordinary unbudgeted coordinator fails. Quantities and risk are
rounded upwards to native lot units and CAD cents. Charging precedes publication:
a commit/response failure cannot refund or implicitly retry the charge. Existing
risk, loss, ownership, quote-freshness and delivery checks remain in place.

This is a **disabled publication rehearsal**, not completed native activation.
There is no HTTP budget-reset or activation endpoint. The real native hard gate
remains false. The independent-audit ingestion method is a trusted local boundary;
it records a completed external audit and does not turn a hash or supplied fields
into verified broker truth. Native budget enforcement/activation, qualified broker
timestamp mapping and source-backed operating inputs still require completion
before actual orders. M1/provider gaps and unobserved fault cases remain open.

The budget tests exposed an open SQLite handle after bootstrap on Windows. Journal
creation now closes its connection deterministically. The previous source bytes
are archived for historical evidence verification. The actual results for this
change are recorded separately from the prior native and regression evidence.

[Budget integration evidence](evidence/m2-bounded-budget.json): **880 full
Python/PostgreSQL/loopback HTTPS tests passed, zero skips**, including 36 new
budget/publication checks. Lint and formatting passed. The regression used separate
fixture databases, verified unchanged Python sources and the original environment,
and made no broker calls. Native sources were unchanged; the earlier 69 native
checks remain evidence for their original source rather than this new Python budget.

## Native budget integration and resumed gate checks

The [native budget evidence](evidence/m2-native-budget.json) records **85 native
Tester checks**, compilation of both native programs with zero errors/warnings,
and **882 full Python/PostgreSQL/loopback HTTPS tests passing with zero skips**.
These are offline/software results; no broker order was sent.

`AcceptanceBudget.mqh` gives the EA its own exclusive, hash-chained journal bound
to account scope, release, policy, backend plan fingerprint and entry window.
The disabled host opens it with an explicit retained checkpoint and binds it to
the native port. Before an entry mutation, the native port charges the original
request's maximum volume/risk and requires a flat account. Native limits are two
entries, 0.02 lot each, 0.25% planned risk each, 0.50% total and a five-minute maximum
entry window. No refund or retry follows an unknown result. Positive deal
reconciliation is required to clear an unresolved charge; backend independent
audit remains a separate prerequisite for publishing another entry.

Expiry is now durably latched in both budget implementations. A restarted journal
or backwards clock reading cannot reopen an expired entry window. Recording a
positive closure after expiry remains allowed. Historical reports and source bytes
are preserved; a failed intermediate regression against the older native source
pin is retained rather than rewritten as a passing run.

The resumed existing FOREX read-only capture completed with a 62 ms host-clock
bound and unchanged original binding. Broker timestamp mapping remains explicitly
unqualified. The capture helper still omits operator context by design; its missing
provider group does not reinstate M1 qualification as a prerequisite for the
owner-selected execution-only scope. Strategy/provider qualification remains open.

**Activation is still incomplete.** The real submission constant remains false,
and the host still enforces Algo Trading off. Enabling it requires an order-capable
host with reviewed controlled-close behavior, source-backed execution-only inputs
and qualified timestamp mapping, followed by actual independent broker evidence.
The later entry-drain fix below replaces the former unconditional timer shutdown.
These budget controls alone are not a deployable order-capable release.
Desktop inspection also failed before initialization because the Windows helper
could not write its kernel assets, including after reset. No broker terminal settings
were changed. There was no new qualification campaign or strategy enablement.

## Percentage risk mandate (supersedes fixed monetary limits)

The owner replaced the fixed monetary budget with controlled percentages. The
current default and maximum rates match the existing risk engine: **25 basis
points (0.25%) per entry and 50 basis points (0.50%) cumulative planned risk**.
A plan can choose smaller rates. These percentages describe modeled loss at the
stop, including the risk model's cost allowances; they are not position notional
percentages, margin percentages or guaranteed maximum realized losses.

The plan pins verified starting eligible equity (the lower of allocated capital
and equity), account currency and an equity-evidence fingerprint. Every entry uses
the lower of this pinned basis, current eligible equity and the basis of previous
accepted charges. Gains, deposits, closing a position or restarting cannot enlarge
or replenish the campaign budget. Falling equity can leave no budget for another
entry. Existing stricter risk-engine, daily-loss and exposure checks still apply.
The native port rechecks current broker equity before charging.

Monetary risk remains an internal calculation in account-currency minor units:
risk is rounded up, equity down, and integer comparisons enforce the percentage
without rounding an allowance upwards. There is no fixed C$5/C$10 policy cap.
Both CAD and USD account currencies are supported. The two-entry, 0.02-lot,
one-position, five-minute and two-second entry restrictions remain unchanged.

`percentage-budget/2` and `DEMO_BUDGET_PERCENT_2` bind the policy and basis to their
journals. Old fixed-limit journals cannot be adopted as percentage journals or
reset automatically. Prior fixed-limit reports/source bytes remain historical
proof of those versions, not qualification of this version. This change does not
enable trading or complete actual-order M2 acceptance.

[Percentage-budget evidence](evidence/m2-percentage-budget.json): **895 full
Python/PostgreSQL/HTTPS tests passed with zero skips, and 90 native offline checks
passed**. Both native programs compiled with zero errors/warnings. This covers
percentage boundaries, equity scaling, conservative rounding, falling equity,
no budget growth from gains, immutable basis/rates on restart and retained expiry.
No broker calls or terminal deployment occurred.

## Entry-window drain and renewed percentage-gate preflight

The [entry-drain evidence](evidence/m2-entry-drain.json) supersedes the timer-stop
limitation described above. The disabled host now persistently closes admission
at the earlier host-duration or budget deadline, including after a blocking HTTPS
exchange. The final native entry barrier independently checks both monotonic and
bounded UTC deadlines. Expiry never refreshes the original quote; the two-second
entry ceiling and 25/50 bps percentage limits are unchanged.

A DRAIN journal record survives restart and never refunds a charge. Reconciliation,
report delivery and the existing owned-risk management path remain available after
admission closes. Successful host shutdown requires a complete RECONCILED scan,
a connected and flat account, no unresolved protection state, every non-rejected
request positively CLOSED, and an empty report outbox. An acknowledgement, missing
position, disconnected terminal, partial/invalidated scan or pending report cannot
satisfy this condition. Identity/storage failure holds the host with an explicit
alert instead of removing it or claiming a successful shutdown. This does not
force-close a protected position or create a new management authority. The order-
capable release, including its controlled campaign close path, remains disabled.

Both programs compiled without errors/warnings; **106 native offline checks**
passed. One earlier compile warning and one local tester authorization failure
were preserved privately. The successful fixture used an isolated portable tester
with cloud/remote agents and broker trading disabled. These are software results,
not broker-order evidence.

The renewed short FOREX read-only preflight captured three observations
per required forex symbol with advancing ticks, a **56 ms host-clock bound**, unchanged original binding
and disabled Algo Trading. It still reports TIMESTAMP_MAPPING_UNQUALIFIED. The
capture helper deliberately supplies no operating context; its MANDATE, COSTS,
BASELINE_AND_EXPOSURE and SESSION labels mean those inputs were not supplied by
this helper, not that the account lacks them. Its PROVIDERS label belongs to the
full strategy input model and is not reinstated as an M1 prerequisite for the
owner-authorized bounded execution-only gate.

The remaining concrete order prerequisites are a qualified quote timestamp mapping,
a source-backed execution-only operating packet, and the reviewed order-capable
host/backend activation and controlled-close path. Actual fills/closure must then
be independently reconstructed. Desktop access was recovered after the owner
restored the FOREX window; no trading setting or broker deployment changed. M1
failures and provider gaps remain separate, and no 24-hour campaign was started.

For the timestamp investigation, the official
[MetaQuotes Python tick documentation](https://www.mql5.com/en/docs/python_metatrader5/mt5copyticksfrom_py)
describes UTC timestamps. That general statement does not independently establish
the existing broker-specific offset used by the provisional capture. The offset
has not been promoted to qualified execution evidence.

The final isolated regression passed **896 Python/PostgreSQL/HTTPS tests**, with
zero failures or skips. Its report verifies unchanged Python source and original
environment during execution, separate fixture namespaces and no broker access.
