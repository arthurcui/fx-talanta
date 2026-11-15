# AI proposal and candidate-bound historical research

This workflow connects strategy authoring to the existing replay simulator. It is
offline research, not permission to trade or a claim of profitability. The Docker
preview has been updated to PR #65 with [direct local workspace access](../guides/local-signin.md); its saved strategies were preserved.

## Owner workflow

1. Open the local Docker preview directly (no account required). Optional
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
5. Select an available historical dataset in step 3. Inspect its source, exact
   chronological windows, qualification caveats and cost/risk assumptions. No file
   chooser is required. The server caps the selected policy to the frozen candidate
   limits, preserving the lower existing risk settings. Advanced import remains
   available for a custom JSON bundle containing `dataset`, `experiment`,
   `minimum_closed_trades` and `maximum_drawdown_fraction`.
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

## English / Chinese interface and translation

Use the header language selector to switch interface labels between English and
Simplified Chinese. Switching does not rewrite form values, saved specifications,
rule enums, identifiers or historical evidence. Evidence stays in its original
language. Both languages are accepted in strategy descriptions, research briefs
and advisor questions; proposal prose follows the brief language unless requested
otherwise. Executable JSON keys and enums remain unchanged.

The **Translate input (preview only)** panel accepts pasted prose and returns an
English or Chinese preview through the configured AI provider. Copy it manually
only after checking numbers and meaning. This never saves a candidate or updates
an input field. Clear, reload or leaving the page discards the translation. Neither
translation input nor output is written to the application journal, database or
browser storage. Requests use `store=false`; this is not a guarantee of zero
provider retention. Do not paste secrets. Twenty requests per server process,
4,000 input characters, 3,000 output tokens; no automatic retries. Failed requests
consume the process limit. Provider configuration is shared with proposals but
translation does not consume their durable ten-request research allowance.

Validation uses deterministic provider fixtures for both translation directions,
invalid inputs, no retries and request limits. Headless browser acceptance checks
language switching, unchanged strategy inputs and option values, translation
preview and clearing on reload. These tests do not qualify translation accuracy.

Two live preview translation smoke checks also completed (English to Chinese and
Chinese to English); both preserved the sample 0.10% risk value. These generic
checks are not a comprehensive semantic-accuracy evaluation.

## Proposal validation diagnostics

Two preview attempts returned `ValidationError`; their original receipts retained
only the error class, so the exact failing fields cannot be reconstructed. They
remain failed and were not resent. A distinct generic Chinese diagnostic proposal
passed validation. The prompt now states the cross-field constraints explicitly
(both pairs exactly once, ordered same-day session, percentage relationships and
minimum description lengths); the provider schema also fixes the pair count at two.
Future failures retain only validation field paths and error codes, never raw error
inputs or provider exception text. The UI explains failures instead of showing only
an opaque status, and failed jobs no longer appear as completed in the job list.

The revised prompt/schema passed an additional live end-to-end proposal generation
check in a temporary journal. It produced `AI_PROPOSAL` without changing the preview
research records or its request allowance. This is a smoke check, not a guarantee
that every generated proposal will satisfy all constraints.

The UI follows three numbered steps: (1) research brief and generated proposals,
(2) candidate review/save/freeze, (3) historical registration and backtesting.
No candidate fields are required for generation. Selecting a proposal populates
and focuses the review form. Manual creation remains an alternative; translation
is an optional disclosure beside the brief. Proposal cards are separate from
backtest results. Headless acceptance covers this ordering and transfer.

## Managed historical dataset selection

Configure `--research-datasets DIRECTORY` with up to eight bounded `*-bundle.json`
files. The preview mounts read-only copies of the existing EURUSD and USDJPY pilot
bundles, verified byte-for-byte against the originals. It does not mount the source
journal or broker credentials. Dates are January 16, 2025, approximately 37 and 35
minutes respectively, with 3,000 events and 1,283 bars each. They are short,
previously exposed, unqualified HistData research slices, not a new independent
holdout, complete historical coverage, or broker-calibrated prices/costs.

Catalog responses contain source and assumptions, windows, event/bar counts,
acceptance criteria, cost/risk policy and SHA-256 identities; never server paths or
raw quotes. Clients submit the selected hash, frozen candidate, rules and review
confirmation. Registration rechecks the source bytes, copies the exact dataset,
pins its catalog hash, and retains the original cost basis and windows. Only risk
fractions are capped downward against candidate limits. No resampling, broadened
risk, clock changes, market data fetch or broker connection occurs. Invalid,
changed or out-of-root sources fail closed. Existing registrations remain usable
from their pinned evidence even if the catalog file later changes.

Advanced imports require an explicit checkbox and retain the existing validation
path. Changing the selected dataset or import mode clears mapping confirmation.
Larger historical runs and custom date/window construction are not added here.

The CI regressions fixed alongside this work were an absent `local_workspace`
attribute in the existing deployment launcher and an unintentionally enlarged
chat request-body ceiling. The launcher defaults safely to authenticated mode;
the existing 4 KiB chat ceiling is restored while research briefs retain their
Unicode-sized request allowance.
