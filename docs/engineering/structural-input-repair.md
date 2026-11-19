# Corrected structural research inputs

The owner authorized a separate rerun of the June 1–12, 2026 EUR/USD comparison
after the [no-trade diagnosis](structural-confirmation-diagnosis.md). Trading stays
disabled. This is an exposed development comparison, not a new 24-hour campaign,
an independent validation sample, or PAPER/LIVE qualification.

## Exact repair scope

Historical acquisition now constructs H1/M15 bid candles from the merged,
time-ordered original quotes, instead of merging monthly candle lists that had
already lost their edge bars. The coverage window is explicit. Partial outer
buckets are recorded and excluded; absent buckets are never forward-filled.
Source month selection uses HistData's fixed-EST date convention. Preparation
version 2 creates a new cache identity, preserving version 1 files and receipts.

For this comparison, the new index restores **exactly four** missing candles:
June 1 H1 closes 05:00/06:00 UTC and M15 closes 05:00/05:15 UTC. All 1,796 original
bars are identical; the corrected index contains 1,800. All 660,471 development
quote rows, including source sequence, timestamps, bid and ask, are identical.
The bar builder reads 927,756 quotes including preceding warmup; that larger
number is not the number of observations traded in either comparison arm.

Weekend continuity is an explicit input-calendar contract bound to the exact
corrected index, symbol, development interval and reconciliation receipt. The
two allowed closures are May 29 22:00 → May 31 22:00 UTC and June 5 22:00 →
June 7 22:00 UTC. Original quotes confirm no observations inside either interval
and quote-bearing H1/M15 candles immediately on both sides.

The exception requires the exact flanking candles. A missing reopening candle,
an unlisted weekend, a missing weekday bar or a closure beyond the reviewed
interval still fails continuity. With no bound input calendar, strict clock
continuity remains the default. Calendars cannot be attached to a different
dataset or a validation/holdout-enabled bundle. No weekend prices are fabricated.

The last 53 actual H1 bars can now supply indicator history across a reviewed
closure. H1 price recency and original quote freshness are unchanged. Swing-pivot
contiguity and active-setup sequencing remain strict; deadlines still expire
setups and do not carry them over a weekend. The contract changes input continuity,
not structural entry rules.

**Source limitation:** this is an archive-reconciled research convention, not a
provider-certified trading calendar. HistData documents fixed EST without DST
and warns that pauses can create gaps, but does not publish the authoritative
session calendar used here. The archive clock is not shifted to FOREX.com's
summer clock. London entry windows still use the original DST-aware timezone.
[HistData FAQ](https://www.histdata.com/f-a-q/),
[timestamp specification](https://www.histdata.com/f-a-q/data-files-detailed-specification/).
This remains part of unqualified historical research, not resolved M1 delivery evidence.

## Frozen comparison

The corrected run uses commit `94d354f` from an immutable source snapshot in a
separate container with networking disabled and no broker/model credentials.
Its engine SHA is
`8f322a43123f96c0db1927e50d9cce1ed6540d11b3f683a899af7c8140942609`.
The corrected index SHA is
`36e344a17c30cb98b822e5fd1838ed182d078c6b00bdaa198b45dce39ebe0a5b`;
manifest digest is
`55c17cf359f23b6e09486bc2d85da2ed4ababb77890e8a021c877447add809de`.

Both arms retain the original experiment window, confirmation/first-touch rules,
EMA/ATR parameters, fixed structural levels, 2R target, eight-bar confirmation
deadline, 16-bar time exit, session end, costs and 250 ms modeled availability.
The risk policies compare exactly: 0.10% per trade and aggregate, 1% daily loss,
5% drawdown, one position, two-second quote ceiling, conservative lifecycle sizing
and persistent HALT semantics. Calendar/news remain counterfactually clear and
broker costs uncalibrated. No USD/JPY or held-out-price study was added.

## Results and evidence

Both corrected arms completed and settled. They share the same 22 opportunity
identities, geometry and transition sequences. Every one of the 16 original study
files still matches its pre-rerun fingerprint. Original zero-trade and losing-control
evidence remains immutable.

| Measure | Original inputs | Corrected inputs |
| --- | ---: | ---: |
| Original quotes per arm | 660,471 | 660,471 |
| Real H1/M15 bars including warmup | 1,796 | 1,800 |
| London cutoffs passing the input gate | 200 / 360 | 360 / 360 |
| Watched levels, shared by both arms | 13 | 22 |
| Touches / bounces / retests / confirmations | 4 / 1 / 0 / 0 | 5 / 2 / 1 / 0 |
| Confirmation closed trades | 0 | 0 |
| First-touch closed trades / winners | 4 / 1 | 5 / 1 |
| First-touch net P&L (USD) | -4.0955352483 | -7.6160212566 |
| First-touch commission / financing (USD) | 2.32 / 0.0055352483 | 2.96 / 0.0060212566 |
| First-touch maximum observed equity drawdown | 0.0889043603% | 0.1241067562% |
| Persistent risk or integrity HALT, either arm | None | None |
| Unsettled positions or orders, either arm | None | None |

Spread and adverse slippage are already in bid/ask fills, not subtracted again.
The confirmation arm has zero P&L and drawdown. Its 953 signal decisions all say
HOLD; no entry candidate reaches risk admission. Three input rejections remain
outside London at Sunday reopening before a current closed H1 exists. They are
valid recency failures, not missing London decisions or waived freshness rules.

The corrected confirmation funnel ends in 12 expired and 10 invalidated setups.
All five touches fail the unchanged first-touch weakening-range proxy. One sell
setup on June 8 now reaches a bounce and retest: watched 11:00, touched 12:30,
bounced 12:45 and retested 13:00 UTC, then invalidated at 14:15 when its structural
stop was crossed. These are closed-bar times; recorded availability adds the
same modeled 250 ms. It never satisfies all confirmation conditions. Removing
only the second-retest requirement still would not resolve the failed weakening
condition. No entry filter was relaxed and no new parameter trial was run.

**Interpretation:** the input repair worked; it did not establish a profitable
strategy. More of the intended London sample is now evaluable, but the confirmation
strategy remains untraded and the control remains negative after modeled costs.
Zero trades cannot estimate confirmation expectancy, and five control trades
cannot establish an edge. The economic verdict remains **INSUFFICIENT_EVIDENCE**.
The entire slice was already exposed; these are development results, not a fresh
holdout or a reason to promote either arm. B01 and M1 qualification gaps remain.

The [independent result receipt](../evidence/structural-input-repair-20261119.json)
checks original-file fingerprints, all original quotes/bars, reconstructed added
OHLC, both full journal chains, all 1,320,942 equity observations, ten fills against
original quotes, fees, financing, P&L, drawdown and unchanged risk admission.
The [weekend reconciliation](../evidence/structural-weekend-reconciliation-20261119.json)
retains source hashes, exact closure boundaries, flanking observations and the
explicit calendar limitation. No broker connection, model call, trading activation,
validation/holdout replay or campaign was involved.

## Verification and reproducibility

The focused regressions cover the actual monthly-file omission, stable timestamp
ties, partial outer windows, no fill of missing candles, preserving an old cache,
exact weekend boundaries, a lost reopening bar, an unexpected weekday gap,
point-in-time visibility, and index/development-scope binding. The host suite
passed 1,427 tests with 145 environment-dependent skips; the strengthened binding
and cache regressions passed separately. All 36 B01 numerical parity cases passed.
The initial sandbox attempt could not atomically replace a test file; the host
rerun used a new isolated test directory and completed without that failure.

The first remote check of `3d73943` passed all 1,573 integration tests and the
Docker suite (1,572 passed, one platform skip), but one owner sign-in browser test
reported `Cannot set properties of null (setting 'onclick')`. Its saved error
artifact remains in [that CI run](https://github.com/arthurcui/fx-talanta/actions/runs/44596816562).
The other 21 browser tests passed, including structural research. Twenty-five
isolated local repetitions of the sign-in test passed; the cause is not proven.
The test now retains the full error stack on recurrence. No assertion was removed,
automatic retry enabled, or application behavior changed to mask this finding.
Later CI status is tracked on PR #66 separately from the completed study evidence.

A [second CI attempt](https://github.com/arthurcui/fx-talanta/actions/runs/44599159570)
passed the owner-session test but exposed a separate test-locator ambiguity:
the hidden Results page and active Improve page both retain session reports.
The improvement test now scopes inspection/export to the active panel and waits
for both reports to exist, reproducing the ambiguous condition deliberately.
This is a test correction, not an application or research-runtime change.

The non-production preparer is
[`correct_structural_inputs.py`](../../tools/research/correct_structural_inputs.py).
It opens the parent and original study read-only, asserts an exact four-bar delta,
copies unchanged development ticks, reconciles the explicit closures and pins the
new bundle/manifest before execution. The existing
[`structural_study.py`](../../tools/research/structural_study.py) executes one
exclusive attempt for each arm; no retry or original-state replacement is used.
[`verify_corrected_structural_study.py`](../../tools/research/verify_corrected_structural_study.py)
independently compares original records, reconstructs restored OHLC, and checks
journal chains, every equity observation, original quotes for fills, cost arithmetic
and risk admission through the retained independent verifier.
