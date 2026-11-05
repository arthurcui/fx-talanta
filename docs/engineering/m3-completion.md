# M3 completion checklist

M3 delivers a trustworthy frozen baseline and a reproducible research verdict. It
does not require disguising a losing strategy as profitable. Engineering validity
and economic suitability are separate conclusions; neither authorizes connected
strategy PAPER while the M1/M2 operational gates remain open.

## What is already evidenced

- Frozen B01 rules, point-in-time bar/revision selection and the same simulator/risk
  components used by offline execution; the two-second entry rule is unchanged.
- Historical bid/ask import, immutable experiment manifests, source hashes,
  streaming replay and independently verified journals/accounting.
- Six full UTC sessions: 713,826 ticks and 14 closed simulated trades; all sessions
  ended flat. Both holdout pairs lost after modeled costs. The original shorter
  pilot and its unresolved position remain preserved separately.
- Independent numerical reference: 36 synthetic vectors across EUR/USD and USD/JPY,
  warm-up boundaries, EMA continuation, both directions, flat trend and equality at
  breakout thresholds. The JavaScript oracle uses exact BigInt rational arithmetic
  and a closed weighted sum, independently of the production Decimal recurrence.
  EMA/ATR error tolerance is 1e-26; direction and rounded stop/target distances must
  agree exactly. [Actual evidence](../evidence/m3-numerical-parity-20261105.json).
- Replay regressions cover adverse gap fills, stale arrival before a fresh exit,
  long/short costs, partial/rejected entries, cost stress with risk-adjusted sizing,
  unresolved end-of-data exposure and rejection of OHLC-only execution paths.

The numerical reference is a development tool, not a new runtime dependency or
an MT5 indicator test. It does not prove native `iMA`/`iATR` parity, terminal
availability, live freshness or broker costs. CI explicitly installs Node for this
check; the application/container image does not gain a JavaScript dependency.

## Finite remaining work

| Work package | Concrete acceptance evidence | Current state |
| --- | --- | --- |
| Input and convention reconciliation | Versioned source/session calendar; classified gaps with unresolved gaps retained; fixed timezone/DST, arrival and revision limitations; independently checked numerical and point-in-time conventions | Numerical comparison now evidenced. Source/session and historical availability limitations remain open; modeled 250 ms latency is not a measured result. Native indicator equivalence remains unclaimed. |
| Cost calibration and conservative execution | Per-pair, account-specific commission, spread, slippage and financing provenance; effective dates/units; rollover/triple-day behavior; explicit conservative stress bounds; reproducible cost attribution | Current 4/2/3 per-lot assumptions are not calibration. Use retained read-only/fill evidence and published schedules where applicable; insufficient observations stay insufficient. No new order is authorized. |
| Frozen multi-fold study | At least three chronological walk-forward folds, all variants retained, identical cost/availability treatment, a separately sealed final holdout, flat partition boundaries and independent artifact verification | One three-day split is completed, not multi-fold evaluation. January 16 and January 21–23 are examined evidence and cannot be relabeled untouched holdout data. |
| Final M3 verdict | Reproducible baseline comparison, cost sensitivity, per-fold results, uncertainty and explicit keep/reject/insufficient decision; checklist links each claim to evidence | Both examined holdouts lost. No economic acceptance or promotion is claimed. |

These packages do not require a new live 24-hour campaign. Missing historical
availability or broker calibration cannot be solved by running more ticks through
an assumption-enabled replay. A data-only study must retain its counterfactual
scope and cannot substitute for those missing attestations.

## Next study protocol, before any new evaluation

The [input/cost audit](historical-input-costs.md) now provides complete retained-tick
integrity checks, daily spread distributions, explicit gap classification and saved
demo fee aggregates. It resolves the inventory step only as a scoped research audit:
the session proxy, original receipt/revision history, historical account tariffs,
financing rates and representative slippage remain unqualified. Current published
commission scenarios must not be described as historically calibrated costs.

1. Finish the source/cost inventory and choose the research claim supported by it.
   Separate calibrated quantities from unmeasured conservative assumptions. Keep
   missing required calendar/news evidence visible; do not rename it a passed gate.
2. Freeze B01, risk policy, source hashes, history prefixes, chronological fold dates,
   comparison arms, cost stress grid, exclusion rules and reporting metrics in one
   registry. No parameter search is authorized by this checklist. Include a no-trade
   comparator and the unchanged B01 under base/stress costs; compare independent
   ledgers rather than adding their percentage returns.
3. Reserve a new final holdout outside all examined windows. Do not choose its dates
   after viewing strategy outcomes. Use at least three walk-forward folds; each
   evaluation period must be later than its training/calibration period. Reusing an
   earlier validation period as later training must be explicitly recorded.
4. Run serial background workers with resource bounds. Require verified-flat prior
   partitions or a preregistered management policy; no hidden reset, window extension
   or forced favorable exit. Retain failures and all registered alternatives.
5. Publish one consolidated result with per-fold trade counts, returns, drawdowns,
   costs and missingness. Account for dependence between adjacent sessions when
   expressing uncertainty. Do not infer robustness from 14 trades or annualize a tiny
   sample. The economic decision may be rejection or insufficient evidence.

This protocol is not a registered experiment: dates, new dataset hashes and calibrated
cost inputs are still required before running it. It deliberately does not manufacture
a completed M3 gate from another assumption-only study.

## Run the numerical check

From the repository, with Python dependencies and Node.js available:

```text
python -m tools.qualification.b01_parity --output .local/b01-numerical-parity.json
```

The output is created exclusively and records source/vector hashes, runtime version,
case results and scope limitations. No terminal, credential, service, order or desktop
interaction is used. No changes to B01 or existing study artifacts were needed.
