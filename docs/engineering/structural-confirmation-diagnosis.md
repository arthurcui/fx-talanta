# Why the confirmation study produced no trades

Diagnosis of the retained June 1–12, 2026 EUR/USD development study, recorded
November 19, 2026. **No entry candidate reached risk admission.** The zero-trade
result comes from the setup conditions and restricted input eligibility, not an
order failure, insufficient risk budget, the two-second quote limit, or a HALT.
Neither arm was rerun. No strategy, risk policy, broker state or deployment changed.

Subsequent owner-authorized work is recorded separately in the
[corrected-input comparison](structural-input-repair.md). The diagnosis and
original results below describe the earlier, unchanged study.

## What happened to the opportunities

The frozen confirmation arm recorded 951 decisions, all HOLD. The ordered funnel
was **13 watched levels → 4 touches → 1 bounce → 0 retests → 0 confirmations →
0 entry candidates → 0 trades**. These are nested counts, not independent samples.

The 13 terminal outcomes reconcile exactly:

| Path | Opportunities | Explanation |
| --- | ---: | --- |
| Untouched, expired | 6 | Level age or London-session deadline reached |
| Untouched, invalidated | 2 | Touching/crossing bar breached the structural stop before a valid touch |
| Untouched, invalidated | 1 | H1 trend no longer agreed |
| Touched, invalidated | 3 | Next M15 bar breached the stop before a qualifying bounce |
| Touched, bounced, expired | 1 | No later return to the zone before the original two-hour deadline |

The four touched paths are individually inspectable below. Times are UTC; June
London local time is one hour ahead. The last column belongs to the existing
first-touch **control**, not a hypothetical confirmation entry.

| First touch | Side | Confirmation path | Control net USD |
| --- | --- | --- | ---: |
| June 4, 07:30 | Sell | Stop invalidation at 07:45 | −3.570861 |
| June 10, 13:45 | Sell | Stop invalidation at 14:00 | −3.360197 |
| June 11, 08:30 | Sell | Bounce at 08:45; no retest; expires 10:30 | +4.676178 |
| June 12, 08:30 | Buy | Stop invalidation at 08:45 | −1.840655 |

Waiting avoided the three stopped control entries and also missed its one winner.
That is a description of four paths, **not evidence of positive expectancy**.
The control lost USD 4.095535 after modeled costs. A later confirmation entry would
have a different price, distance to the fixed stop, size and target; it cannot
inherit the first-touch control's profit.

### A second, latent entry veto

All four touched setups also have `weakening=false`. The frozen proxy compares
the sum of the two latest M15 high–low ranges at first touch with the preceding
two. The recorded recent/prior pairs, in pips, are 9.3/6.5, 24.1/11.4, 15.6/9.6
and 16.9/12.8. Independent reconstruction from the original bars matches all four.

This veto is checked only after a subsequent retest and reversal, neither of
which occurred. Consequently `PULLBACK_NOT_WEAKENING` is absent from the final
HOLD-reason tally, although the stored condition would reject each of these four
paths if it reached that check. **Removing the second-retest requirement alone
would not make these observed opportunities eligible while this condition stays.**

Full candle range is not the same measurement as directional selling/buying
pressure into a level. A large wick or reversal can increase range. That is a
limitation of this proxy, not proof that a different momentum measure is profitable.
The implementation also requires distinct later bars for bounce, retest and
reversal; it deliberately does not infer their order inside a single OHLC candle.

## Input eligibility was materially restricted

There were 360 London **decision cutoffs**, 36 on each nominal weekday.
Only 200 passed the input gate; 160 (44.44%) were blocked. This denominator differs
from the 360 expected London bar closes in the original quality receipt: decision
cutoffs include the session-opening evaluation and exclude its closing evaluation.
Having every in-session bar does not establish complete preceding H1 context.

| H1 discontinuity present in the required recent context | Blocked London cutoffs |
| --- | ---: |
| Observed weekend boundary only | 72 |
| Month-file join omission only | 16 |
| Both | 72 |
| **Total, with overlap counted once** | **160** |

All 160 fail the 53-H1-bar clock-contiguity check. Eight also fail M15 contiguity;
these eight are already included, not extra blocked slots. None of these London
blocks is an expired quote or a risk-admission rejection. Four entire London
sessions (June 1, 2, 8, 9) and the first four hours on June 3 were excluded.

The EMA itself is not reset by this check. The evaluator instead vetoes inputs
unless its most recent 53 H1 bars are exactly one clock hour apart. Thus normal
weekend closure can prevent research through Monday and Tuesday even when enough
actual trading bars exist. Session definitions currently specify entry windows;
they do not supply a source-specific market-open completeness calendar.

### Confirmed month-boundary bar omission

Two H1 bars and two M15 bars are absent even though their underlying quote rows
are in the same prepared index:

| Timeframe / close (UTC, June 1) | Quotes present | Minutes containing a quote |
| --- | ---: | ---: |
| H1 / 05:00 | 1,283 | 60/60 |
| H1 / 06:00 | 708 | 60/60 |
| M15 / 05:00 | 240 | 15/15 |
| M15 / 05:15 | 221 | 15/15 |

The M15 counts are subsets of the H1 counts. This is a transformation defect,
not evidence that the underlying source had a two-hour outage. Nor does quote
presence in every minute certify continuous tick delivery or two-second freshness.

`research/tick_index.py::build_index` drops a bar if its opening boundary precedes
the file's first quote or its closing boundary follows the file's last quote.
The May archive ends at June 1 04:59:50.162 UTC; the June archive begins at
05:00:04.979 UTC. Each monthly index therefore drops its edge H1 and M15 bar.
`research/acquisition.py::prepare` merges ticks but copies these already-trimmed
bar lists without rebuilding the internal boundary. Both original monthly-index
hashes were verified against their receipts; only metadata was queried there.

HistData documents fixed EST without daylight-saving adjustments for these tick
files, so the month boundary maps to 05:00 UTC. Do not shift the archive timestamps
to make it resemble broker hours. [HistData file specification](https://www.histdata.com/f-a-q/data-files-detailed-specification/).

A timestamp-only sensitivity check inserts the four omitted bar *times* into a
temporary list and rechecks the original decision cutoffs. It restores input
eligibility at 16 additional June 3 cutoffs; 144 remain blocked at observed weekend
boundaries. This check runs no signal evaluation, EMA/ATR revision, order or P&L
simulation. It cannot predict how many additional setups or trades a corrected
study would produce.

## Recommended next revision

**First make a data-corrected, market-calendar-aware baseline with the same entry
rules. Do not optimize the entry sequence on this four-touch sample.** This is a
post-diagnosis proposal, not a completed repair, a new frozen run plan or execution
authorization.

The bounded repair scope is:

1. Build internal month-boundary bars from merged, ordered original quotes;
   reconcile OHLC against one-pass aggregation. Record genuine partial outer
   windows explicitly. Preserve the old index and every original result; publish
   a separately hashed corrected artifact.
2. Separate indicator history across **verified scheduled closures** from missing
   observations during expected trading. Keep 53 real H1 observations and closed-bar
   availability. Do not fabricate weekend candles, forward-fill unknown gaps,
   carry active setups across session expiry, or waive intraday gaps. A calendar
   must identify source, timezone, DST and closure boundaries. FOREX.com's published
   Sunday–Friday ET hours illustrate why closure is not an outage, but are not
   automatically the HistData source calendar. [FOREX.com hours](https://www.forex.com/en-ca/help-and-support/market-trading-hours/).
3. Retain the same EUR/USD development window, matched control, fixed levels,
   confirmation ordering, weakening proxy, stop, 2R target, deadlines, costs and
   risk policy. A later repair-verification comparison is still exposed development,
   not independent validation. Record how many decisions become eligible and why,
   before interpreting trade count or profit.

Acceptance for that revision is exact bar/quote reconciliation across the month
join; a scheduled closure that preserves real indicator history; an unexpected
in-session gap that still blocks; no future-bar access; and a clear eligibility
reason at each decision. The two-second entry rule, 0.10% per-trade/aggregate
caps, 1% daily limit, 5% drawdown limit, one-position limit and persistent HALT
semantics remain intact. More trades is not an engineering acceptance criterion.

After that repair, the next *entry hypothesis* worth examining is whether a
closed rejection at the first valid structural retest is sufficient, versus a
mandatory second return. However, this study supplies only one bounced path and
zero second retests, and its first-touch weakening proxy fails all four touches.
There is no defensible winning parameter choice here. Any later entry comparison
must preregister exactly which condition changes, retain both losses and missed
moves, and measure executable remaining reward/risk and costs from the later entry.
Do not remove both confirmation and weakening merely to capture the June 11 winner.
USD/JPY needs its own session/structure evidence; these EUR/USD results do not
transfer an edge to it.

## Evidence and reproduction

- [Original frozen study and unchanged verdict](structural-pullback-study.md).
- [Recomputed diagnosis](../evidence/structural-confirmation-diagnosis-20261119.json):
  all 13 paths, range comparisons, exact input-gate overlap, missing-bar provenance,
  timestamp-only sensitivity and source fingerprints.
- [Original monthly-index lineage](../evidence/structural-month-boundary-lineage-20261119.json):
  May/June source receipts, verified index hashes and file-edge timestamps.
- [Read-only analysis script](../../tools/research/diagnose_structural_confirmation.py).

From this checkout, run the script with the private retained study and a **new**
output path outside it:

```powershell
python tools/research/diagnose_structural_confirmation.py `
  .local/study-output/june-development `
  --output .local/confirmation-diagnosis/new-receipt.json
```

The script checks pinned inputs/results, opens SQLite read-only, reconciles all
951 original input-gate outcomes and rechecks every original study file hash
before/after (16 files). It imports no signal, broker, replay or model runner.
Raw historical prices stay private. No strategy rerun, held-out-price inspection,
provider qualification, campaign, model call or trading action occurred. PRs #65
and #66 remain unmerged; M1 gaps, B01 and earlier failures are unchanged.
