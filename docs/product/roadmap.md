# Trading lifecycle roadmap

Owner-approved direction, November 14, 2026: build a real AI-led trading agent for
**EUR/USD and USD/JPY**. Profit after costs is the objective, not an assumed result.
AI designs a strategy, historical evaluation tests it, demo validates it prospectively,
capped live measures real outcomes, and AI proposes a new version for validation.

Reuse the M0-M5 foundation. Start with one execution broker and one approved active
strategy version; other accounts remain isolated. This plan does not select a new
broker, enable failover or authorize provider calls, deployment or a new campaign.
**Current mode: local engineering and simulation; trading disabled.**

## Milestones and UI acceptance

| Stage | Deliverable and exit criteria | UI workflow the owner can verify |
| --- | --- | --- |
| **R0 - Consolidate foundation** | Canonical architecture, reuse map, prioritized gap register and explicit runtime authority. Exit when implementation versus qualification is visible and the overview is tested. | Overview shows mode, strategy state, milestones and blockers. Identify why trading is blocked without engineering logs. |
| **R1 - AI Strategy V1** | Versioned AI-authored hypothesis, input provenance, executable EURUSD/USDJPY rules, entry/exit/HOLD conditions, percentage risk and combined USD exposure limits. Pin model/prompt versions. Validate generated artifacts through reviewed schemas and implementations. | Create, question, revise, compare and freeze candidates. Show authorship and distinguish descriptive drafts from executable candidates. Freezing is not trading approval. |
| **R2 - Historical validation** | Point-in-time data, realistic base/stress costs, preregistered development/walk-forward/untouched holdout windows, benchmarks and uncertainty. Exit with reject/revise/eligible-for-paper evidence; insufficient evidence cannot pass. | Select frozen candidate and registered dataset, run experiment, inspect progress/errors, trades on charts, equity, drawdown, costs and windows. Explain verdicts; compare, resume and export. |
| **R3 - Integrated paper readiness** | Bind approved strategy to qualified inputs, deterministic risk, fixed EA and reconciliation. Close applicable M1 inputs, M2 fault and M3 data/cost gaps. Verify wrong identity, stale input, uncertain submission, loss of protection and recovery. | Separate EA/Python/MCP health, quote age, clock uncertainty, coverage and entry permission per pair. Explain fault vetoes and continued position protection. |
| **R4 - Prospective demo trading** | Frozen candidate under a predeclared authorized plan. Compare forward decisions/fills/costs with backtests. Retain eight weeks AND 100 closed trades per candidate plus economic/operational gates for unattended acceptance; this floor alone does not prove profitability. | Demo cockpit: sessions, approved controls, charts, HOLD reasons, positions/stops, USD exposure, reconciliation and forward comparisons. Label BROKER_DEMO versus simulation. |
| **R5 - Capped live validation** | Separate live authorization/account and percentage allocation; measure actual costs, slippage and drawdown. Suspend on breached mandate. Scaling needs an evidence-based authorization. | Unmistakable LIVE view, approved limits, exposure, costs, alerts and audited pause-entry/controlled-close controls. Inspect suspension and demo/live differences. |
| **R6 - Controlled AI improvement** | AI proposes a challenger with linked outcomes and change hypothesis. Repeat R1-R4 validation before promotion. Preserve incumbent, rejections and rollback. No live self-modification or risk escalation. | Review & Improve shows version differences, validation, promotion decisions and rollback. Suggestions cannot activate themselves. |

Implementation order: R0, integrated **Strategy + Research** (R1-R2), then R3-R5.
Versioning starts in R1; R6 closes the loop. Rejection returns a candidate to research.

## Definition of done for every milestone

- Usable UI integrated with the backend, not a mockup or API alone.
- Recorded/synthetic/simulation/demo/live labels and visible missing evidence.
- Progress, actionable errors, durable results, restart and relevant export behavior.
- End-to-end checks and a short reproducible owner walkthrough.
- Advisor explanations cite exact strategy/input/experiment/trade evidence.
- Engineering completion and operational/economic qualification have separate verdicts.
- UI controls cannot create broker authority or bypass risk.

## Migration and reuse

| Existing work | New role | Preserved boundary |
| --- | --- | --- |
| M0A-M0C | Shared persistence, isolation, risk, recovery and packaging | Preserve regressions and historical journals |
| M1 | R1 input declarations, R2 historical integrity, R3 qualification | [Open requirements](../engineering/m1-open-requirements.md) remain open |
| M2 | R3-R5 EA execution/reconciliation | Bounded demo closeout passed; full fault matrix remains open |
| M3 | R2 replay/cost/study engine | B01 remains REJECT_FOR_PROMOTION; [M3-Q1-Q4](../engineering/m3-research-closeout.md) remain open |
| M4 | R1 design, bounded selection, explanations and R6 analysis | No model broker/risk-policy/deployment authority |
| M5 / PR #63 | UI, runners, queues, durable model-call reservations | Fixture transport is not qualified provider access or profitability |
| M6 / M7 | R5 / R6 | Live and promotion gates remain mandatory |

The [previous roadmap](../history/roadmap-m0-m7.md) is historical, not a competing
implementation order. The [architecture specification](../architecture/specification.md)
retains detailed gates. The [R0 register](../engineering/r0-strategy-research.md)
tracks actual implementation and gaps.

## Scope discipline

Prioritize strategy viability and its complete workflow. Defer peripheral deployment,
additional brokers and polish. Use consolidated workflow PRs with fixed acceptance.
Never tune against an exposed holdout; reserve new evaluation data for later research.
Optional news may be omitted only by a registered variant; missing required inputs
block entry. Preserve the two-second entry ceiling and deterministic portfolio protection.
