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

## Implemented replay boundary

The replay uses the existing offline `Gateway`, risk governor and simulator lifecycle.
`Gateway.for_replay` supplies an ephemeral PAPER/SIMULATOR-only journal; the normal
PostgreSQL constructor retains its durable store. No DSN, terminal or broker client
is accepted by the replay command. This memory adapter does not claim crash recovery.

Bar arrivals and quote arrivals advance a fake clock in availability order. Bars
available at a timestamp are evaluated before quotes at that timestamp. Entries
require a strictly subsequent source quote, the original sixty-second signal window,
the unchanged two-second freshness guard, acceptable spread and an adverse move
within the instrument limit measured from the signal's BID close. Existing risk,
reservation, lot rounding, protection, loss and position limits still apply. Each
signal gets at most one simulator submission; revisions cannot renew that attempt.
The next observed executable quote determines exits, including worse prices after
gaps. Missing end-of-data quotes leave exposure open in the report.

Costs are frozen in account currency (USD) per lot: commission per side, adverse
slippage per side and a nonnegative daily financing charge prorated by elapsed
holding time on closed volume. Spread is represented by the input bid/ask. The
risk budget includes both slippages and a full day's financing estimate; a delayed
exit can exceed that estimate. Spread/slippage are already embedded in fill P&L,
so the cost breakdown must not be subtracted again. Open marked equity excludes
uncharged financing and future close costs. This flat financing model is a research
assumption, not a broker swap calendar or triple-rollover implementation.

Supported execution scenarios are normal, rejected and partial entries; remaining
partial orders remain visible rather than becoming fictitious full fills. A supplied
quote path is required: OHLC-only data cannot specify which protective level came
first and is not accepted as an execution dataset. Unobserved intervals are not
assumed to have remained inside stops. This first version reports observed-path
results without claiming interval completeness or conservative OHLC reconstruction.

## Reproducible local example

Run from the repository with the package installed (or `PYTHONPATH=src;.` on Windows):

```text
python -m tools.fixtures.b01_replay --output .local/b01-example
python -m fx_talanta.research.replay register --dataset .local/b01-example/dataset.json --experiment .local/b01-example/experiment.json --directory .local/b01-experiment
python -m fx_talanta.research.replay run --dataset .local/b01-example/dataset.json --directory .local/b01-experiment --partition training
```

The example is explicitly SYNTHETIC and covers training mechanics only. It is not
historical data, and its validation/holdout intervals deliberately have no quotes.
The actual checked run is summarized in [replay evidence](../evidence/m3-synthetic-replay.json).

Registration precedes execution and pins dataset bytes, relevant engine sources,
strategy/cost/policy settings and chronological training/validation/holdout boundaries.
Validation requires verified training artifacts; holdout requires verified training
and validation artifacts. Each partition directory is created exclusively, including
failed attempts, so the CLI cannot silently rerun or overwrite it. Modified inputs
require a distinct retained experiment. Hashes detect changed artifacts; they are not
an external attestation or a security boundary against someone rewriting the registry.
Researchers must retain all registered variants and must not reuse an examined
holdout to claim an untouched out-of-sample test.

Each completed run exports results, the hash-chained journal (including decision,
risk and execution records), and checksums. Output includes costs, realized P&L,
observed equity/drawdown, closed trades, net expectancy, pending orders and open
exposure. No annualized ratios or economic significance are inferred from a tiny
sample. Calendar/news booleans are scenario assertions, never promotion of an M1
provider. All results retain `execution_enabled=false`, `m1_qualified=false` and
`economic_acceptance=false`.

## Remaining M3 acceptance

The [first historical pilot](m3-historical-data.md) now covers HistData ingestion,
fixed-EST conversion and six bounded replay scenarios. It produced no closed trades
and is insufficient for economic selection. Equal-time quotes with explicit source
sequences are retained; unsequenced ties remain invalid.

This PR delivers the integrated offline research path, not economic acceptance:

- Source-backed historical bid/ask datasets with reconciled availability, session
  gaps, revisions and calendar/news inputs remain required.
- Frozen multi-fold walk-forward experiments, retained alternatives and an actually
  untouched historical holdout still need to be run and evaluated. One chronological
  validation partition is not a completed walk-forward study.
- Conservative OHLC ambiguity handling, broker-specific rollover costs, and required
  independent/native indicator parity remain open before broader research claims.
- A reproducible historical comparison and uncertainty-aware economic report remain
  required; synthetic loss/profit is not strategy performance evidence.

M1 operational requirements and broader M2 fault acceptance remain recorded. This
work does not enable connected strategy PAPER, change the two-second entry ceiling,
start a campaign or authorize any broker order.
