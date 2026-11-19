# Trading lifecycle roadmap

Owner direction, revised November 18, 2026: build a real trading agent for
**EUR/USD and USD/JPY**, with profit after costs as an evaluated objective.
The sequence is **understand conditions → identify a setup at a known price level
→ wait for confirmation → validate economics and risk → execute under an approved
mandate → review outcomes**. AI researches and explains this process; a plausible
narrative is not evidence of an edge.

Keep R0–R6 identifiers and reuse the M0–M5 foundation. R0 is not being restarted.
This revision changes research priorities and future acceptance, not runtime code.
**Trading stays disabled; PR #65 stays unmerged.** It starts no backtest, broker
connection, model request, deployment or campaign. Existing risk limits, the
two-second original/native entry quote ceiling and clock requirements remain intact.

## Why the order changes

The earlier route began with AI proposals and executable indicator rules. It did
not separately require proof that a level was known before entry, that a pullback/
retest sequence happened, or that its invalidation fit the account's risk mandate.
The current `TREND_PULLBACK` kernel is an EMA recross; it does not implement a
support/retest setup. A preceding-range breakout is likewise not a breakout
followed by a confirmed retest.

The owner's gold examples motivate three research families. They do not expand
the instrument scope to XAUUSD or establish transferable parameters:

1. **First: trend pullback to known support/resistance.** Register trend context,
   level provenance, pullback, confirmation, expiry and structural invalidation.
   Test whether waiting adds value after costs.
2. **Second: range breakout followed by a retest.** A separate candidate after the
   first receives a bounded research disposition. Freeze the box before breakout;
   immediate and delayed retests are separate hypotheses, not pooled winners.
3. **Deferred: SuperTrend/RSI/volume filters and M5 scalping.** Each filter needs
   incremental evidence. M5 does not itself require scalping; quote-update counts
   do not establish consolidated volume. Gold parameters are not FX calibration.
   Partial exits/trailing stops are later exit variants.

Start development with EUR/USD, closed H1 context and closed M15 confirmation,
reusing available granularity. This is a tractable research choice, not an optimal
timeframe claim. USD/JPY is the second independent study; do not copy EUR/USD
thresholds, require it to succeed, or add independent P&Ls to claim a portfolio.
Evaluate sessions, event risk and costs per pair. Do not choose a session simply
because its retrospective P&L was highest.

## Milestones, decisions and UI acceptance

The UI column specifies acceptance still to be built where absent. It does not
claim those screens or economic results exist. Extend the existing separate pages
and carry the candidate/experiment context between them.

| Stage | Trading question and exit evidence | UI the owner can verify | Current position |
| --- | --- | --- | --- |
| **R0 — Reuse the foundation** | Is authority bounded and evidence traceable? Preserve storage, replay, risk, EA, advisor and negative results; expose remaining gates. | Overview distinguishes implemented capability, unqualified inputs and candidate eligibility. | Foundation/inspection available; preserve, do not rebuild. |
| **R1 — Define an observable setup** | Why might the opportunity exist, where is it valid, and what disproves it? Freeze one setup's point-in-time definitions, inputs, costs, control and finite experiment plan. Unsupported rules remain drafts. | Market & data shows dated context/coverage. Review charts show the pre-existing level, confirmation and invalidation. Step through successful, failed, expired and absent setups without future bars. | AI drafts/freeze/session tools exist; structural setup recognition and charts are missing. **Immediate focus.** |
| **R2 — Demonstrate economic evidence** | Does the setup survive realistic costs, unchanged risk and independent evaluation? Complete the bounded stages below. Rejection finishes a study, not the promotion gate. | Backtest chooses/checks period and data. Results show opportunities, no-trade reasons, trades, costs, net expectancy, uncertainty, session attribution and risk halts, with cutoff-aware charts. | Replay/results/revisions exist; no strategy has qualified. Structural setup and lifecycle sizing are not implemented. |
| **R3 — Verify operational readiness** | Can this exact candidate use its required data and execute safely on the chosen account? Close applicable M1 inputs, M2 fault cases, cost and recovery requirements. | Readiness separates EA/Python/MCP health, quote age, event coverage and entry permission; inspect veto and reconciliation failures. | Reuse bounded demo evidence; source/execution gaps remain. |
| **R4 — Verify prospective demo behavior** | Does the frozen candidate behave as expected prospectively? Use a separately authorized plan. Existing unattended floor remains **eight weeks AND 100 closed trades per candidate**, plus economic/operational gates; this floor does not prove edge. | Actual broker fills, protection, session, planned versus realized risk/costs and backtest divergence; distinguish demo from simulation. | No strategy campaign authorized or started here. |
| **R5 — Validate capped live economics** | Does the qualified release survive real execution under separately authorized percentage limits? Suspend on mandate breach; scaling needs evidence and authorization. | Clearly labeled LIVE view, costs/exposure, qualification, suspension and approved pause/close controls. | Gated; no live activation. |
| **R6 — Improve through challengers** | What measured failure or opportunity justifies a change? AI proposes a hypothesis; the challenger repeats R1–R4 before promotion. | Improve compares parent/challenger, change rationale, matched evidence, rejected variants and rollback. | Diagnosis/revision tools exist; qualified promotion remains open. |

R6-style diagnosis already helps R1/R2 research; it does not wait for LIVE. Active
rules never self-edit. The owner sets objectives, risk and stage authority, reviews
evidence and authorizes demo/live transitions. The agent handles data selection,
bounded research, progress and explanations without asking the owner to select
every file, date or indicator. Ordinary valid trades within an approved operating
mandate do not require repeated per-trade confirmation.

## R1: the setup contract

Before its first economic replay, each candidate must freeze:

| Element | Required meaning |
| --- | --- |
| Context | Pair, named session/timezone, trend/range definition, volatility/cost conditions and dated calendar/event policy. Unknown is distinct from favorable. |
| Key level | One derivation rule, zone tolerance, source bars, first-known/confirmation time and expiry. Future-confirmed pivots cannot be used early. |
| Sequence | Ordered pullback/retest states, definitions of weakening/confirmation and maximum wait. Numeric definitions replace “small candle” or similar subjective prose. |
| Invalidation | Structural break, changed context, missing required input or expiry. Retired setup IDs cannot silently reactivate. |
| Entry | Completed-bar confirmation followed by the next eligible bid/ask; signal expiry and the unchanged two-second native quote check remain separate. |
| Protection/exit | Structural invalidation plus predeclared volatility allowance, fixed target/time exit, rounding and broker feasibility. Begin with one fixed 2R research exit; 2R is an assumption, not a guaranteed payoff. |
| Risk compatibility | Lower of frozen candidate/dataset/account ceilings, costs, projected current-to-stop exposure and other reservations. Minimum lot infeasible means HOLD. |
| Comparison | One primary thesis, one specified control, no-trade comparator, falsification criterion, exposure ledger and finite study end. |

Illustrative sequence: `WATCHING → LEVEL_KNOWN → PULLBACK → CONFIRMED`.
Any prerequisite can instead yield `INVALIDATED`, `EXPIRED` or `DATA_BLOCKED`.
Confirmation is not permission: calendar, cost, quote and deterministic risk checks
may still produce HOLD. Setup events and execution reservations have distinct IDs;
the same bar/setup cannot create duplicate entries after refresh or restart.

Freeze one level method and confirmation definition before outcomes. Record every
opportunity and veto, including breakouts that never retest. Do not redraw levels,
count only fills or add another indicator to rescue a loss. Verify definitions on
a chronological chart audit before an economic study.

## R2: bounded research with a stopping decision

**R2A — Feasibility and meaning.** Use exposed development data to inspect setup
occurrence, coverage, spread relative to stop/target and opportunity count by session.
Pin required calendar/news inputs; verified absence and missing data are different.
Descriptive excursions are not tradable returns. Resolve the known lifecycle-sizing
incompatibility under existing caps before claiming a governed comparison. Stop if
the setup cannot be observed reliably, cannot fit minimum size/risk or lacks cost
headroom.

**R2B — Governed development comparison.** Freeze candidate, engine, dataset,
period, costs, primary/control rules and stopping criteria. The first control removes
only the registered confirmation requirement at the same level touch, retaining
the opportunity universe and risk/exit policy. Different entry prices/times and
consequent sizes remain visible; arms are simulations, not concurrent broker
mandates. Record no-trade outcomes as well as fills. No parameter sweep or automatic
retry with altered rules follows a loss.

Run actual stop/target/time-exit paths with bid/ask, dated commission, slippage
stress, financing where applicable and unchanged persistent halts. Report realized
net R against frozen initial planned risk, net expectancy and uncertainty, drawdown,
adverse/favorable excursions, holding time, costs/exposure and preregistered session/
event attribution. Separate structural invalidations from risk, data and execution
failures. A 2R target or better win rate alone is not acceptance.

**R2C — Independent evaluation.** Freeze the surviving specification before
chronological validation/walk-forward and a once-used untouched final evaluation.
Choose independent day/event blocks and a confidence method before outcomes;
account for all tried variants, not ticks as independent samples. Require positive
conservative net-expectancy evidence and predeclared cost/robustness tests within
unchanged risk. Qualify joint capital and USD exposure before claiming a two-pair
portfolio. A separately qualified one-pair release may proceed while the other
stays disabled, under an explicit approved scope.

Every stage issues **REJECT**, **INSUFFICIENT_EVIDENCE**, or its actual stage pass.
Only all required economic/input gates allow **ELIGIBLE_FOR_PAPER**. A failed idea
is shelved; insufficient evidence identifies the exact gap and a bounded evidence
requirement. Do not extend a campaign or sample until a pass appears. New variants
require a registered thesis and preserve their parent. A completed study may conclude
no trade; it cannot authorize the next operating stage through a negative result.

The agent chooses a period from opportunity frequency, regimes and available data,
then pins it before outcome queries. A fixed 126-session request does not guarantee
adequacy. Existing exposed training stays development data. Do not open a holdout
to debug rules, or fill historical event gaps with an AI model's later knowledge.

Candidate-required input/cost checks move into R1/R2, not only R3. Broader M1
production reliability remains separate. Missing required calendar/news or
uncalibrated broker costs permit labeled exploration, not qualified performance.
Optional news may be removed only through a registered variant, never silently
after missing data blocks a run.

## First implementation PR after this design

Deliver **one offline trend-pullback workflow for EUR/USD** using the existing
research/UI/storage stack. This update does not implement or launch it.

- Add one reviewed structural-setup contract and deterministic sequence: level
  provenance, confirmation, invalidation, expiry and deduplication. Do not relabel
  the existing EMA recross as support/retest recognition.
- Add the restrictive lifecycle admission bound from the
  [risk assessment](trading-research-assessment.md#resolve-the-strategyrisk-conflict).
  Preserve caps, giveback semantics and persistent halts. Verify fixed-target
  feasibility, costs, rounding, reservations and minimum-lot HOLD. Unbounded
  trailing exits cannot borrow this finite-target proof.
- Record every setup, rejected opportunity, structural exit and governance veto.
  Keep opportunity diagnostics separate from governed account returns.
- Extend Review/Backtest/Results with a cutoff-aware annotated chart, setup timeline
  and reason to wait; retain candidate context, export and reload.
- Prove causality/boundaries on synthetic paths, then a preregistered short exposed
  development slice with matched control/costs. Record limitations; a short slice
  cannot claim full-period or independent-holdout acceptance.
- Deliver one consolidated report with failures, data gaps and separate engineering/
  economic verdicts. No demo/live activation or automatic promotion.

Done means the owner can inspect **why an opportunity was watched, confirmed,
rejected or invalidated**, verify only then-available data was used, and trace
risk and costed outcomes through the existing engine. An absence of setups or a
losing result is valid evidence, never a profitable gate. Exclude gold, extra brokers, M5 scalping,
SuperTrend/RSI/volume stacks, partial exits, deployment expansion, cosmetic-only work
and legacy development-data migration.

## Evidence carried forward and delivery discipline

- [Trading assessment](trading-research-assessment.md): EU-FIX-01 stays shelved;
  JP-POLICY-01 stays data-gated. The new hypotheses do not revive those results
  or prove their own profitability.
- Reuse M0A–M0C storage/isolation/risk and M2 execution/reconciliation. Preserve
  bounded demo closeout; full fault-matrix acceptance remains open.
- [M1 gaps](../engineering/m1-open-requirements.md) and
  [M3-Q1–Q4](../engineering/m3-research-closeout.md) stay tracked. B01 remains
  **REJECT_FOR_PROMOTION**. Preserve broker/provider failures and finished runs.
- Reuse M4 advisor/model records, M5 UI/runner/dispatch and PR #65 proposal/replay/
  revision plumbing. They do not certify a strategy. The
  [R0 register](../engineering/r0-strategy-research.md) retains its historical scope.
- Every milestone needs usable UI, backend evidence, error/restart/export checks
  and synthetic/historical/simulation/demo/live labels. Display setup validity,
  economic evidence and operating readiness separately.
- Use one complete decision workflow per implementation PR. End each study with
  a disposition; avoid open-ended feature/parameter loops. No qualified candidate
  is a legitimate research outcome, not permission to trade anyway.

The [architecture](../architecture/trading-lifecycle.md) defines authority and
failure behavior. The [M0–M7 roadmap](../history/roadmap-m0-m7.md) remains history;
existing safety and unattended gates are not reduced by this revision.

Before operational strategy PAPER/LIVE records exist, do not build legacy data
migrations. Preserve protected evidence; fresh disposable development stores are
permitted. Current-version persistence/recovery/idempotency remain necessary.
Establish operational backups and upgrade/rollback before demo/live activation.
Keep root/broker checkouts and campaigns isolated; work in the background without
changing the owner's running applications.
