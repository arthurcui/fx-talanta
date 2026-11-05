# M3 offline baseline and replay

The owner authorized M3 progression under the approved
[M1 split](m1-completion-decision.md). The [open M1 register](m1-open-requirements.md)
blocks connected strategy PAPER. This work has no broker execution authority.

## Frozen first research convention: B01-research/1

`research/baseline.py` implements the specification's signal hypothesis: completed
H1 EMA50/EMA200 trend plus a completed M15 close breaking the previous twenty M15
bars, excluding the signal bar. Short signals mirror long signals. It emits a
research candidate or an explicit HOLD, never an executable intent.

Conventions are declared before any economic results:

- Decimal arithmetic with local precision 34; each EMA starts with the SMA of its
  first period of closes, then uses alpha = 2/(period+1).
- ATR14 starts with the mean of fourteen true ranges using a preceding close,
  then uses Wilder smoothing. Stop distance is 1.5 ATR rounded upward to 0.00001
  for EURUSD or 0.001 for USDJPY; target distance is twice that rounded distance.
  These are research increments, not claims about broker capabilities.
- First session baseline: UTC weekdays 00:00 through 23:45, exclusive at the end.
  Time exit is sixteen M15 bars after signal close or that day's 23:45 UTC cutoff,
  whichever comes first. This session is not an optimized or profitable choice.
- Only closed bars available by the decision time contribute. Complete revision
  history is required; later revisions do not refresh the original sixty-second
  signal expiry. Input order cannot change the result. Future rows/revisions do
  not enter the decision's evidence hash.
- Dataset completeness is an explicit caller attestation against a pinned source
  session calendar, defaulting to unverified/HOLD. OHLC alone cannot prove that
  a missing trading session was closed. The most recent H1 bar must also be current.
- Minimum history is 200 completed H1 bars and 21 completed M15 bars. Seed results
  depend on the pinned history prefix; subsequent replay manifests must retain it.
- Existing position means HOLD. Candidate generation does not perform sizing,
  reserve capital or authorize an order. The two-second quote entry restriction
  remains a separate downstream requirement.

## Remaining M3 deliverable

This is the initial signal kernel, not completed M3 or economic validation.
Keep the rest together in the M3 branch before presenting a completion PR:

1. Immutable dataset/experiment manifests, availability-aware event replay and
   chronological train/walk-forward/untouched-holdout boundaries.
2. Candidate-to-simulator integration using existing deterministic risk controls;
   next executable bid/ask, sixty-second expiry and unchanged quote freshness.
3. Explicit spread, commissions, slippage, financing, gaps, partial/rejected fills
   and conservative ambiguous intrabar outcomes; never infer profit from signals.
4. Reproducible artifact hashes, retained variants, baseline statistics and
   cross-language indicator/reference parity where required by the specification.

Synthetic kernel tests establish mechanics and point-in-time behavior only.
They do not qualify M1 inputs, supply historical market data or show profitability.
