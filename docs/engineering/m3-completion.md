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

## Acceptance evidence and remaining boundaries

| Work package | Concrete acceptance evidence | Current state |
| --- | --- | --- |
| Input and convention reconciliation | Versioned source/session calendar; classified gaps with unresolved gaps retained; fixed timezone/DST, arrival and revision limitations; independently checked numerical and point-in-time conventions | Numerical comparison now evidenced. Source/session and historical availability limitations remain open; modeled 250 ms latency is not a measured result. Native indicator equivalence remains unclaimed. |
| Cost calibration and conservative execution | Per-pair, account-specific commission, spread, slippage and financing provenance; effective dates/units; rollover/triple-day behavior; explicit conservative stress bounds; reproducible cost attribution | [Versioned broker-aware costs](broker-aware-replay-costs.md) are integrated and tested in the USD replay ledger; per-fill notional fees, explicit dated signed rollover and risk reserves are supported. Historical tariffs, dated swap/conversion evidence and representative slippage remain unqualified. Original 4/2/3 studies are unchanged. |
| Frozen multi-fold study | At least three chronological walk-forward folds, all variants retained, identical cost/availability treatment, a separately sealed final holdout, flat partition boundaries and independent artifact verification | Completed: three advancing origins, January 30 outcome holdout, both pairs and base/stress scenarios, all 16 sessions verified flat. [Registered result](m3-walkforward.md). No fitted-model or wholly unseen-price claim. |
| Final M3 verdict | Reproducible baseline comparison, cost sensitivity, per-fold results, uncertainty and explicit keep/reject/insufficient decision; checklist links each claim to evidence | Registered research verdict: REJECT_FOR_PROMOTION. All scenario outcomes, uncertainty and no-trade comparison are published in [the consolidated report](m3-walkforward.md). The research screen is complete; full historical cost/availability qualification and economic acceptance remain open. |

These packages do not require a new live 24-hour campaign. Missing historical
availability or broker calibration cannot be solved by running more ticks through
an assumption-enabled replay. A data-only study must retain its counterfactual
scope and cannot substitute for those missing attestations.

## Protocol applied to the registered evaluation

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

The [published registry](../evidence/m3-walkforward-registration-20261105.json)
implements this protocol with explicitly uncalibrated base/stress assumptions, rather
than claiming missing historical broker inputs were obtained. Its defined study is
finished and does not authorize further tuning or another run. The two research
deliverables above are complete; full M3 calibrated-cost and source-availability
requirements remain open and are not erased by a completed simulation.

## Run the numerical check

From the repository, with Python dependencies and Node.js available:

```text
python -m tools.qualification.b01_parity --output .local/b01-numerical-parity.json
```

The output is created exclusively and records source/vector hashes, runtime version,
case results and scope limitations. No terminal, credential, service, order or desktop
interaction is used. No changes to B01 or existing study artifacts were needed.
