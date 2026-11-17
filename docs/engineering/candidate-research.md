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
5. Choose **Preview agent plan** to see the strategy-selected period and available
   data. **Run agent research** checks adequacy, selects both pairs' catalog inputs
   and drives the permitted stages. You do not need to choose dates or files.
   Inadequate inputs allow labeled exploratory training only, not full validation.
6. Inspect Results for each stage, data requirements, net P&L, trade count, drawdown,
   equity and recorded HOLD reasons. Export the agent report and underlying research
   evidence. Advanced controls retain manual dataset/partition selection and custom
   bundle import; all registrations cap risk to the lower frozen candidate limits.

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

Uploaded bundles retain the 2,000-bar/5,000-event interactive limit. Server-pinned
full-session indexes now use background streamed execution (see below), preserving
every tick with bounded memory. Neither path constitutes full R2 qualification.

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
Custom date/window construction remains outside this UI; full-session catalog
entries now provide longer fixed windows through the background path below.

The CI regressions fixed alongside this work were an absent `local_workspace`
attribute in the existing deployment launcher and an unintentionally enlarged
chat request-body ceiling. The launcher defaults safely to authenticated mode;
the existing 4 KiB chat ceiling is restored while research briefs retain their
Unicode-sized request allowance.

## Guided pages and strategy context

The primary navigation is Overview, Strategies, Market & Data, Advisor and
Activity. Strategies has a task sequence with real, reloadable URLs:
`/strategies/describe` → `/strategies/review` → `/strategies/backtest` →
`/strategies/results`. Browser Back/Forward works without submitting requests.
Legacy section links still route to their corresponding page.

Describe accepts English or Chinese instructions and displays retained proposals.
Review loads the chosen proposal and its executable mapping together. Save a
revision, freeze it, then choose Continue to backtest. The strategy name, version
and state remain visible throughout; its immutable hash is carried in the URL.
Saved strategies open directly in Review. Saving changes to a frozen version
creates a new revision; the frozen evidence is retained.

Backtest requires a frozen version, an explicitly reviewed rules mapping and a
historical dataset. **Run backtest** registers these inputs and executes the chosen
partition in one action, then opens Results. Separate registration and previous
registered studies remain under Advanced. File import remains optional. Invalid
input never submits; uncertain requests are not automatically resent. Results
are filtered to the selected version and retain export, costs, limitations and
verdict evidence. Missing or unknown candidate hashes show no other strategy's
results. Nothing here grants trading authority or changes qualification gates.

Within the browser tab, strategy draft fields, rules, proposal choice, dataset,
partition and registered-study choice survive navigation/reload. Mapping approval
is deliberately not persisted and must be checked again after reload or changing
inputs. Translation previews and credentials are never included in this state;
sign-out clears the tab's flow state. Server records are the source of truth for
saved/frozen versions. Reload validates the selected hash against returned records.
For older candidates without tab state, select a saved proposal and explicitly
load its rules; an exact provenance match (or sole available proposal) preselects
the dropdown but does not automatically assert mapping review.

## Actual Docker UI verification, November 16

Step 3 now provides a frozen-candidate selector directly. Selection is restored
from its hash in browser session storage after reloading, only if that record is
still returned as frozen by the server. This stores no translation or credentials;
clearing selection/signing out clears the preference. Mapping review is always
reset on selection, including restoration.

The actual running Docker preview was exercised headlessly, without route mocks,
using its retained AI proposal, real EURUSD catalog bundle and a separately named
`UI registration verification 2026-11-16` candidate. Existing candidate records
were not changed. Save/freeze, reload/restore, rule loading, registration, automatic
experiment selection, training backtest and result persistence succeeded. Both
registration and backtest returned HTTP 200; zero browser errors occurred. The
result was INSUFFICIENT_EVIDENCE with zero closed trades. The test candidate and
its evidence are retained in the preview, clearly separate from the owner's work.
See [actual UI receipt](../evidence/docker-registration-ui-20261116.json).


## Separate-page acceptance, November 16

Browser regression coverage exercises the guided flow, direct URL reload,
Back/Forward, saved and unsaved context, result isolation, Chinese labels, mobile
width, mapping reapproval and refusal to backtest unsaved changes. The real Docker
preview also uses retained model output and an actual historical catalog bundle,
without mocked HTTP responses or new model calls. Its INSUFFICIENT_EVIDENCE result
is a workflow verification, not a strategy qualification. See the
[Docker guided-page receipt](../evidence/docker-guided-pages-20261116.json).

## Local preview restart recovery

A Docker rebuild rotates the local CSRF value. An already-open tab now refreshes
its local connection on a rejected request without showing sign-in or clearing
its draft/context. The rejected action is never resent automatically; the UI asks
the user to review and submit again. Authenticated deployments retain ordinary
session-expiry behavior and all Host/Origin/CSRF checks remain enforced.

Verified against an actual preview restart with an open background browser:
no sign-in page, preserved draft across reload, one rejected write with no resend,
and unchanged saved strategy hashes. See
[restart receipt](../evidence/docker-local-recovery-20261116.json).

## Full-session catalog and result diagnostics

The preview now adds **EUR/USD and USD/JPY, January 21–23, 2025**: three complete
24-hour partitions per pair (training, validation, previously available holdout).
Each has 312 pre-start H1 and 1,254 M15 bars, sufficient to initialize the supported
H1 trend/M15 breakout or pullback rules. Every selected tick is replayed in source
order, including timestamp ties. No sparse sampling or invented quotes are used.
The earlier tiny bundles and all old results remain intact.

| Pair | Training ticks | Validation ticks | Holdout ticks | Total |
| --- | ---: | ---: | ---: | ---: |
| EUR/USD | 122,952 | 88,605 | 101,193 | 312,750 |
| USD/JPY | 167,688 | 115,620 | 117,768 | 401,076 |

**Tested symbol** explicitly filters dataset choices. The strategy specification
covers both permitted pairs, but a study still tests one selected pair; the name
of a strategy is not a symbol binding. Results display the actual pair, UTC bounds,
duration, number of evaluations, candidate signals, closed trades and recorded
hold reasons. Zero closed trades are distinguished from no signals, no evaluations
and positions still open. Diagnostics are derived from retained decisions, so old
results become explainable without rerunning or rewriting their evidence.

Long studies run in a single bounded background worker. Durable admission prevents
duplicate starts; browser reload only observes progress. A process interruption is
reported as INTERRUPTED_NO_RESEND, never silently restarted. Full tick processing
uses the existing streamed simulator engine and bounded compressed journal/equity
spools. Result exports contain sampled chart values, full decisions/trades and
hash receipts for the exact local audit streams under the private state directory.
They do not embed the entire tick archive or gzip streams. At most one background
run is admitted at a time; each partition remains bounded to 300,000 ticks/one day.

The index and manifest are pinned by SHA-256; bindings are checked before and after
replay. Index files are read-only copies mounted in the preview catalog. Create a
catalog reproducibly from an existing full-session plan and local indexes:

```powershell
python -m tools.dev.catalog_sessions --plan PLAN.json --index EURUSD=EURUSD_INDEX.sqlite --index USDJPY=USDJPY_INDEX.sqlite --output CATALOG_DIRECTORY
```

This preserves the prior M3 sources, B01 verdict and M1 gaps. The existing dataset
assumption remains counterfactual: calendar/news are assumed clear, receipt latency
is modeled at 250 ms, and costs are uncalibrated. Previously exposed January data
is not a fresh independent holdout. Three days provide more signal opportunities
than the original minutes-long slices, but do not establish profitability or
permission for PAPER/LIVE promotion. Trading remains disabled.

Actual Docker acceptance exercised the owner's retained strategy with each pair's
24-hour validation window, without mocked responses or new AI calls. EUR/USD
processed 88,605 ticks and produced 96 evaluations, five candidate signals and one
closed simulated trade. USD/JPY processed 115,620 ticks and produced 96 evaluations,
seven candidate signals and one closed simulated trade. Both remain
INSUFFICIENT_EVIDENCE. Reload during processing, completed result display and
browser export passed. The earlier 11-minute zero-trade result now explicitly
shows USD/JPY, one evaluation and NO_SIGNAL without changing its retained record.
See [actual full-history receipt](../evidence/docker-full-history-20261116.json)
and [catalog/source receipt](../evidence/historical-catalog-20261116.json).

## Agent-selected periods and staged validation

The default Backtest page now asks the owner to review executable rules and select
**Run agent research**. The agent chooses both pairs' catalog inputs and stages;
manual dataset/partition selection remains under Advanced. Preview agent plan
explains the requested dates, warmup, available dates, age, coverage gaps and why a
stage is blocked. Results retain progress, stage decisions and a downloadable
agent report. A reload observes the same job rather than creating another one.

`dashboard/validation_agent.py` implements versioned policy `strategy-validation/1`.
The model authors the strategy; a deterministic strategy-aware planner chooses the
research period before looking at outcomes. It does not ask a model to guess dates
or search for a profitable window. The initial planning heuristic uses active UTC
hours, M15 signal lookback and holding bars to request at least 126 weekday sessions,
or more for slower/narrower-session rules. Targets are 100/50/50 closed trades in
chronological 60/20/20 development/validation/holdout windows. These are engineering
planning assumptions, not statistical power guarantees or measured trade frequency.
Actual observations determine whether a stage has enough evidence.

The requested end is the current UTC day's start. Catalog selection ranks overlap
with the requested dates, then duration, recency and stable identity, never P&L.
Checks include H1/M15 warmup, history length, requested-date coverage, source/cost/
calendar qualification, independent holdout evidence and exact planned window
bindings. Weekday counts are a preliminary availability estimate, not proof of
complete market sessions. The current catalog is explicitly unqualified, so it
cannot pass the full data gate regardless of a profitable exploratory result.

The worker automatically registers the reviewed frozen strategy and runs available
training partitions for each pair. With inadequate data those are explicitly
EXPLORATORY_ONLY: the existing catalog windows are used and disclosed, not relabeled
as the requested recent period. Validation and holdout stay closed. With qualified,
exactly matched windows, the staged coordinator requires sufficient closed trades,
settled positions, positive net P&L and preserved drawdown/underlying study gates
before advancing. This staged coordinator is regression-tested with controlled
outcomes; full qualified-window execution is not demonstrated by today's catalog.
Walk-forward robustness, stress costs, benchmarks, uncertainty and combined-portfolio
validation remain R2 requirements. No stage grants PAPER or LIVE authority.

Admission is durable and at-most-once per plan. Changed catalog manifests are refused;
manual replay cannot compete with an active agent. Interrupted or uncertain work is
reported without automatic resend. Prior results, exposed holdouts and B01 remain
unchanged. Automatic acquisition is now available through the explicitly configured fixed
provider described below. Downloaded prices remain unqualified research inputs.

Owner walkthrough: **Strategies → select frozen strategy → Backtest → Load proposal
rules for review → review mapping → Preview agent plan → Run agent research → Results**.
No dates, symbols, datasets or partitions need to be selected on the default path.

Actual Docker acceptance used the owner's existing frozen strategy and retained AI
rules with no new model calls, mocked responses or manual date/dataset selection.
The plan requested 126 sessions from May 24 to November 17, 2026 (UTC). The catalog
has three January 2025 sessions per pair, outside those requested dates. The agent
ran each available training day: EUR/USD 122,952 ticks, eight candidate signals,
one closed simulated trade; USD/JPY 167,688 ticks, three candidate signals, one
closed simulated trade. Both failed the 100-trade training target; final state was
DATA_REQUIRED, not strategy acceptance. No validation or holdout was opened by this
agent run. Earlier standalone validation evidence remains unchanged.

Actual UI verification covered plan preview, start, reload while processing, final
results, report export, container-restart persistence, duplicate-start returning
the original job and mobile width. A test-receipt script initially expected derived
diagnostics in the raw immutable item; it was corrected to read the existing summary
API. The completed studies were not repeated. See
[Docker agent validation receipt](../evidence/docker-agent-validation-20261116.json).

## Automatic historical acquisition (November 17)

Set `FX_HISTORY_ACQUISITION=histdata` explicitly on the research service to enable
fixed-origin downloads. The local Docker preview enables this setting. It does not
configure broker connections or trading. With acquisition disabled, existing
catalog-only behavior remains available. **Run agent research** now acquires missing
history before replay; the UI shows downloading month, preparation and study stages.
No file upload or manually selected dates are needed on this path.

The provider is HistData's public monthly ASCII bid/ask tick ZIP download form.
Only EURUSD and USDJPY are supported. HTTPS origin is pinned to www.histdata.com;
redirects to another host or plaintext are refused. Download form identity, ZIP
signature, byte limits, original archive SHA-256, member/month validation and price
validation are checked. Requests are serial with bounded timeouts, no paid service,
no account credentials and no automatic retries on provider errors. The form token
is transient and never included in receipts. HTTP errors remain failures, not empty
market sessions. Source archives are private and not committed or redistributed.

Preparation downloads the months covering the fixed research period plus warmup.
Completed months are cached immutably; the current month has a dated snapshot key
so later plans can acquire a newer version without replacing old evidence. Cache
and prepared index hashes are checked before reuse. Interrupted preparation is
preserved rather than overwritten. The job itself remains at-most-once; a stopped
job is not automatically restarted. Templates retain reviewed risk/cost assumptions;
expired dated broker costs are not silently extended.

October's actual EURUSD source contained reversed timestamps. The default legacy
importer still rejects these. The acquisition path explicitly uses stable sorting
by timestamp and original row sequence, retaining original ZIPs and a source-order
SQLite journal. Equal-time ticks and duplicates remain intact; no prices/ticks are
invented or sampled. The first rejected import was retained privately. UTC mapping
continues to use the existing fixed-EST HistData convention. Gaps, observed days,
missing weekdays and end lag are reported, not equated with certified coverage.

Prepared data is registered in a separate private catalog under the dashboard state
and restored on server restart. New acquisitions can span up to 366 days per
partition, 50 million ticks per index/partition and 14 source months, with streaming
replay and disk-backed normalization. Legacy catalog limits remain one day/300,000
ticks. Larger studies may take substantial time and several GB of disk. Existing
registrations retain their original engine hash and cannot execute against changed
code; their saved results and all B01/M1 evidence remain untouched.

Acquisition does **not** qualify source reliability, receipt timing, broker costs,
calendar/news or untouched holdout evidence. Training uses explicitly disclosed
assumed-clear calendar/news and modeled receipt latency for exploratory research.
Missing warmup prevents replay. Later stages remain gated; no result grants trading
permission. Walk-forward/portfolio robustness remains separate work.

Verification: real October 2026 archives downloaded for both pairs on the host and
inside Docker, with matching SHA-256 identities. An isolated Docker acceptance
store exercised UI start → verified cache → preparation → training → result/export,
using three explicitly bounded one-hour windows, not the full 126-session plan.
Prepared inputs contained 790,379 EURUSD and 981,596 USDJPY ticks including warmup;
both training studies finished, returned insufficient observations and opened no
holdout. Reload and report export passed. The normal preview retains the full
agent-selected horizon; this acceptance override exists only in the private test
server, not production code. See
[actual Docker receipt](../evidence/history-acquisition-docker-20261117.json).

The full six-month study has not been run to completion by this acceptance test.
The production button can acquire and prepare that plan automatically; a successful
download alone never changes the strategy's qualification verdict.
