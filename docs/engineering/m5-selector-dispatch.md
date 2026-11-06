# Durable simulation selector dispatch

`fx_talanta.evaluation.dispatch.Dispatcher` connects the
[recorded selector](m5-recorded-selectors.md) to a caller-supplied transport and the
existing source queue. This change tests only an in-process fixture transport. No
provider SDK, HTTP transport, endpoint, credential, paid call or broker connection is
configured, and no CLI starts dispatch. Trading remains disabled.

## Frozen authority and accounting

Create one dispatcher for an empty, current queue bound to a recorded-selector runner.
`Policy` pins the absolute queue path, source binding hash, deadline, lifetime maximum
calls, tokens reserved per call and cumulative reserved-token allowance. Its returned
hash is mandatory on every operation. It cannot extend the runner deadline or change
the existing two-second entry rule, candidate, model profile, account or risk policy.

These are call/token planning allowances, **not a provider billing guarantee**. The
transport receives the frozen token/deadline limits and must enforce its own bounded
request, output and timeout behavior. This synchronous layer cannot cancel an arbitrary
injected function that hangs or ignores those limits. A production adapter still needs
that implementation and acceptance. Dollar values in results are reported accounting,
not trading-risk limits or permission to spend.

Before either AI arm is invoked, one append-only reservation commits both call slots
and both token allowances. Actual token usage, HOLDs, timeout, error, stop and restart
never refund that reservation. A crash can leave a reserved call that never started;
the report deliberately does not identify reserved counts as verified provider calls.
One unresolved observation blocks subsequent dispatch. A persistent source-side binding marker pins one dispatcher path and policy hash.
Creating a second dispatcher for that source, or copying the journal to another path,
cannot reset its allowance. Do not attach unrelated producers to the queue.

## Lifecycle and failure behavior

1. Validate the exact source, mode/channel, drained queue, next sequence, current
   deadline and runner mandate before reserving. A stopped or mismatched source cannot
   consume call allowance. Prepare the two candidate-bound requests without runner writes.
2. Commit the paired reservation and exact input/request content. A nonblocking process
   lock prevents concurrent dispatch/stop; lock contention fails instead of creating a
   second caller. Do not bypass the class's internal journal methods.
3. Invoke the injected transport once per arm and persist each bounded `Delivery` as a
   reply. The dispatcher stamps completion with its clock and pins the prepared request
   hash. Original response, model identity, usage and reported cost remain available for
   the existing selector validator. Both arms retain the same request cutoff; sequential
   transport time consumes that window and can invalidate entry freshness.
4. A thrown exception, malformed delivery or process death after reservation leaves
   uncertainty. Retry of the same input returns `OUTCOME_UNKNOWN_NO_RESEND`; later input
   is blocked. No request is blindly repeated, missing response invented, or budget reset.
   Only the exception type is retained, not potentially secret exception text.
5. A reported token overrun is retained as a result, then blocks remaining dispatch and
   publication. If the deadline expires between arms, the remaining arm is not invoked.
   An already-started synchronous callback may finish after the deadline; its result is
   retained, but new dispatch/publication is forbidden.
6. Once both replies are durable, publish the exact selected Tick to the source queue.
   If publication or its checkpoint is interrupted, retry reuses stored replies and the
   queue's same-ID receipt without invoking transport. Draining remains a separate
   operation under the runner's unchanged risk and freshness checks.

A transport-returned TIMEOUT/ERROR is a durable reply, producing a recorded HOLD in the
selector, with unknown cost retained when absent. A thrown exception is different: the
dispatcher cannot attest what completed and leaves the observation unresolved. There is
no provider receipt lookup or reconciliation mechanism in this slice, so unresolved
dispatch does not silently become usable. Stop irreversibly blocks dispatch/publication
and preserves reservations and unknowns; it does not close simulated positions or stop
the source automatically. Stop the source/runner explicitly when finishing the exercise.

## Application and inspection interfaces

```python
dispatcher, dispatch_hash = Dispatcher.create(path, policy, clock)
result = dispatcher.dispatch(unselected_tick, dispatch_hash, fixture_transport)
# Once PUBLISHED, the existing Operations.drain_one admits the queued Tick.
report = dispatcher.report(dispatch_hash)
dispatcher.stop(dispatch_hash)
```

`Delivery` defines the strict bounded transport return. The transport is trusted injected
application code, not a sandbox or an authentication boundary. The implementation has no
default real transport. Tests prohibit network access. Do not supply a real provider
function under this simulation-only authorization.

The existing dashboard study configuration accepts:

```json
{"source_kind":"DISPATCH","journal":"/absolute/path/dispatcher.sqlite","plan_hash":"<dispatcher binding SHA-256>"}
```

It combines runner/queue inspection with reserved calls/tokens, completed replies,
unresolved reserved calls, known reported cost and unknown-cost calls. OPEN is not proof
of a live transport; status becomes UNRESOLVED when journal evidence cannot establish a
completed pair. Persistent dispatcher and source/runner checkpoints reject rollback;
published source bytes must match the retained dispatch results. Missing or inconsistent
evidence clears the view. The UI has no send, refund, retry, stop or execution controls.

Preserve all **three** journals, the source-side `.dispatch-binding.json` marker and
the binding/checkpoint evidence. Interrupted initialization may leave the marker with
an incomplete dispatcher; preserve it for diagnosis rather than deleting it to reset
the allowance. There is no automatic initialization retry/reset or relocation path. The earlier paired
source/runner archive remains valid for inspecting those two files, but it does not back
up or restore dispatch reservations and is not a dispatch restart artifact. No automatic
dispatcher restore or budget migration is provided here. Local hashes detect changes
relative to trusted checkpoints, not an attacker replacing all evidence and hashes.

## Reproducible acceptance and remaining gates

```powershell
$env:PYTHONPATH = "src;."
python -m tools.qualification.runner_selector_acceptance --dispatch --output .local/dispatch-new
python -m tools.qualification.m5_acceptance --output .local/dispatch-checks-new.json
```

The exercise runs six normalized synthetic observations through 12 fixture calls,
durable reservation/results, queue publication, restart, simulated execution and dashboard
inspection. It consumes the full predeclared call/token allowance and closes one simulated
position per arm. Fault tests cover crashes before/after one response, lost publication
checkpoints, overrun, expiry, concurrent callers, source mismatch/stop, cumulative budgets
and dashboard rollback detection. No external model or broker is called.

Still open: authenticated real transport and enforced provider timeout/token behavior,
independent usage/billing and unknown-call reconciliation, qualified source/model inputs,
eligible candidates/costs, connected operations and actual deployment acceptance. Existing
M1–M3 failures and B01 `REJECT_FOR_PROMOTION` remain preserved. This is not the required
eight weeks **AND** 100 closed PAPER trades; full M5 remains open.

The [source-hashed acceptance report](../evidence/m5-selector-dispatch-checks-20261106.json)
records 248 backend checks and 11 headless browser scenarios passed, with zero skips
or flaky results. The [synthetic dispatch report](../evidence/m5-selector-dispatch-synthetic-20261106.json)
records 12 fixture transport calls, 12 permanent call reservations, 2400 reserved
tokens and no unresolved calls at stop. Both reports match the final tested code.
