# Trading research assessment — November 18, 2026

## Decision

Complete the trading assessment before extending the application. Retain the
current-to-stop risk definition and every existing limit. Resolve the predictable
strategy/risk conflict through **smaller entry sizing that reserves room for a
winner to reach its planned exit**, rather than increasing risk limits or clearing
halts. This is an analytical design decision, **not an implemented fix**.

Research two explicit hypotheses: EUR/USD post-London-fix drift, and USD/JPY
post-BoJ-announcement continuation conditional on observed rate/price agreement.
Both are untested adaptations of published mechanisms, not profitable strategies.
EUR/USD first needs a cost-feasibility screen; USD/JPY first needs suitable
point-in-time rates and announcement data. Neither is ready for paper trading.

Scope: source review, retained-evidence arithmetic and research specifications.
No new replay, provider-model request, broker observation, order, campaign, Docker
restart or production-code change. Trading stays disabled; PR #65 stays unmerged.
M1 gaps and B01's rejection remain unchanged. The sources reviewed below do not
establish that either proposed entry rule has predictive power today.

## What the existing studies actually establish

| Finding | Meaning for the next decision |
| --- | --- |
| EUR/USD: two trades, net -3.522165… in simulated USD; permanent aggregate-risk halt on May 27 | Too few trades to infer signal quality; resolve sizing/management compatibility first |
| USD/JPY: 23 trades, net -28.986978…; aggregate-risk halt on June 12 | Also a truncated trading opportunity set; its precise trade-level cause has not been independently reconstructed here |
| EUR/USD 20-to-24-bar comparison: identical trades, P&L and halt | This parameter change did not address the binding constraint; do not repeat the sweep |
| Millions of ticks were processed after the halts | Processing coverage is not equivalent to active strategy observation over that period |
| Requested 126-session study remained `DATA_REQUIRED`; validation/holdout unopened | Do not describe this as completed full-period strategy validation; November 16 was missing from acquired sources |
| Session groups each have fewer than 20 closed trades | Attribution is useful, but it does not identify a profitable session |
| Costs, calendar/news and independent holdout qualification remain open | An engineering pass cannot authorize an economic promotion |

Evidence: [full-history outcome](../evidence/full-history-remediation-20261118.json),
[comparison](../evidence/eurusd-24bar-comparison-20261118.json),
[halt reconstruction](../evidence/shared-risk-halt-20261118.json),
[session report](../engineering/session-aware-research.md), and
[cost assessment](../engineering/retained-cost-calibration.md).
Do not overwrite these records. The `integrity_halt` field in these results also
represents a documented risk-limit breach; it does not by itself prove corrupt data.

## Resolve the strategy/risk conflict

### Cause and authority

The [governor](../../src/fx_talanta/risk/governor.py) sizes entry-to-stop loss plus
costs and entry equity charges. Its ongoing `exposure` function instead measures
current-liquidation-to-stop loss plus incremental exit costs. The
[gateway](../../src/fx_talanta/gateway/offline.py) persistently halts on an aggregate
breach and attempts protective closure. These meanings agree with the
[architecture](../architecture/specification.md#sizing).

For a fixed stop below a long entry, unrealized profit increases the amount of
current equity that could be lost before that stop. The entry sizer does not
currently reserve the whole planned increase. This is a strategy/admission design
mismatch, not a demonstrated arithmetic defect. It also applies to a short with
the corresponding sign changes.

The retained EUR/USD trigger has:

- Entry-to-stop capital loss: 7.12 USD.
- Unrealized profit: 2.08 USD.
- Incremental exit allowance: 0.88 USD.
- Current-to-stop exposure: **7.12 + 2.08 + 0.88 = 10.08 USD**.
- Bound: **0.10% × 9,996.95792198… = 9.99695792… USD**.

With the recorded balance and unchanged stop/costs, the uncapped-equity branch
crosses the boundary when unrealized profit exceeds approximately **1.996875 USD**.
The preceding observed profit was 1.92; the triggering profit was 2.08.
The new [arithmetic receipt](../evidence/trading-risk-assessment-20261118.json)
checks this against retained values. Dollar amounts explain an old observation;
they are **not new fixed-dollar budgets**.

This study's 0.10% aggregate cap is tighter than the architecture's generic 0.50%
demo default. Never substitute the generic default to obtain a pass. All effective
limits must still be the minimum of the frozen candidate, dataset and mandate.

### Chosen design: reserve exposure along the planned trade path

Add a restrictive admission bound in future implementation, in addition to all
existing checks. For an isolated position with a fixed stop and finite target:

```text
L(v) = entry-to-stop loss at volume v
T(v) = entry-to-target profit at volume v
C(v) = incremental exit-cost allowance
H(v) = additional exposure allowance for modeled overshoot, costs and conversion
B    = conservatively projected exposure of other positions and reservations
Emin = conservative eligible-equity floor for the modeled trade lifecycle
a    = unchanged effective aggregate-risk fraction

B + L(v) + T(v) + C(v) + H(v) <= a × Emin
```

Use the maximum over the modeled path, not just its endpoint, when conversions,
costs or other exposures vary. For the simple constant-conversion, fixed-stop
case with target `k × L`, the main term is `(1+k) × L`. Sizing only for `L`
is therefore insufficient. Choose the smaller of this new size and every existing
governor limit, then round down to the broker increment. Below minimum lot means
HOLD. Do not widen the stop, increase allocation, add positions or change the target
to force a trade through.

`Emin` must account for entry charges, possible losses and other allowed exposure;
it must not assume that expected profits increase the budget. For USD/JPY, yen P&L
must be converted along the path using adverse conversion bounds. Linear EUR/USD
arithmetic cannot be reused as a USD/JPY proof. Unknown costs/conversion bounds
prevent qualification; do not silently assign zero.

Illustration only: with a 0.10% aggregate cap, a 2R target consumes roughly three
times initial stop risk before costs. Initial stop risk around 0.03% would leave
roughly 0.01% for other modeled exposure/cost allowance; it is not a universal
recommended trade size. Using the retained EUR/USD geometry, an **assumed** 2R
target, an **assumed** equity floor of 9,990 and 0.01% extra headroom, 0.03 lot
uses 8.34 of 8.991 USD capacity; 0.04 lot uses 11.12 and fails. This is not a
counterfactual replay, proof that the original trade would have succeeded, or
permission to trade those sizes. The original target ratio was not inferred.

The extra bound does not replace the actual risk reservation or governor. Avoid
double-counting the same pending reservation while checking projected peak exposure.
Later entries must respect previously admitted positions' projected needs too;
initial research should remain one-position-at-a-time within any tighter mandate.

### Why not the apparent alternatives?

| Alternative | Decision |
| --- | --- |
| Raise aggregate risk or exclude unrealized giveback | Rejected: changes the owner's mandate/definition |
| Automatically reset the halt or restart each day | Rejected: falsifies the continuously governed strategy and erases a persistent restriction |
| Tighten the stop as soon as profit appears | Defer as a separate hypothesis: changes the payoff distribution and depends on confirmed stop modifications |
| Pre-emptively close before consuming the limit | Potential later protective rule, but it truncates winners; cannot be represented as the original strategy |
| Smaller initial volume with planned lifecycle headroom | Preferred first design: preserves signal, stop, target and risk definition |

No finite buffer guarantees a hard loss ceiling through gaps or failed execution.
A target may be skipped or a close rejected; the existing governor and emergency
handling remain authoritative. Overshoot and evaluation/exit sequencing must be
tested before calling the admission change operationally resolved. No new guarantee
or automatic recovery is introduced by this assessment.

## FX evidence and its limits

| Source | Finding used here | What it does not establish |
| --- | --- | --- |
| [Bank of Canada, Krohn/Mueller/Whelan, 2021, sections V.E and appendix](https://www.bankofcanada.ca/wp-content/uploads/2021/10/swp2021-48.pdf) | Historical dollar strengthening before fixes and reversal afterward; their cost analysis often removes profits at full indicative spreads, with narrow windows especially difficult | Current retail net profitability; our exact times, stops and target; executable broker fills |
| [LSEG WMR benchmark description](https://www.lseg.com/en/ftse-russell/benchmarks/wmr-fx-benchmarks) and [methodology](https://www.lseg.com/content/dam/ftse-russell/en_us/documents/ground-rules/wmr-fx-methodology.pdf) | Identifies the London 16:00 benchmark and the surrounding sampling convention | Access to benchmark pricing as an executable fill; trading entitlement or alpha |
| [BoJ, Ikkatai/Kawamoto/Sakura, 2024](https://www.boj.or.jp/en/research/wps_rev/wps_2024/wp24e23.htm) | Dollar-yen policy responses are state-dependent; expectations channels can matter more than a simple rate-differential explanation | Predictable continuation after a 30-minute blackout; higher rates mechanically imply a profitable yen trade |
| [BIS Bulletin 90, August 2024](https://www.bis.org/publ/bisbull90.htm) | Leveraged unwinds amplified a macro shock and currency volatility | A reliable real-time carry-position measure or a rule that predicts the next unwind |
| [BIS FX execution study, 2019](https://www.bis.org/publ/qtrpdf/r_qt1912g.htm) | Execution is fragmented across venues/dealers | Our feed represents consolidated volume or global order flow |
| [Bailey et al., backtest overfitting, 2015](https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf) | Selecting among many historical configurations creates misleading winners | A fixed trade count or one holdout guarantees a genuine edge |

Sources were reviewed November 18, 2026. Published historical associations motivate
tests; they do not certify persistence. No cited strategy's returns are used as our
expected returns. The following parameters are new preregistration proposals,
not parameters established by those papers or optimized on our results.

## Hypothesis EU-FIX-01 — EUR/USD post-London-fix drift

**Question:** Does the post-fix decline in dollar demand leave enough subsequent
EUR/USD appreciation to pay our actual execution costs? The proposed mechanism
is benchmark-related intermediation, not an EMA crossing. The strongest rival
explanation is that observed drift is fully absorbed by spread/slippage or has
decayed since publication. Test cost feasibility before building an execution rule.

| Specification | Proposed primary test |
| --- | --- |
| Decision time | 16:05 Europe/London on a verified fixing/business day; apply historical DST and holidays |
| Direction | Long EUR/USD; no short mirror chosen after seeing results |
| Entry | First eligible executable ask within 60 seconds of decision; two-second native quote ceiling and existing clock, spread and all other gates unchanged |
| Stop | 1.5 × simple ATR(14) of completed M15 bars through 15:45 London; outward native tick rounding; reject invalid broker distance |
| Target | 2 × actual rounded entry-to-stop distance; required lifecycle sizing bound |
| Time exit | 18:00 Europe/London, or earlier protective/mandated exit; no overnight holding |
| Calendar | Existing ±30-minute affected-currency high-impact blackout; skip if a known event's blackout intersects planned holding window; missing required coverage means HOLD |
| Sampling | At most one entry per eligible day; count every no-trade day and its reason |
| Comparators | Cash/no trade; opposite direction at the same time and same rules as a diagnostic control; price drift without stops as a non-tradable mechanism diagnostic |

These timings deliberately avoid attempting to execute at the benchmark itself.
They are an adaptation, not a replication of the paper's longer holding windows.
Do not borrow the paper's returns or spread discounts. The original paper's data
extend through 2019; the current 2026 slice alone cannot establish persistence.

Required inputs: timestamp-verified bid/ask, business/fixing calendars, point-in-time
EUR/USD events, dated costs and a mapping to our intended broker. Do not use mid-price
fills or halve spreads to rescue the idea. Report the break-even incremental cost
after actual bid/ask, commission and financing; if plausible slippage consumes it,
reject this candidate before further implementation.

**Falsification:** reject for deployment if net expectancy is nonpositive on the
registered independent evaluation, loses its margin under the predeclared cost
stress, or depends on a few event days. If uncertainty spans zero, label it
insufficient evidence rather than a pass. Opposite-direction parity weakens the
specific dollar-reversal explanation. Month-end and ordinary-day attribution is
diagnostic; selecting only winning dates becomes a new registered hypothesis.

**Current decision:** cost-feasibility research candidate only. The engine cannot
faithfully express a 16:05 fixing rule as one of its existing two trend kernels.
Do not silently map it to a generic breakout or build it before the cost screen.

## Hypothesis JP-POLICY-01 — USD/JPY conditional post-policy continuation

**Question:** After a scheduled BoJ decision, does agreed rate/FX repricing continue
after the mandatory blackout, or has the information already been fully priced?
The null is immediate adjustment: waiting removes the advantage. Rate/FX agreement
is a proposed proxy for coherent repricing, not an identified structural policy
shock. BoJ evidence explicitly cautions against a simple rate-differential story.

| Specification | Proposed primary test |
| --- | --- |
| Event universe | All scheduled BoJ monetary-policy decisions in the registered period; no retrospective selection by surprise magnitude or profitability |
| Decision time | First completed M15 boundary strictly later than release +30 minutes, within 09:00–16:00 Asia/Tokyo; otherwise skip |
| Required rates | Same-maturity USD and JPY two-year OIS quote series, synchronized at release -5 minutes and +30 minutes, each available by cutoff; maximum quote age and pair timestamp mismatch 60 seconds for these rate observations |
| Rate variable | Change in USD OIS minus JPY OIS over that window; this is a proposed expectations proxy, not a claim of causal identification |
| Direction | Positive differential change and positive USD/JPY return: long; both negative: short; zero, disagreement or missing observations: HOLD |
| Entry | First eligible executable FX quote within the unchanged 60-second signal expiry; original two-second FX rule still applies independently of rate-data timestamps |
| Stop / target | 1.5 × simple ATR(14) from complete M15 bars ending no later than release -5 minutes; target 2R; lifecycle risk sizing |
| Exit | Earlier of two hours after entry, 16:00 Tokyo, or a protective/mandated exit |
| Known additional events | Reject planned holding overlap with ±30-minute decision/press-conference/other affected-currency blackouts; do not assume a decision's release ends the communication cycle |
| Comparators | Same event/time price-direction-only rule without rates; opposite FX direction as a diagnostic; cash/no trade |

The rate agreement must add value over the price-only control after costs; otherwise
the added data dependency is unjustified. Pre-event volatility may be used for
reported attribution, but no volatility cutoff is fitted after reading results.
Unscheduled intervention and carry unwinds remain tail risks, not events a calendar
can guarantee to avoid. Post-event revisions, ex-post surprise labels or an LLM's
knowledge of subsequent prices cannot enter the historical decision.

**Falsification:** reject deployment if delayed net expectancy is nonpositive,
rate confirmation offers no independent advantage, or costs/uncertainty remove
the effect. Too few independent policy meetings is insufficient evidence, even
if thousands of ticks or both long/short outcomes are available. Multiple years
and distinct policy environments are necessary to evaluate this infrequent idea;
do not invent extra daily trades to meet a count target.

**Current decision:** data-gated research hypothesis, not an implementation task.
The reviewed retained inputs do not establish synchronized historical OIS or
decision/press-conference availability. Daily yields and ordinary news headlines
cannot substitute for those intraday observations. If suitable permitted data
cannot be obtained economically, shelve this exact hypothesis rather than rename
a price-only strategy as macro-informed. No paid acquisition is authorized here.

## Data, experimental design and stopping decisions

1. **Use existing data for development only.** Retain all prior exposure markers.
   Unopened files are not automatically an independent holdout, and a period
   already discussed in this chat cannot be advertised as wholly unknown to AI.
   Current receipt timing is modeled, not measured execution latency.
2. **Fix the experiment before computing new P&L.** Pin periods, rules, source
   vintages, costs, risk mandate, comparators and a trial ledger. The two cards
   above are proposals, not launched/registered experiments. No data-window search
   for attractive returns. A development continuation cannot silently become a pass.
3. **Separate causes of failure.** First check implementation/data validity, then
   strategy/policy compatibility, then economic signal, then broker execution.
   A correctly applied halt can invalidate the proposed strategy-policy combination
   without proving all price signals useless. Post-halt hypothetical trades must
   never be combined with the original governed account P&L.
4. **Measure net returns and uncertainty.** Compare on chronological folds with
   non-overlapping outcomes and appropriate warmup; forbid positions crossing split
   boundaries. Use day/week blocks for EUR/USD and independent event clusters for
   USD/JPY, not tick counts as sample size. Predeclare block length, inference and
   multiplicity handling before evaluating outcomes. Require a positive conservative
   lower confidence bound for deployment consideration, not merely positive P&L.
5. **Cost screen before optimization.** Preserve observed bid/ask, avoid double
   charging spread, include dated commission and financing when applicable. Show
   zero-additional-slippage only as an optimistic bound, never calibrated reality.
   Predeclare base/stress slippage using representative evidence. Until available,
   report break-even capacity and conditional results; do not qualify the broker.
6. **Prevent repeated-search optimism.** Count both hypotheses, comparators and
   all later variants; report rejections. A fresh untouched final evaluation is used
   once after specification freeze. Sequentially extending history requires a
   registered information/stopping plan, not checking until significance appears.
7. **Check joint USD exposure only if individual candidates survive.** Long
   EUR/USD and short USD/JPY both sell USD. Opposite directions do not justify
   subtracting stop risk. Simulate shared capital, costs, reservations and limits;
   separate pair reports do not establish portfolio diversification.

Published evidence does not establish either exact rule's profitability, and no
new return estimate was generated in this assessment. No minimum trade count,
fixed six-month period or low drawdown alone establishes an edge.

## What is worth keeping, and what stops now

Keep the existing deterministic governor, immutable records, replay, session
accounting, trade-level inspection and UI. Use AI to articulate rival explanations,
audit assumptions and recommend rejecting an idea. Numerical claims must reference
computed records, not model prose. Keep the current entry freshness boundary; it
is an execution safety check, not proof of a trading advantage.

Stop parameter sweeps before diagnosing a shared halt; translating unconstrained
AI prose into an unrelated executable kernel; treating tick coverage as economic
sample size; and using repeated feature delivery as the trading success metric.
No further branding, broker integrations or research UI expansion is part of this
assessment. A historical language-model explanation is not a prospective forecast.

## Finite handoff before further coding

This assessment is complete when the retained halt arithmetic, unchanged-limit
design choice, hypothesis cards, counterarguments and data gates are documented
and checked. **That boundary is met; profitability and implementation are not.**

The first justified implementation, after this assessment, is narrowly scoped to
the additional lifecycle sizing check and its visible rejection reason. Required
acceptance: unchanged legacy caps/halts; a feasible fixed-stop winner can reach
its planned target under the modeled envelope; an infeasible minimum lot is HOLD;
cost/conversion/other-position changes cannot bypass checks; overshoot retains
protection; old evidence is unchanged. Verify synthetic boundaries first, then a
separately registered targeted historical comparison. Do not launch a full study
to discover whether the arithmetic is coherent. This document does not implement
or start that work.

EUR/USD's cost screen precedes a new signal implementation. USD/JPY's data audit
precedes one. If their required inputs/cost economics fail, issue a rejection or
insufficient-evidence decision and stop that hypothesis. No open-ended tuning loop
and no requirement to produce a profitable answer.
