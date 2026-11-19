# Session-aware strategy research

FX-Talanta can condition research entries on a named session and use a defined
session range instead of treating every rolling lookback as equivalent. This is
research functionality; trading remains disabled and no session is assumed profitable.

## Owner and AI workflow

1. In **Backtest → Session-aware rules**, choose an entry session and breakout
   reference, then apply them to the reviewed JSON. Applying settings clears the
   review confirmation. Risk policy, stop multiplier and other rules are untouched.
   AI proposals can also supply these fields; the owner reviews them before testing.
2. Run a newly registered strategy using the existing research workflow. New results
   include session attribution. Existing results retain their original hashes and
   rules; **Diagnose and improve** creates a separate retrospective session report.
3. Inspect **Session results** in Results or Improve. Exports preserve exact amounts,
   definitions, sample counts, limitations and source bindings.
4. **Generate AI diagnosis** now sends these measured session results, costs, risk
   limits, known coverage limitations and any verified risk-halt diagnosis to the model.
   It must distinguish evidence from hypotheses and can recommend investigation
   instead of a rule change. A reviewed revision may change one supported field;
   risk limits and the original comparison inputs remain protected.

## Session conventions

These are versioned research conventions, not centralized FX exchange schedules,
market-holiday calendars or guarantees of liquidity. Intervals include the start
and exclude the end. Only local weekdays are active.

| Session | Local interval | Time zone |
| --- | --- | --- |
| Tokyo | 09:00–18:00 | Asia/Tokyo |
| London | 08:00–17:00 | Europe/London |
| New York | 08:00–17:00 | America/New_York |

The application loads packaged **tzdata 2026.6** explicitly on Windows and Linux.
London and New York change clocks independently, including their mismatch weeks.
The session code and tzdata version are included in the registered engine hash.
Tokyo/London and London/New York overlaps are distinct reporting buckets; a trade
is counted once, not added to multiple session totals.

`entry_session` accepts `UTC_WINDOW` (legacy), `TOKYO`, `LONDON`, `NEW_YORK` or
`LONDON_NEW_YORK_OVERLAP`. The existing UTC window remains an additional cap.
Named sessions cap signal expiry and the time exit; pending signals cannot leak
past the session end. The planner accounts for the session/UTC intersection using
the prior year's weekday clock conventions as a planning proxy, not a measured
trade frequency. A disjoint window is rejected.

## Reference ranges

- `ROLLING`: the preceding `signal_period` completed M15 bars. Legacy rules default
  to this, with `UTC_WINDOW`, preserving their meaning.
- `CURRENT_SESSION`: all complete M15 reference bars from the selected named
  session's start up to, but not including, the signal candle. At least one is
  required and the sequence must be complete.
- `PREVIOUS_COMPLETED_TOKYO`: the latest fully completed weekday Tokyo range,
  no more than 24 hours old. The full nine-hour range requires 36 M15 bars. If
  today's range still contains the signal candle or is unfinished, only a valid
  prior completed range can qualify. A Friday range cannot silently become Monday's.

The latter two require `TREND_BREAKOUT`. `signal_period` does not set their range
length, so changing that inactive parameter cannot create an AI revision. H1 trend,
ATR protection, risk sizing, spread and two-second freshness checks remain unchanged.
Only bars visible by the decision cutoff are used; missing required reference bars
produce `REFERENCE_RANGE_INCOMPLETE`, never an inferred range.

## Attribution and limitations

Closed positions are grouped by their **entry** session combination. Net P&L sums
retained realized deal amounts, including recorded fees. Open-position charges,
separate financing and finite-precision reconciliation residuals are reported as
unattributed rather than allocated inventively. Closed-trade drawdown is the maximum
decline of a bucket's cumulative closed-trade P&L; it is not marked-equity or
intratrade drawdown and must not replace the strategy's risk metrics.

Reports retain evaluation and signal counts separately before and after a measured
halt. Blocked post-halt signals are not executable trading opportunities. Fewer
than 20 closed trades produces an explicit sample warning; 20 is a descriptive
threshold, not a qualification gate or statistical significance claim. The current
report does not invent session-specific spreads, volatility, news exposure or causal
performance estimates that were not measured.

Old engines/results remain frozen. An AI diagnosis based on an older engine can be
reviewed, but executing a revision comparison requires a new matched baseline under
the current engine. The system does not silently replace the engine or launch a new
full study to obtain one. Previously exposed training/holdout data stays exposed.

## Actual acceptance

The original EURUSD study, its 24-bar revision and the original USDJPY study received
separate session reports. Their original result hashes stayed unchanged. Both EURUSD
trades entered during London/New York overlap; USDJPY's 23 trades span four combinations.
Every traded bucket has fewer than 20 trades. No session edge or promotion is inferred.

One real OpenAI request received the session evidence and verified EURUSD halt
reconstruction. It returned `INVESTIGATE_DATA_OR_POLICY`, preserving every rule and
explaining that the verified giveback-risk halt does not establish a session effect.
No actual strategy revision was automatically approved or executed.

Separate synthetic end-to-end acceptance exercised AI session proposal → owner
review → freeze → comparison → export/reload, plus session controls and JSON
persistence. Real Docker acceptance verified historical tables, exports, Chinese
labels, the saved model diagnosis and original evidence preservation. No new full
historical study, broker order or 24-hour campaign was started.

See [the acceptance receipt](../evidence/session-aware-research-20261118.json).
