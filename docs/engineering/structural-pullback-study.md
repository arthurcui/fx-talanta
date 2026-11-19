# Structural pullback development study

Status: implemented and the bounded development comparison completed on November
19, 2026 UTC. The confirmation arm did not trade; the first-touch control lost
money after modeled costs. **INSUFFICIENT_EVIDENCE**, not a qualified strategy.
Research only, trading disabled. B01, M1 gaps and prior failed evidence are unchanged.

## Frozen question and scope

Does waiting for a bounce, retest and closed-bar confirmation improve the recorded
opportunities relative to first touch of the **same** previously confirmed H1
level? EUR/USD only. Neither arm is presumed profitable. USD/JPY is excluded from
this first kernel, not treated as a validated portfolio companion.

Use the existing, already exposed HistData training history. Pin June 1 00:00 UTC
through June 13 00:00 UTC, 2026 (ten nominal weekdays), with preceding data only
for indicator warmup. This is the first complete two-week block after source
warmup, chosen before querying this strategy's outcomes. No validation or holdout
data, period extension, parameter search or losing-run reset. Count actual
eligible sessions and missing inputs rather than claiming ten complete sessions.

## Rules fixed before results

- Closed H1 price above EMA50 with EMA higher than three H1 bars earlier for buys;
  inverse for sells. Require contiguous indicator inputs and a current closed H1.
- The latest strict H1 swing low/high has two closed H1 bars on each side. Its
  confirmation, source bars and first availability must precede the entire M15
  touch bar. A level older than eight hours is not eligible.
- Freeze simple M15 ATR14 when the level is watched. Zone half-width = 0.25 ATR;
  protective stop = another 0.25 ATR beyond the zone (rounded outward to tick).
  Price must depart the zone before a later touch. No moving zone or widened stop.
- Entry window: London 08:00â€“17:00 local, using the existing pinned timezone
  definitions. This is a research convention, not a claim of optimal liquidity.
- First touch arm: consider entry after the first touching bar closes. A bar
  crossing the structural stop invalidates the setup before any entry.
- Confirmation arm: touching bar's last two ranges average no greater than the
  preceding two; then a later close outside the zone in trend direction, a later
  retest, and a later reversal candle closing past the retest extreme. Confirmation
  candle range must be at most the frozen ATR. These OHLC conditions are proxies,
  not observed order flow. Inconclusive OHLC paths do not invent intrabar ordering.
- Expire eight M15 bars after touch, at session end, on trend loss, or level age
  expiry. Revisions to consumed bars invalidate the evaluator; no historical
  rewriting. Duplicate arrivals never create an additional opportunity or order.
- Both arms: next eligible original quote within 60 seconds, two-second freshness,
  unchanged spread/adverse-price checks, the same fixed structural stop, 2R target,
  and exit after 16 M15 bars or session end. No partial close or trailing stop.

The detector records opportunities while positions are open too; the account
governor may veto them. Setup quality and realized account results are separate.
No synthetic fill is assigned to a blocked or unfilled opportunity.

## Risk and evidence

Cap all risk at the lower of the existing dataset and frozen candidate policy.
For this development study use 0.10% per trade **and** aggregate, 1% daily loss,
5% drawdown, one position; retain all other existing limits. A lifecycle admission
bound additionally uses only 90% of aggregate capacity at conservative post-loss
equity to cover target-to-stop giveback plus modeled exit costs. It can only reduce
volume. A below-minimum lot is HOLD. Gaps, overshoot or cost/model errors can still
cause the original persistent HALT. Never increase caps to obtain trades.

Source bid/ask and the existing uncalibrated USD cost scenario (4 commission and
2 slippage per lot per side; 3 financing per lot/day), modeled 250 ms availability,
and counterfactual clear calendar/news remain **unqualified**. No production
provider or demo/live execution is exercised.

Retain source/engine/manifest hashes; append-only opportunity transitions,
governance reasons, reservations, fills, exits and costed account results. Show
only bars available at a selected chart cutoff. Report all watched levels,
touches, confirmations, invalidations, expiry, blocked/missed entries, settled
trades, drawdown and HALTs in both arms. A zero-trade or losing result is valid.

Engineering acceptance requires causal synthetic tests, unchanged legacy behavior,
actual replay evidence, UI inspection/export/reload and no risk-limit increase.
Economic status remains **INSUFFICIENT_EVIDENCE** for this short exposed slice,
irrespective of P&L. No automatic promotion or further study is authorized by a
positive development result.

## Actual development results

Both arms processed the same 660,471 original quote rows. All 13 watched levels,
their geometry, context bars and transition sequences match across arms; entry
eligibility differs. The independent verifier reads the original SQLite index and
all compressed journals without replaying or changing either run.

| Measure | Retest confirmation | First-touch control |
| --- | ---: | ---: |
| Watched levels | 13 | 13 |
| Touches / bounces / retests / confirmations | 4 / 1 / 0 / 0 | 4 / 1 / 0 / 0 |
| Expired / invalidated opportunities | 7 / 6 | 7 / 6 |
| Closed trades / winners | 0 / 0 | 4 / 1 |
| Net realized P&L (USD) | 0 | -4.0955352483 |
| Commission / financing (USD) | 0 / 0 | 2.32 / 0.0055352483 |
| Maximum observed equity drawdown | 0% | 0.0889043603% |
| Persistent risk or integrity HALT | No | No |
| Unsettled position or order | None | None |

The control closed three trades at structural stops and one at the fixed target.
Adverse slippage is already in fills; spread is embedded in bid/ask execution.
Neither is subtracted a second time. Four trades are inadequate for economic
inference. No winner is selected from this comparison; avoiding these four entries
does not demonstrate that the confirmation rule has positive expectancy.

All 360 expected London M15 closes are present, with no duplicate source sequence
IDs or tied quote timestamps. That does **not** establish full input eligibility.
The strict contiguous H1 warmup restarts after weekend gaps: opportunities appeared
on June 3â€“5 and 10â€“12, only six of the ten nominal weekdays. Across the whole replay,
445 evaluations reported `GAPPED_OR_STALE_INPUTS`; 306 were outside the session.
The longest receipt gap is 172,844.985 seconds, including the weekend. These are
retained limitations, not silently removed periods or qualified delivery metrics.

The funnel stops before a retest: four touches yielded one qualifying bounce,
and no later valid retest/confirmation before invalidation or expiry. The next
research decision should inspect these paths and the weekend warmup convention
before preregistering a new variant. Do not extend the period or relax filters on
this run to manufacture trades. USD/JPY and independent validation are still open.

## Verification and reproducibility

The [sanitized verification receipt](../evidence/structural-pullback-20261119.json)
retains source, manifest, run, engine and audit hashes; exact per-trade costs and
outcomes; UI checks; and explicit engineering/economic verdicts. Raw historical
prices and the original private journals remain outside Git. No original research
result, broker record or PR #65 state was replaced.

Independent checks reconstruct both journal hash chains and final broker books,
verify compressed/raw receipts and all 660,471 equity samples per arm, recompute
drawdown, match each of eight fills to its exact original quote, and recalculate
commission, financing, P&L and percentage/lifecycle admission bounds. Each entry
uses a modeled 0.25-second quote age. This validates the replay arithmetic, not
real broker latency, market-data quality or executable cost calibration.

The historical engine is reproducible at commit `2dbe5a08a90e4c881e7e9c54603773840acbfb45`.
Its frozen engine hash is
`f06f0c1420de4b4aab9a33617a95608057525cbb41e7b6ba48868d36a263caa4`.
A subsequent isolated recording fix retains an equity sample when a next quote
has already crossed the planned stop. That path occurred **zero** times in both
arms; each retained run already has one sample per quote. The final engine hash
is `a96346a2cea6c9fbec98d70e39c080539fd645e2ba4935909c4ef9ece72f2d51`.
The original run was not rerun or relabeled as using the later engine. A targeted
synthetic regression verifies the changed rejection path and no order submission.

Validation includes 1,421 passed / 145 skipped native tests before that recording
fix, the new targeted regression afterward, 36 B01 numerical parity cases, and all
22 headless browser tests. Synthetic fixtures additionally demonstrate a guarded
fixed-target winner, the original unguarded giveback HALT at identical caps, and
a gap beyond the guarded envelope that still HALTs. Fixture profits are not market
evidence. Applicable CI covers the final PR revision.

To inspect locally, [open the saved study in the separate Docker preview](http://127.0.0.1:8767/strategies/results?candidate=471c7b3ca672c32739e8bf5239d10f02ae37d62e137e767d57f7360779f81040).
The link selects its frozen strategy. Open **Inspect opportunity**, choose a
level, move the cutoff, and switch M15/H1. The control's **Final account outcome**
shows filled volume from deals, costs and exit conditions; outstanding reservation
volume is not mislabeled as filled size. The completed matched control cannot be
started again from its button. Export and reload preserve both results. The
original preview on port 8766 remains unchanged.

The research app stays on an internal Docker network without an external gateway;
a separate fixed-destination ingress publishes only Windows loopback port 8767.
The preview uses a copy of the completed state and has no broker or model credentials.
No live AI request or trading action was part of this study. A future structural
revision requires a distinct preregistration; AI cannot silently mutate these rules.

Repository entry points are `tools/research/structural_study.py` for explicit
prepare/run/serve and `tools/research/verify_structural_study.py` for read-only
independent verification. The preparer requires the pinned historical source;
`run` creates an exclusive start marker and never overwrites a previous attempt.
Results are development-only; validation/holdout execution is rejected.
