# Recorded model-selection integration, simulation only

The incremental runner can now consume bounded recorded model replies instead of only
`SCRIPTED_TEST_DOUBLE`. `RECORDED_MODEL_RESPONSES` exercises selection validation,
matched-arm timing, response failures, token/cost evidence and restart through the
existing simulator. It contains no provider transport, credentials, API call, broker
adapter or campaign activation. B01 remains `REJECT_FOR_PROMOTION`.

## Frozen registration and request preparation

Register the runner with `selector: RECORDED_MODEL_RESPONSES` and a `selector_profile`
containing the exact model identity, prompt reference hash and maximum response latency
(default 1500 ms, hard maximum 2000 ms). Scripted mode must not have this profile;
recorded mode must have it. The registered artifacts include these values, and code
drift still invalidates reconstruction. A prompt reference hash is not proof of the
actual prompt or provider configuration used outside this process.

`Runner.prepare_selector(tick, registration_hash)` reads and reconstructs the existing
journal, computes the next B01 candidates and returns two requests. It does **not**
append a tick, reserve a paid model call, alter the simulator's persisted state or
create any execution authority. It rejects stopped, expired, over-capacity, wrong
sequence or already-selected inputs. It evaluates only bars available by request time.

Each request hash binds the frozen profile, input hash, arm, candidate and candidate
UUID, allowed exit and request cutoff. AI_NO_NEWS receives candidate data without news
content; AI_NEWS also receives the bounded news classification. The opaque input hash
binds the whole observation but does not reveal its raw news content. Neither request
includes raw provider prose, account credentials or arbitrary tools.

```powershell
python -m fx_talanta.evaluation.runner prepare-selector --journal .local/runner.sqlite --registration-hash $registrationHash --input next-tick.json
```

For this simulation path a fixture supplies a `model_batch` on the Tick: the shared
`requested_at` and exactly one reply for each AI arm. `Batch`, `Reply` and `Profile` in
`fx_talanta.evaluation.selectors` define the strict JSON contracts. The normal queue
`enqueue`/`drain-one` path then records and admits that Tick. A normalized source Tick
may carry this batch; use `normalize` before preparing requests. `enqueue-envelope`
remains the scripted-input convenience path and does not fabricate recorded replies.

## One decision and its failure behavior

The runner reconstructs each request from its own frozen profile, input and candidate.
Claimed request times must follow previous committed state and all admitted input
availability, and precede actual admission. Future completions reject admission rather
than allowing future information. At final admission it reconciles current simulated
state and rechecks the candidate; a changed request hash becomes a HOLD.

Replies with timeout/error status, wrong request/model identity, excessive latency,
malformed/extra JSON fields, another candidate or an unsupported exit become recorded
HOLDs. The reused M4 `Selection` contract permits only a supplied candidate and TIME_EXIT,
or HOLD. It cannot set size, account, stop, policy or execution authority. Scripted
selection overrides are forbidden in recorded mode.

Shared calendar/news safety, position/entry limits and deterministic risk still apply
after model selection. The existing adverse/unavailable-news guard remains in AI_NEWS.
The NO_AI arm uses the same request cutoff for candidate comparison and actual admission
time for safety; it does not invoke a model. All three decision receipts are constructed
before simulated submission. The original **two-second quote ceiling** remains intact:
a timely reply does not rejuvenate an older quote, and model delay can remove entry
eligibility even when the reply schema is valid.

The original bounded response and metadata remain in the Tick. Decision content records
the independently rebuilt request hash, response-record hash, parsed selection, failure
reason and reported usage. Same-ID/content replay returns the existing receipt; changing
the reply or cost under the same ID fails. Restart reconstructs stored transitions and
never reissues a model request. Preparation itself is not a durable paid-call reservation;
a future real transport must implement that separate uncertain-call/budget boundary.

## Timing and cost interpretation

Decision latency is derived from recorded completion minus request time, separately for
each AI arm. These are **reported timestamps**, not measured or independently verified
provider latency. The dashboard shows recorded reply count, rejected/HOLD count, token
counts, maximum reported latency, known reported USD cost and unknown-cost reply count.
Unknown cost remains unknown; no timeout or malformed reply implies a free call/refund.

Model cost is reported separately from existing simulated trade P&L and broker costs.
Derived receipt exports retain the model trace in decision content but do not claim a
net economic verdict including model charges. Economic review must reconcile these costs
and unknowns before comparing profitability. Values in synthetic fixtures are invented
test accounting, not API pricing, invoices, model performance or prospective evidence.
All external-call verification flags remain false.

## Acceptance and remaining boundary

```powershell
$env:PYTHONPATH = "src;."
python -m tools.qualification.runner_selector_acceptance --output .local/selector-new
python -m tools.qualification.m5_acceptance --output .local/selector-checks-new.json
```

The exercise normalizes six inputs, prepares requests without journal writes, supplies
12 fixture replies, reopens the consumer, checks retries, settles one simulated position
per arm and stops. Tests cover malformed/unsupported replies, timeout, identity/hash
mismatch, latency bounds, future responses, unknown costs, changed replay content,
news-content ablation and stale-quote rejection. Headless browser tests inspect the
actual resulting runner and its model-accounting labels.

This closes recorded-response simulation integration, not production model integration.
Still required are authenticated real provider/source transports, durable paid-call
reservation and uncertainty handling in this runner, independently qualified input and
model/cost evidence, eligible candidates, connected operations/deployment acceptance,
and the specification's eight weeks **AND** 100 closed PAPER trades. M1–M3 gaps and
historic failures remain preserved. Full M5 is open; trading remains disabled.

The [source-hashed acceptance report](../evidence/m5-recorded-selector-checks-20261106.json)
records 234 backend checks and 11 headless browser scenarios passed, with zero skips
or flaky results. The [six-input synthetic report](../evidence/m5-recorded-selector-synthetic-20261106.json)
records 12 fixture model replies and one simulated close per arm. Both reports match
the final tested code; external model and broker call counts are zero.
