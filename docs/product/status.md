# Current product status

Research baseline: merged PR #34 (`93fb4c5`, November 5, 2026). M3's completed
research scope is closed by owner decision; qualification gaps remain tracked.
This does not change execution authority or qualify another campaign.

## Implemented

M0A–M0C provide the Python/PostgreSQL foundation, separate PAPER/LIVE credentials,
append-only records, deterministic offline simulation, risk reservations, protective
management, restart reconciliation and portable archive/restore profiles.

The repository also contains read-only MT5 observation, EA quote streaming,
calendar/news filtering and journaling, manual BLS upload with reminders, optional
native MCP calendar import, and a fixed EA with deterministic execution controls.
The M5 [read-only dashboard](../guides/dashboard.md) now provides a local browser
workspace for offline records, EA/Python/MCP timing, cited English/Chinese evidence
chat and isolated manual BLS uploads. Optional bounded model inspection, current
broker receipt views, simulator-only administration, background inspection and
HTTPS owner sign-in are implemented. A [pinned inspection-only deployment profile](../engineering/m5-deployment-readiness.md) validates local artifacts, TLS and journal recovery before explicit launch. The UI does not attach broker terminals or
expose broker order controls. Actual remote deployment and unattended PAPER remain
unqualified. Historical execution does not imply current positions.

The [incremental PAPER runner](../engineering/m5-paper-runner.md) is implemented
for simulation only: frozen B01 research signals, scripted selection, three isolated
risk/execution arms, restart-safe evidence and dashboard receipt exports. It has no
broker/live-model adapter and does not qualify B01 or start a PAPER campaign.

## What the demo proved

The [PR #25 fixed-build result](../evidence/m2-one-entry-closeout-20261105-02.json)
is **PASS_BOUNDED_SAME_SESSION_CLOSEOUT**: one 0.01-lot entry, broker SL/TP,
one controlled exit, durable CLOSED/ACK and completed drain in the same EA,
without recovery. Quote ages were 1,797/1,798 ms; the 0.10% per-entry/cumulative
risk limit remained. Authority is retired, account flat, Algo Trading off.
The preceding failed closeout and PR #23 recovery-assisted result below remain
historical evidence. No further entry is authorized by this status page.


[PR #23 evidence](../evidence/m2-bounded-demo-20261104.json) records one actual
FOREX.com demo EURUSD entry, confirmed protection and a controlled exit. Independent
broker history confirms closure and flatness. A separate hard-disabled build recovered
the final `CLOSED` report after an empty-position fingerprint defect. This is
**EXECUTION_ONLY_VERIFIED_WITH_READ_ONLY_RECOVERY**, not unattended first-pass success.

The approved percentage limits remained intact. Both authorized entry reservations
were consumed, including a definite pre-submission rejection; a rejected attempt does
not refund authorization. Original authority is retired. Test EAs/listeners were stopped
and Algo Trading disabled at verification. This document is not a live terminal monitor.

## Current development milestone

Current work is **M5 operating UI and unattended PAPER qualification**. M4 offline
engineering is implemented after the owner closed the completed M3 research scope. The [M3 closure](../engineering/m3-research-closeout.md) retains M3-Q1–Q4
qualification gaps and B01's REJECT_FOR_PROMOTION verdict. The
[M4 consolidated implementation](../engineering/m4-completion.md) provides authenticated
local access, bounded candidate/HOLD proposals, deterministic simulator risk and
execution, evidence-backed explanations, qualified-memory filtering and simulated
administrative commands. Its acceptance report separates software checks from real
model/strategy quality. M1 [open requirements](../engineering/m1-open-requirements.md)
still block connected strategy PAPER. Trading remains disabled.

## Remaining gates

- **M1:** broker data and required USD/EUR/JPY calendar/news coverage, timeliness and
  reliability remain unqualified. Failed and owner-stopped campaigns retain their verdicts.
- **M2D:** bounded first-pass closeout is verified; the complete connected fault matrix remains
  open. The [closeout evidence](../engineering/m2-demo-execution.md#closeout-verification) now verifies
  the complete native close/report/ACK path without restart, plus backend replay. The bounded execution gate keeps M1 gaps
  separate; it does not clear them.
- **M3:** [offline B01 baseline and replay](../engineering/m3-baseline.md) now has
  simulator/risk integration, synthetic lifecycle evidence and a
  [first historical pilot](../engineering/m3-historical-data.md), followed by a
  [full-session study](../engineering/m3-session-study.md): six sessions, 713,826 ticks,
  14 closed simulated trades and all sessions flat. Both holdout pairs lost after
  modeled costs; historical economic acceptance remains open.
  The [M3 completion checklist](../engineering/m3-completion.md) records the completed
  multi-fold evaluation and verdict, with source/cost qualification still open. Independent
  numerical comparison passes 36 synthetic cases; this is not terminal qualification.
  The [input/cost audit](../engineering/historical-input-costs.md) checks all retained
  January ticks and records spread distributions and demo fees. Historical fee terms,
  financing rates, representative slippage and source availability remain unqualified.
  The [registered multi-fold evaluation](../engineering/m3-walkforward.md) adds
  three advancing origins and a separate January 30 outcome holdout: 16 verified
  flat sessions, 42 simulated closed trades across base/stress scenarios, and
  **REJECT_FOR_PROMOTION** under the frozen research screen. This completes that
  registered comparison, not full M3 cost/availability qualification. No retuning
  or further study run is implied by the result.
  [Broker-aware replay costs](../engineering/broker-aware-replay-costs.md) now support
  per-fill USD-notional commissions and dated signed rollover postings in the USD
  simulator. The legacy cost model and B01 verdict are unchanged; synthetic tests
  prove integration, not historical account-cost calibration.
- **M4 and later:** consolidated offline engineering implementation is complete;
  remote deployment, live dashboard integration, strategy quality, unattended PAPER and capped LIVE
  remain gated. See the [M4 acceptance boundary](../engineering/m4-completion.md).

Broader M2 acceptance must preserve the historical closure recovery and reconcile
existing evidence for lost replies, restart while exposed, partial fills, rejected
protection, backend/database loss and closed-market exits. A new broker-order attempt
requires fresh bounded authorization; no further order or 24-hour run is started by
this documentation or repository cleanup.

See [demo execution details](../engineering/m2-demo-execution.md),
[broker conclusions](../history/broker-campaign-conclusion.md) and
[provider conclusions](../history/provider-campaign-conclusion.md).

### Read-only monitoring continuation

The dashboard also supports explicitly bound offline telemetry-file inspection,
durable sampled incident transitions, resumed inspection state, saved advisor answers,
upcoming manual-calendar events and M4 lesson eligibility at the snapshot cutoff.
Missing/invalid/stale telemetry remains unavailable; old evidence is preserved.
This is not a connected collector, continuous monitoring campaign or unattended
PAPER qualification. See the [dashboard operating guide](../guides/dashboard.md).

The evidence workspace adds searchable projected records, explicit-reference trails,
full retained-incident search with stable pagination, and hashed bounded inspection
report downloads. It exposes gaps rather than synthesizing missing execution or
learning evidence; all routes remain authenticated and read-only with respect to
trading. M5 unattended PAPER prerequisites and observation gates remain unchanged.


The consolidated [M5 engineering matrix](../engineering/m5-offline-acceptance.md)
adds historical operating/model-usage summaries, explicit qualification gates,
matched offline comparison validation and one source-hashed acceptance entry point.
Its current matrix records completed read-only integration and the remaining broker administration, evaluation and deployment gates; this
is not full M5 completion. Historical counts do not establish current account
performance, and synthetic paired results do not qualify a strategy.


### M5 read-only integration

The dashboard supports opt-in bounded M4 citation selection with durable call
budgets and retry-safe receipts; offline matched-study uploads; sampled in-page
incident alerts; optional loopback TLS; and an explicitly bound, read-only
PostgreSQL broker-observation panel. Broker samples remain historical, with current
positions unknown and entry readiness false. No MT5 control, order route or strategy
activation is added. See [setup and limits](../guides/dashboard.md#optional-read-only-integrations).
Full M5 still requires current reconciliation/admin/deployment acceptance, eligible
candidates and the unchanged prospective observation gates. B01 and M1 gaps remain.


### M5 simulator operator and local recovery

Explicit optional operator mode now exposes M4 simulator pause/resume/owned-close/
flatten-halt and reconciliation through separately authenticated preview/confirmation.
It preserves the original two-second checks, state versions, durable uncertainty and
existing risk gates. No broker order or strategy-entry route exists. Verified stopped
workspace backup/restore retains evidence and removes model/operator authority from
the copy. Remaining M5 work includes current broker reconciliation and administrative
acceptance, remote deployment/access, continuous delivery and qualified prospective
matched candidate evaluation; full M5 remains open.


### M5 inspection service and authenticated access

Browser-independent inspection, durable local incident delivery/acknowledgment and
optional certificate-authenticated HTTPS inspection are implemented. Remote mode
requires mutual TLS plus the viewer capability, has no operator route authority,
and is tested only through isolated loopback handshakes. No remote deployment,
external notifications, collector startup or strategy operation is implied. The
qualification gaps and B01 verdict remain unchanged.


### M5 registered evaluation receipts

The [matched-study receipt workflow](../engineering/m5-matched-workflow.md) now
preserves frozen artifact bytes and chronological observation, decision and outcome
receipts in an isolated journal. Corrections, idempotent retries, restart, deadline
checks and dashboard rollback detection are implemented and tested synthetically.
This supplements offline study upload; it does not execute strategy/model arms or
start a prospective campaign. The remaining M5 operating/economic gates are unchanged.


### M5 bounded alert delivery

An opt-in [HTTPS alert outbox](../engineering/m5-alert-delivery.md) now adds durable
send reservations, exact receiver acknowledgements, uncertain-send recovery and
separate dashboard delivery status. It is disabled by default and tested only with
synthetic transports and a local TLS receiver. Real-recipient delivery/deployment
acceptance remains open; this adds no trading authority or campaign.

### M5 simulation runner operations

The [bound source queue and direct dashboard view](../engineering/m5-runner-operations.md)
now provide durable input acknowledgements, restart recovery and audited stop for the
local simulation runner. Source qualification, production model integration and all
prospective operating gates remain open; no trading or campaign has been enabled.

### M5 source inspection and recovery evidence

[Queue-aware inspection and verified paired archives](../engineering/m5-runner-recovery.md)
are implemented for the simulation runner. Restore is inspection-only; prospective
source/model qualification, connected operating acceptance and full M5 remain open.

### M5 normalized simulation inputs

The [typed source adapter](../engineering/m5-input-admission.md) now feeds retained
market/bar/calendar/news evidence through the queue and simulator with shared safety
checks and admission-time expiry. Dashboard channel labels are asserted provenance,
not live connections or provider qualification. Trading remains disabled.

### M5 recorded model-selection replies

The runner now [validates recorded model replies](../engineering/m5-recorded-selectors.md)
and shows reported latency, token usage and known/unknown model costs. Tests use only
synthetic replies; no provider calls or production model qualification are implied.
