# Frozen B01 advancing-origin evaluation

This is a simulator-only research evaluation of the unchanged `B01-research/1`.
It is not a new broker campaign, account activation, or strategy deployment.
The [protocol](../evidence/m3-walkforward-protocol-20261105.json) and
[registration](../evidence/m3-walkforward-registration-20261105.json) were published
before evaluating these strategy outcomes. The registration binds 16 serial jobs,
source hashes, exact source row counts, prior-history counts, engine/runner hashes,
cost assumptions, risk policy and decision rule.

## Result: reject promotion, retain the baseline evidence

The [independently reconstructed report](../evidence/m3-walkforward-result-20261105.json)
covers all 16 registered sessions. All ended flat; 42 closed simulated trades include
both cost scenarios. The replay processed 2,249,344 tick events across the scenarios,
representing 1,124,672 unique pair/day observations. Repeated scenarios are not new
independent market evidence. No failed job, retry, extra variant or window extension
was used. The earlier failed broker/provider evidence remains separate and unchanged.

| Evaluation | Pair | Base return % | Stress return % | Closed trades (base / stress) |
| --- | --- | ---: | ---: | ---: |
| Jan 15 | EURUSD | -0.153 | -0.175 | 2 / 2 |
| Jan 15 | USDJPY | -0.005 | -0.038 | 3 / 3 |
| Jan 20 | EURUSD | -0.229 | -0.240 | 1 / 1 |
| Jan 20 | USDJPY | -0.016 | -0.070 | 5 / 5 |
| Jan 27 | EURUSD | 0.435 | 0.413 | 2 / 2 |
| Jan 27 | USDJPY | 0.235 | 0.184 | 4 / 4 |
| Jan 30 holdout | EURUSD | -0.157 | -0.167 | 1 / 1 |
| Jan 30 holdout | USDJPY | 0.423 | 0.390 | 3 / 3 |

The largest observed within-session drawdown was 0.406% (USD/JPY stress).
This is a maximum across independently funded sessions, not portfolio drawdown.
The full report retains each session's commission, slippage, spread attribution,
financing, equity states and artifact hashes. Both pairs have very small trade
samples: six EUR/USD and fifteen USD/JPY closed trades per cost arm across four days.

The no-trade comparator returns 0% in every row. Both pairs lost in the first
two folds under both cost scenarios, so each has only one positive earlier fold.
EUR/USD also lost in the final holdout; USD/JPY gained. Both rejection conditions
are retained rather than selecting only the profitable pair/date. **REJECT_FOR_PROMOTION**
means this frozen candidate fails the registered research screen; it is not a claim
that the strategy can never work, nor statistical proof of future losses.

The engineering work delivered the registry, all variant records, full-tick replay,
flat-boundary verification, cost sensitivity, comparison and a reproducible verdict.
Full M3 calibrated-cost/source-availability acceptance remains incomplete. Connected
strategy PAPER remains blocked by the retained M1/M2 requirements.

## Design and data separation

| Fold | Expanding history | Full UTC evaluation day | Role |
| --- | --- | --- | --- |
| 1 | January 1–14, available bars only | January 15, 2025 | Walk-forward test |
| 2 | January 1–19, available bars only | January 20, 2025 | Walk-forward test |
| 3 | January 1–26, available bars only | January 27, 2025 | Walk-forward test |
| Final | January 1–29, available bars only | January 30, 2025 | Final outcome holdout |

These are advancing forecast origins for a fixed strategy, **not fitted models**.
There is no parameter search, fold-specific tuning or profitable-window selection.
Each origin has at least 200 preceding available H1 bars. Later sessions may use
bars from earlier evaluations; point-in-time selection still excludes future bars.
January 16 and 21–23, whose outcomes were examined earlier, are not evaluation days.
The holdout was new to strategy evaluation, but all January prices and gap/spread
statistics were already audited. It is not a wholly unseen external dataset.

EUR/USD and USD/JPY each use independent USD 10,000 simulated accounts. Every
source tick is processed, with modeled 250 ms receipt latency, the unchanged
two-second entry ceiling, one position maximum and the existing 0.25% per-trade
research risk cap. These are offline policy values, not authority to submit orders.
History/news/calendar readiness is counterfactual; M1 gaps remain visible.

Two registered cost arms retain the legacy model for comparability:

| Arm | Commission / lot / side (USD) | Slippage / lot / side (USD) | Financing / lot / elapsed day (USD) |
| --- | ---: | ---: | ---: |
| Base | 4 | 2 | 3 |
| Stress | 8 | 4 | 6 |

These are **uncalibrated scenarios**, not the current published broker tariffs or
historical effective rates. The elapsed-day financing convention is not a broker
rollover model. Recorded bid/ask spread is embedded in fills and is not deducted
again. Costs can change risk sizing and fills, so the two scenarios need not have
identical positions or monotonically ordered total returns.

The no-trade comparator is analytical zero trading return, zero trading costs and
zero drawdown, excluding cash interest. It does not require a fabricated broker run.

## Acceptance and failure behavior

The runner consumes the frozen manifest once. Each job writes exclusive journal,
equity, result and receipt artifacts. It reconstructs journal chains, fills, balance,
exposure and drawdown, and checks source counts/hashes. All preceding sessions must
have completed flat before any later session or final holdout is evaluated. A failure
or unresolved exposure stops the sequence; no blind retry, forced favorable close,
time-window extension, downsampling or hidden reset is allowed.

An independent reporting pass reopens each source index read-only, recounts input
rows and reconstructs the persisted evidence. It includes any unrun jobs and verifies
that the saved conclusion follows the predeclared rule. Original pilot, full-session
study and qualification failures remain unchanged.

The registered research screen rejects promotion if any pair/scenario final holdout
return is non-positive, or fewer than two of three earlier fold returns are positive
for any pair/scenario. Incomplete or unresolved evidence returns **insufficient**.
Passing the screen means **keep for further research only**, not economic acceptance,
broker qualification or connected strategy permission.

Report each day/account separately. Ranges and worst single-session drawdown do
not form a combined equity curve. Pairs, dates and cost arms are dependent; four
dates in one month cannot establish statistical significance or an annualized edge.

## Reproduction

```text
python -m tools.qualification.walkforward register --protocol docs/evidence/m3-walkforward-protocol-20261105.json --directory <new-directory> --index EURUSD=<retained-index> --index USDJPY=<retained-index>
python -m tools.qualification.walkforward run --directory <registered-directory>
python -m tools.qualification.walkforward_report --directory <registered-directory> --output <new-report.json>
```

Use the pinned runner/engine revision and retained private indexes. Registering a
new experiment is different from replaying an exhausted run directory. The worker
lowers only its own process priority; it never opens MT5 or controls other apps.
