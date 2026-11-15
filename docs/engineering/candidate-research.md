# AI proposal and candidate-bound historical research

This workflow connects strategy authoring to the existing replay simulator. It is
offline research, not permission to trade or a claim of profitability. The Docker
preview built for PR #64 remains on that image until explicitly rebuilt; changing
source does not change the running preview or delete its saved strategies.

## Owner workflow

1. Start the dashboard with its usual private session launcher. Optional
   `--research-key-file PATH` enables the existing OpenAI transport using an ignored
   dotenv file containing `OPENAI_API_KEY`. Never put the key into the browser.
   Without that flag, manually reviewed candidates and backtests still work.
2. Enter a generic research brief. Generate a proposal, then choose **Review proposal
   in form**. Inspect the model receipt, proposed percentages, descriptive rules and
   executable parameters. Generation does not save or freeze a candidate for you.
3. Edit, save and freeze the candidate. Select its exact frozen version. Freezing
   descriptive prose alone still does not establish executable semantics.
4. Supply the supported executable-rule JSON and explicitly confirm the reviewed
   mapping. Differences from the prose must be treated as research assumptions;
   the application cannot prove that a human review was correct.
5. Upload a JSON research bundle containing `dataset`, `experiment`,
   `minimum_closed_trades` and `maximum_drawdown_fraction`. The existing replay
   `Dataset` and `Experiment` schemas apply: source/availability timestamps, bars,
   market events, chronological training/validation/holdout boundaries, cost basis
   and deterministic risk policy. Policy percentages cannot exceed the candidate.
6. Register before execution; choose a partition and run. Inspect verdict, net P&L,
   trade count, observed drawdown, equity chart, deals and costs. Export the exact
   evidence, including registration, candidate hash and simulator journal. Display
   charts are reduced samples; exports retain all observations.

For a runnable **synthetic** upload (not historical evidence):

```powershell
python -m tools.fixtures.candidate_research > synthetic-research-bundle.json
```

Use a breakout mapping with `trend_period=50`, `signal_period=20`, `atr_period=14`,
`stop_atr="1.5"`, `reward_risk="2"`, `hold_bars=16`, UTC session hours 0–23 and
`calendar_policy="REQUIRE_MARKET_HEALTH"`. The fixture produces a costed loss; the
expected assessment is **REJECT_OR_REVISE**, not successful strategy qualification.
Historical bundles can use the existing HistData import pipeline. Source receipt
times, calendar availability and broker costs must retain their original caveats.

## Executable boundary

Only two reviewed kernels execute: H1 EMA trend with M15 preceding-range breakout,
or M15 EMA crossing after a pullback. H1 trend slope compares the current EMA with
three H1 bars earlier. ATR is the simple mean of the last registered true ranges,
not Wilder smoothing. Stop and target distances round upward to native tick size.
Time exits and UTC weekday sessions are fixed parameters. Future revisions are
invisible until their availability time. Entry remains subject to the existing
two-second quote limit, protection, exposure and risk simulator.

No Python/MQL or expressions returned by the model are evaluated. Unsupported
families/fields are rejected. Calendar veto uses the supplied historical Market
health; this does not implement an arbitrary prose blackout or news strategy.
Each run contains one symbol and one position at a time. Combined EURUSD/USDJPY
portfolio testing and signed USD exposure evaluation across simultaneous symbols
remain open, rather than being inferred by adding two independent equity curves.

Interactive bounds: 2,000 bars and 5,000 market events per registration. Larger
historical studies remain in the CLI research pipeline pending integration of its
streamed execution into this UI. This bounded integration is not full R2 closure.

## Authority, retries and evidence

- AI calls require explicit server configuration. One store permits at most ten
  requests, each capped at 3,000 output tokens; this is a request/token ceiling,
  not a billing guarantee. The existing TLS-only, fixed-endpoint, no-redirect
  transport is reused. No broker credentials or account data enter the prompt.
- A durable request identity is reserved before dispatch. Conflicting retries are
  rejected. Failure, crash or uncertain completion never permits an automatic
  resend. Model name, request/response hashes, usage and parsed proposal are retained.
- Registration pins the replay and candidate-kernel source hashes; changed engines cannot execute an old registration. Registration, exposure and results are immutable. A partition exposure is written
  before running; an interrupted run remains exposed without result and cannot be
  silently rerun. Completed retries return the original result. A new registration
  is a new experiment; it does not make previously seen holdout data untouched.
- Closing the browser does not cancel a synchronous server calculation. Refresh
  research evidence after a timeout. No broker state or trading authority exists in
  this path. Dedicated queued cancellation/large-study workers remain future work.
- Verdicts are **INSUFFICIENT_EVIDENCE**, **REJECT_OR_REVISE**, or
  **FURTHER_VALIDATION_REQUIRED**. No result grants PAPER/LIVE eligibility. Minimum
  sample and drawdown criteria are registered by the researcher, not supplied by AI
  after seeing results. Qualified inputs/costs, robustness and independent holdouts
  are still required before promotion.

## Actual evidence

The [integration receipt](../evidence/r1-r2-integration-20261115.json) records a real
OpenAI proposal and bounded runs using retained, previously exposed EURUSD/USDJPY
historical inputs. Each used an exact contiguous 3,000-event prefix, not resampled
ticks. Both produced zero closed trades and **INSUFFICIENT_EVIDENCE**. They verify
plumbing only. The first provider attempt failed decimal schema validation; it was
retained privately, the schema was corrected to decimal strings, and a distinct
bounded request succeeded. No failed request was relabelled successful.

Synthetic acceptance exercises a closed trade with costs and a rejected verdict.
Browser acceptance covers freeze, registration, run, chart, retained result and reload.
Tests preserve the original B01 result hash, future-data exclusion, percentage limits,
provider retry conflicts and uncertain outcomes. All M1–M3 gaps and the existing B01
**REJECT_FOR_PROMOTION** verdict remain unchanged. No campaign or broker connection.
