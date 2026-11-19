# Trading research assessment — November 18, 2026

## Decision

Complete the trading assessment before extending the application. Retain the
current-to-stop risk definition and every existing limit. Resolve the predictable
strategy/risk conflict through **smaller entry sizing that reserves room for a
winner to reach its planned exit**, rather than increasing risk limits or clearing
halts. This is an analytical design decision, **not an implemented fix**.

The initial assessment proposed EUR/USD post-London-fix drift and USD/JPY
post-BoJ-announcement continuation conditional on observed rate/price agreement.
The market follow-up below now **shelves the EUR/USD idea**: its fixed-window
endpoint diagnostic does not demonstrate an edge even before additional fees or
slippage. USD/JPY remains data-gated. Neither is ready for paper trading. Preserve
the original hypothesis cards below; do not rewrite them around observed winners.

Initial assessment scope: source review, retained-evidence arithmetic and research specifications.
No new replay, provider-model request, broker observation, order, campaign, Docker
restart or production-code change. Trading stays disabled; PR #65 stays unmerged.
M1 gaps and B01's rejection remain unchanged. The sources reviewed below do not
establish that either proposed entry rule has predictive power today. The subsequent
read-only market analysis adds observations from exposed training, not a new
strategy replay, independent validation or current live-market assessment.

## Market follow-up: measure before implementing

**Decision:** keep session-aware measurement, shelve EU-FIX-01, and do not implement
JP-POLICY-01 without its required inputs. More market movement is not predictable
direction, and more software cannot make a negative or unidentified edge positive.

The [pinned plan](../evidence/market-anatomy-plan-20261118.json) was written before
calculation. The [result](../evidence/market-anatomy-20261118.json) covers May 25
through September 4, 2026 inclusive: 75 nominal weekdays wholly inside previously
exposed training. It reads 4,352,449 EUR/USD and 6,403,768 USD/JPY source rows.
Validation and holdout outcomes were not queried. Dates are UTC unless a named
local session is specified; this report is dated November 18 in Vancouver.

### Session conditions

Each UTC minute uses the last source bid/ask at or before that minute. Only quotes
no older than two seconds enter these summaries. The 15-minute movement requires
eligible quotes at both ends and the same session bucket and UTC day. It is an
absolute mid-price change, **not a forecast or achievable profit**. Overlapping
minute observations are not independent trades.

| Disjoint session bucket | EUR/USD spread median / p95, pips | EUR/USD median absolute 15m move, pips (paired observations) | USD/JPY spread median / p95, pips | USD/JPY median absolute 15m move, pips (paired observations) |
| --- | ---: | ---: | ---: | ---: |
| Tokyo only | 0.30 / 0.50 | 1.55 (8,054) | 0.40 / 0.70 | 2.80 (11,574) |
| Tokyo + London | 0.30 / 0.50 | 2.30 (4,129) | 0.40 / 0.60 | 3.10 (4,747) |
| London only | 0.30 / 0.50 | 2.05 (5,633) | 0.40 / 0.60 | 2.65 (6,317) |
| London + New York | 0.30 / 0.50 | 2.95 (10,900) | 0.40 / 0.60 | 3.15 (10,815) |
| New York only | 0.30 / 0.50 | 2.05 (9,274) | 0.40 / 0.60 | 2.55 (10,287) |
| Outside these sessions | 0.50 / 4.80 | 1.10 (1,428) | 0.70 / 6.10 | 1.75 (2,102) |

Definitions are the existing versioned conventions: Tokyo 09:00–18:00 local,
London 08:00–17:00 local, New York 08:00–17:00 local, weekdays, with timezone/DST
conversion. Overlaps have separate buckets. These are not holiday calendars or
claims that the global FX market is closed outside them. Pips differ in quote
currency across pairs; this table is not a comparison of portfolio dollar risk.

**Trading interpretation:** the EUR/USD sample offers larger movements during
London–New York overlap than Tokyo alone, with similar median source spreads.
The less favorable spread tail outside the named sessions merits a separate cost
regime. These observations justify measuring signal behavior by session; they do
not justify a long, short, breakout, mean-reversion or automatic session exclusion.
USD/JPY's profile is distinct; a EUR/USD session rule cannot be assumed to transfer.

### EUR/USD post-fix diagnostic

The direction and window were fixed beforehand: long EUR/USD from 16:05 to 18:00
Europe/London. This checks endpoint drift, **not** the full stop/target strategy.
No calendar veto or verified fixing-day filter was available. Twelve of 75 nominal
weekdays were excluded because at least one endpoint source quote exceeded two
seconds; excluded dates and ages remain in the receipt. Selection may bias the
63-day subset. There are only 15 observed week clusters, not millions of trials.

| Metric | Observed result |
| --- | ---: |
| Mean mid-price change | −0.648 pips/day |
| Mean exit bid minus entry ask | **−0.921 pips/day** |
| Mean endpoint spread deduction | 0.273 pips/day |
| Positive days after source spread | 30 / 63 |
| Approximate 95% week-cluster percentile interval for mean bid/ask outcome | **−3.481 to +1.876 pips/day** |
| First 25 expected weekdays | 18 included; mean −2.994 pips/day |
| Middle 25 expected weekdays | 21 included; mean +2.429 pips/day |
| Last 25 expected weekdays | 24 included; mean −2.296 pips/day |

The interval uses 5,000 resamples of ISO-week clusters, seed 20261118. It is
exploratory, assumes weeks are suitable resampling units and does not correct
selection bias, prior research exposure or changing regimes. It is not a calibrated
probability of future profit. Both signs remain plausible; two chronological
blocks were negative. Fees, slippage and financing are omitted. On this recorded
bid/ask sample there is no positive average margin available to absorb extra costs.

**Disposition: SHELVED / EDGE_NOT_DEMONSTRATED.** Do not shift the window, reverse
direction, select the middle block or optimize stops to rescue this observation.
This does not prove that every fixing strategy loses, or establish the untested
stop/target strategy's outcome. It is enough to decline further implementation of
this proposal now. USD/JPY's session table does not test its macro hypothesis;
synchronized historical rate expectations and release evidence are still absent.

### Data trust and reproducibility

The [HistData FAQ](https://www.histdata.com/f-a-q/) specifies fixed EST (UTC−5,
without DST) for source timestamps and bid/ask for generic ASCII ticks. The
repository parser uses that fixed offset before UTC conversion. HistData does not
certify data quality or provide consolidated FX volume. These are source quotes,
not measured CMC/FOREX.com fills or global order flow.

All queried prices passed finite, positive, non-crossed and native precision checks.
Equal timestamps occur frequently: 1,388,509 additional rows for EUR/USD and
3,099,688 for USD/JPY; 89,005 and 428,861 respectively repeat a timestamp/quote
combination. Sampling selects the last stored sequence at the timestamp instead
of counting every tick as another opportunity. This convention does not independently
validate vendor sequencing. No original data was deleted or deduplicated.

The eligible minute fraction ranges from 29.8% to 79.1% across EUR/USD buckets
and 36.5% to 78.0% for USD/JPY. Denominators include nominal weekday minutes,
including closures and holidays. Inactive quotes, archive gaps and closures are
not distinguished here. **These are not collector-reliability scores or observed
network latency**, and cannot qualify or weaken the live two-second entry gate.
Per-day coverage, exact denominators and source hashes remain in the result.

The [non-production analysis script](../../tools/qualification/market_anatomy_20261118.py)
reads SQLite in immutable read-only mode, checks both source hashes before and
after, and independently verifies every included EUR/USD endpoint using point
queries and Decimal arithmetic (126 checks). A second arithmetic review checked
daily returns, block means, exclusions and minute denominators. All 780 previously
tracked files were unchanged at the end of calculation, before adding this report.
The [publication receipt](../evidence/market-anatomy-verification-20261118.json)
records result/plan fingerprints and AST equivalence between the executed script
and its formatted published copy. Published plan values are identical; Git
normalizes its final CRLF to LF, so both byte fingerprints are recorded.
Old qualification and strategy results remain
unchanged. No product code, risk setting or running preview was modified.

Reproduction requires the same two privately retained source indexes and manifests
with the hashes in the result; raw vendor data is not republished. Use the study's
pinned repository revision/image and timezone dependency recorded in the receipt.
In an isolated container, mount those two history directories under
`/data/preview/history` read-only and mount a **new empty** output directory at
`/review` containing the published plan as `plan.json`. Run the published script with
the repository `src` on `PYTHONPATH`. Disable networking; the original resource
limits were 0.5 CPU and 256 MiB, with a read-only container root and temporary
`/tmp`. The script refuses to overwrite `result.json`. Script and plan byte hashes
differ from the original after formatting/newline normalization; the receipt
checks unchanged code structure and plan values.
Reproduction does not create fresh independent evidence.

### How decisions change from here

Market questions lead implementation: identify the participant behavior or
information change, define an observable signal available at decision time, and
write a falsification test before computing results. Compare against no trade and
simple controls; account for source coverage, session, event risk and realistic
costs. AI can challenge a thesis and explain measured outcomes; a plausible story
is not a signal. Rejected ideas remain rejected unless new evidence motivates a
separately registered hypothesis. Current market context must carry an as-of time
and point-in-time sources; this historical sample is not a current trading view.

Measure progress by eliminating bad ideas and finding robust economic evidence,
not by feature count. Keep the risk-policy compatibility work restrictive, but
do not confuse fixing that engineering constraint with discovering alpha. No new
strategy kernel, model request, paper campaign or trading authority follows from
this analysis.

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

**Original proposed decision, superseded by the follow-up above:** cost-feasibility
research candidate only. The engine cannot
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

Published evidence does not establish either exact rule's profitability. The
initial assessment generated no return estimate; the follow-up above supplies a
limited exploratory endpoint diagnostic, not a tradable result. No minimum trade count,
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

Subsequent owner direction is incorporated in the [revised roadmap](roadmap.md).
It groups the restrictive sizing work below with one structural trend-pullback
workflow, chronological chart inspection and a bounded comparison. That new
price-action hypothesis has no profitability verdict yet. EU-FIX-01 remains shelved
and JP-POLICY-01 remains data-gated; neither is revived by the roadmap change.

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

Implementation follow-through is now recorded separately in the
[structural development study](../engineering/structural-pullback-study.md).
That review branch adds the restrictive admission check and causal setup workflow;
it does not revise this assessment's earlier findings or qualify its hypotheses.

EUR/USD's cost screen precedes a new signal implementation. USD/JPY's data audit
precedes one. If their required inputs/cost economics fail, issue a rejection or
insufficient-evidence decision and stop that hypothesis. No open-ended tuning loop
and no requirement to produce a profitable answer.
