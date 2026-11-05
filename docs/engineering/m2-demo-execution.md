# Bounded demo execution integration

## Current implementation and acceptance boundary — November 4

PR #23 adds an explicitly armed, demo-only execution build alongside the
hard-disabled default build. Strategy and live trading remain blocked. M1 broker
and provider gaps remain separate and unchanged. No new 24-hour campaign ran.
The actual bounded-order verdict is **verified with read-only recovery**, recorded
in the [sanitized session report](../evidence/m2-bounded-demo-20261104.json): one
0.01-lot EURUSD entry, broker-confirmed protection and one controlled close.
The backend received and the native outbox acknowledged the final `CLOSED` state
after the recovery described below. The original session was not an unattended
first-pass success. All test EAs/listeners are stopped, the account is flat,
Algo Trading is off and the original authority is retired.
Full M1 and the full M2 fault matrix remain unqualified;
compilation, a reference-risk acceptance and a native ACK are not substitutes for
independently verified broker fills and closure.

### Activation and authority

`DemoEA.mq5` retains its hard-disabled release. `BoundedDemoEA.mq5` selects a
separate compiled release that also requires a local, exact-hash activation
manifest, pinned account/demo identity, release/policy/budget fingerprints,
qualified finite timestamp policy, healthy journals and terminal/EA permissions.
A terminal toggle alone cannot authorize it. There is no HTTP activation,
budget-reset or model-selected execution endpoint.

The backend remains incapable of broker submission (`execution_enabled=false`).
It records native authorization separately, requires a recent authenticated
readiness report, and charges the dedicated percentage budget before publishing.
Readiness and publication are serialized; a readiness hold before admission does
not consume a reservation. A committed reservation is never refunded or replayed.
The native port independently validates identity, source and current quote age,
loss/exposure limits, volume, protection and the fixed submission boundary.

The owner-authorized maximum remains two entry reservations, 0.02 lot per entry,
one position at a time, 0.25% planned risk per entry and 0.50% cumulative planned
risk. The actual test uses stricter 0.01-lot requests and 0.10% reservations.
Starting/current/prior eligible-equity minima and conservative integer rounding
apply. A later isolated window carries prior consumed entries and risk forward;
new files or a new process do not replenish authorization. Original expired
windows are never reopened or extended.

A verified closure requires positive entry/exit deal witnesses and a flat broker
account. A separate no-execution settlement requires a complete independent audit
of the authenticated definite rejection, native journal with no submission,
unchanged broker order/deal history and flatness. Neither settlement refunds the
charge; missing positions, a hash alone, an EA claim or an uncertain result cannot
settle it. Both are trusted local audit boundaries, not network operations.

### Time, prices and controlled close

A same-day FOREX terminal Calendar export places the ISM services release at
17:00 server time; the official release schedule places it at 15:00 UTC.
Market Watch independently corroborated the two-hour server offset. Each test
pins that evidence to a finite +7,200-second mapping. It does not establish broker
clock accuracy, sustained timeliness, another broker's mapping or M1 acceptance.
Original captures/bindings remain unchanged; normalized captures retain source
fingerprints. No host clock was adjusted.

The native high-resolution clock consumes a synchronization interval before any
later read advances its monotonic watermark. Its 100 ms uncertainty limit and
full measured RTT accounting remain unchanged. The two-second entry ceiling is
checked against both the original observation and current native quote, including
a final post-persistence check. A newer tick never rejuvenates the source packet.

Native repricing first validates the original snapshot and conversion relations.
It then derives only the symbol-price-dependent conversion legs from the current
bid and the still-fresh original USD/account observation. Original timestamps,
conversion age and source hash remain unchanged; approved volume cannot increase.
This fixes the observed `CONVERSION_INCONSISTENT` refusal without accepting
inconsistent source data or relaxing adverse-price checks.

Expiry persistently closes entry admission. Reconciliation, report delivery and
one-shot owned-risk management continue. A positively reconciled protected
position can receive one controlled-close attempt at campaign end, through the
same journal, ownership, final checks and fixed native send boundary. Ambiguous
results never resend. Successful drain requires positive reconciliation, flatness,
no unresolved protection and an empty outbox; a stopped listener is not completion.

The actual close exposed an empty-account fingerprint defect: native hashing of
an empty data array returned an empty string, so a flat snapshot looked unavailable.
The fixed fingerprint includes a domain prefix. A separate hard-disabled build
replayed copies of the retained journals and positively reconciled the actual
entry/exit history. Its authenticated `CLOSED` report and native ACK were verified
against the backend and unchanged broker history. Receipt-only recovery used the
expired original owner without renewing its lease or entry window. Original
journals and the incomplete first result remain preserved. The restart protection
halt remains sticky; closure and explicit authority retirement do not rearm it.

The local TLS listener optionally reuses a connection for at most four successful
requests while retaining its original absolute two-second connection deadline,
four-worker limit, certificate validation and authenticated frames. Errors close
the connection. The default listener behavior still explicitly closes responses.
This reduces handshake overhead; it does not subtract RTT or enlarge clock limits.
Windows terminal identification now uses read-only native process APIs with exact
resolved executable matching, avoiding three PowerShell startups per capture.
Unverifiable candidate terminal processes fail closed.

### Evidence and remaining scope

[Current native/regression evidence](../evidence/m2-bounded-activation.json) separates
offline tests from actual broker observations. Prior reports and source bytes are
retained, including the [pre-repricing native fixture](../evidence/m2-bounded-activation-pre-repricing.json).
The public session report contains sanitized outcomes; private manifests, complete
broker audits, native journals, hash chains and checkpoints remain under `.local`.
Credentials, account identifiers, ticket numbers and raw prices are not published.

PR #23 verification: 938 Python/PostgreSQL tests and 125 native checks passed.
Two earlier regression runs hit the original database container's shared-memory
limit; their failures are retained. Final tests used a separate loopback-only
PostgreSQL instance, without restarting or modifying the broker-evidence database.
Both allowed entry reservations are consumed: one definite pre-submission refusal
and one actual entry. Total reserved risk is 0.20% of eligible equity, with no
refunds. Entry quote-age bounds were 1.631/1.633 seconds and native clock bounds
were 93 ms; the ceilings remain two seconds and 100 ms.

Only actually observed outcomes may pass the bounded normal-order gate. Partial
fills, rejected protection, ambiguous broker replies, closed-market exits and
restarts during real exposure remain fixture-only or unobserved unless explicitly
captured. A normal entry/close does not qualify the full live fault matrix or M1.
CMC and the owner-reported third AvaTrade demo remain untouched and unqualified
by these FOREX-only tests. PR #23 was merged after CI passed; its recorded execution limits remain unchanged.

### Closeout verification

This increment verifies the final-state path with synthetic native and backend
inputs. It does not reopen a broker campaign, change trading permissions, replenish
the consumed demo budget or qualify M1.

#### Completed work

The native lifecycle now runs through one `DemoKernel`: entry receipt/ACK, positive
protected-position reconciliation, controlled close, positive entry/exit history,
empty-position fingerprint, durable `CLOSED` report, report ACK and successful drain.
No gateway restart or separate recovery build is used in that synthetic flow.
A missing ACK keeps the report pending and blocks drain; retransmission is identical;
a wrong ACK is rejected. The fake port records exactly one entry and one close.
The real native submission port remains disabled throughout the fixture.

The actual captured native `CLOSED` payload is then replayed through the Python
backend. Restart plus a lost response yields the same ACK and one durable state
record. Receipt of that report does not make it independently broker-verified,
release reserved risk or enable trading.

The [native evidence](../evidence/m2-native-closeout-20261104.json) records **142
passing checks**: all 125 prior activation checks plus 17 closeout checks. Compilation
had zero errors and warnings. The first attempt had one failed assertion because the
new test expected `CLOSED` instead of the existing `CLOSED_CONFIRMED` return value.
Its check file and source are retained; the runtime return value was not changed.

#### Evidence validation fix

`tools.fixtures.demo_execution_fixtures.compare` previously accepted any 20 passing
rows and collapsed duplicate names into a dictionary. A truncated check file, or a
failed row overwritten by a duplicate passing row, could therefore appear successful.

It now requires a predeclared check manifest. Missing, additional, duplicate,
malformed and failing rows are rejected. Native completeness is established against
the entire declared set, not a count. Historical manifests/results are not regenerated.
A historical check set can be verified by explicitly supplying that version's names;
never derive the required set from the output being verified.

```python
import json
from pathlib import Path
from tools.fixtures.demo_execution_fixtures import compare

fixture = Path("tests/fixtures/demo-closeout")
manifest = json.loads((fixture / "required-checks.json").read_text())
report = compare(fixture, required_checks=manifest["checks"])
```

#### Acceptance boundaries

| Gate | Evidence now available | Remaining boundary |
| --- | --- | --- |
| Actual demo entry, protection and exit | PR #23 broker audit, independently verified | Original final delivery required read-only recovery; retain that qualification |
| Integrated close/report/ACK/drain | Current synthetic native lifecycle and backend replay | Not a connected first-pass broker result |
| Lost response and duplicates | Native pending report, incorrect ACK rejection, backend restart/replay; existing send-uncertainty fixtures | No automatic broker resend is authorized |
| Partial fill, rejected protection and closed-market exit | Existing native/fixture cases retained in the 142-check manifest | Fixture evidence is not an observed broker fault; applicable connected acceptance remains open |
| Database/network loss and writer fencing | Existing backend/HTTPS/PostgreSQL tests | No new live fault injection performed |
| Risk and time | Existing percentage budget and clock/freshness checks retained | Two-second entry and 100 ms clock ceilings unchanged |
| M1 qualification | Original failed/stopped reports | Still unqualified and separate from this execution-only work |

#### Authorized bounded connected verification — preflight blocked

The previous authority is retired and both entry reservations are consumed. The owner
authorized a **new** one-entry check on November 4; the prior allowance is not reused.
This check uses the existing FOREX.com demo account, one entry reservation, at most 0.01
lot, one position at a time and at most **0.10% of eligible equity** planned risk
(per-entry and cumulative). The percentage calculation and conservative equity basis
remain enforced; volume is reduced or the entry is refused if necessary.

Use a new isolated manifest and journals, never reset the old budget. Before activation,
perform fresh identity, flatness, clock/mapping, protective-order and authority checks.
Set a fixed 30-second entry window and a bounded management/reporting window, with no
extension or extra attempt. The exact UTC boundaries must be pinned before activation.
Require a fresh original and native quote within two seconds and clock uncertainty
within 100 ms. Preserve broker-confirmed SL/TP and the existing one-shot controlled
close/reconciliation behavior; no blind resend or refund after an uncertain outcome.

Success requires an independently verified entry/exit history, flat account, the same
running EA's `CLOSED` report and ACK, and completed drain without a recovery attachment.
Retire authority and disable trading afterward. Failure preserves all evidence and
requires reconciliation; it never silently starts another attempt. This is a short
execution-only check, not a 24-hour campaign, a complete fault-matrix pass or M1 acceptance.

The [authorized preflight evidence](../evidence/m2-one-entry-preflight-20261104.json)
records **57 read-only samples and zero eligible entries** over approximately one
minute. EURUSD spreads remained **5.1–5.5 pips**, above the existing **3-pip** limit;
quote-age upper bounds ranged from **1,508 to 32,341 ms**. A short candidate threshold
of 1,500 ms reserves transport headroom; the final original/native entry ceiling
remains 2,000 ms. No spread or freshness limit was relaxed. The host clock passed
its existing bound, and the isolated bounded EA compiled with zero errors/warnings.

This is a **blocked preflight**, not a failed order attempt or completed closure
acceptance. No activation, fixed entry window, authority or budget reservation was
started; no EA was attached and no order was sent. Independent postflight checks
confirmed unchanged broker history, flatness, disabled Algo Trading and all 69
preserved prior evidence files unchanged. The authorization was unused at that preflight; the November 5 attempt below consumed it.
CMC and AvaTrade were untouched. Same-session connected `CLOSED`/ACK/drain remains
unverified; synthetic closeout and the earlier recovery-assisted result remain
separate evidence. M1 gaps and the prohibition on a new 24-hour campaign remain.

#### Quote-capture diagnosis

The [capture diagnostic](../evidence/m2-quote-capture-diagnostic-20261104.json)
measured 30 read-only captures: median **27 ms**, maximum **55 ms**. Quotes were
already aged when the SDK returned them; these measurements do not establish
whether the age originates in broker timestamp accuracy, network delivery or the
terminal. Python capture overhead is not the principal observed delay.

A separate one-minute check with 100 ms sleeps between complete captures recorded
**429 samples and 11 eligible overlaps**, using the unchanged 1,500 ms candidate
headroom and 3-pip spread limit. Median capture time was 30 ms, maximum 85 ms.
One-second sparse monitoring can miss these brief opportunities. Readiness checks
should therefore use this finer cadence; neither the original broker timestamp nor
the final two-second entry rule changes. This is monitoring evidence, not an entry
permit or a same-period randomized comparison of polling cadences.

The initial desktop activation failed twice, so this November 4 diagnostic stopped
before attachment. The owner restored the window; the subsequent comparison and
one-entry attempt are recorded below, separately from that zero-order preflight.

#### November 5 actual one-entry outcome and shutdown fix

The [independent broker/native audit](../evidence/m2-one-entry-closeout-20261105.json)
verified one **0.01-lot** entry, broker SL/TP and one controlled exit, with a flat
account and no recovery attachment. Planned risk remained capped at **0.10% of
eligible equity**, per entry and cumulatively. Native admission recorded quote-age
upper bounds of **1,542/1,544 ms** and **89 ms** clock uncertainty. Algo Trading is
off, the listener stopped, the EA removed itself and authority is retired. The
reservation remains charged; no extra entry or new 24-hour campaign is authorized.
All 69 earlier evidence files and preceding broker-history records were unchanged.

**The connected closeout gate failed:** local reconciliation reached CLOSED, but
the backend received only PROTECTED. The terminal logged clock-sync uncertainty
above 100 ms near shutdown. When the clock was unverified, the host skipped state
publication; the empty outbox then incorrectly allowed `DEMO_DRAIN_COMPLETE_FLAT`.
That log line is not evidence that the required CLOSED/ACK gate passed.

Drain now requires the exact current CLOSED state/version to have a durable report
ACK. An empty outbox with an unpublished final state blocks shutdown. This also
blocks stale PROTECTED acknowledgements and lost/wrong CLOSED acknowledgements.
The [new isolated native run](../evidence/m2-native-clock-loss-closeout-20261105.json)
passed **143 checks**, including clock-loss/unpublished-close regression; earlier
142-check evidence is preserved. This offline fix does not convert the failed
connected attempt into a pass. M1 and full M2 qualification remain separate.

The [EA/Python comparison](../evidence/m2-native-quote-comparison-20261105.json)
completed after the owner restored FOREX.com. Across 556 assessments per symbol,
the native stream never had a newer timestamp than Python. New native samples had
median mapped age approximately **1.17 seconds**, with buffer flush medians of
39 ms (EURUSD) and 47 ms (USDCAD). This corroborates timestamp age before Python
processing; it does not identify broker/network causality or certify timestamp
accuracy. Both read-only publishers stopped with archived STOP records and trading
off; the [cleanup record](../evidence/m2-native-quote-cleanup-20261105.json) is separate
from the later authorized entry.

## Historical implementation stages

The following notes describe earlier versions and their retained evidence. Their
statements that activation was absent or trading was never enabled apply to those
historical stages, not the current explicitly authorized bounded build above.

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

[Source-pinned evidence](../evidence/m2-demo-execution.json) includes the full native
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
The [initial PR evidence](../evidence/m2-demo-execution-initial.json) remains intact;
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
At this historical stage, these were actual-order acceptance gates rather than
a 24-hour campaign, and PR #23 was still awaiting review. The current merged
outcome is recorded at the top of this document.

## November 4 order-gate preflight

The [retained preflight report](../evidence/m2-gate-preflight-20261104.json)
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

[Budget integration evidence](../evidence/m2-bounded-budget.json): **880 full
Python/PostgreSQL/loopback HTTPS tests passed, zero skips**, including 36 new
budget/publication checks. Lint and formatting passed. The regression used separate
fixture databases, verified unchanged Python sources and the original environment,
and made no broker calls. Native sources were unchanged; the earlier 69 native
checks remain evidence for their original source rather than this new Python budget.

## Native budget integration and resumed gate checks

The [native budget evidence](../evidence/m2-native-budget.json) records **85 native
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

[Percentage-budget evidence](../evidence/m2-percentage-budget.json): **895 full
Python/PostgreSQL/HTTPS tests passed with zero skips, and 90 native offline checks
passed**. Both native programs compiled with zero errors/warnings. This covers
percentage boundaries, equity scaling, conservative rounding, falling equity,
no budget growth from gains, immutable basis/rates on restart and retained expiry.
No broker calls or terminal deployment occurred.

## Entry-window drain and renewed percentage-gate preflight

The [entry-drain evidence](../evidence/m2-entry-drain.json) supersedes the timer-stop
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
