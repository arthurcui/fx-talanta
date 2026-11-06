# M4 offline command gateway integration

`advisor.command_gateway` connects the bilingual evaluator to the existing
`gateway.offline.Gateway` and `brokers.simulator.Simulator`. Exact concrete types,
PAPER/SIMULATOR identity, database binding and writer ownership are checked. There
is no terminal SDK, EA dispatch, model call, HTTP endpoint or deployment path.
The scope comes from a trusted harness, not authenticated user input.

## State and authority

`command_snapshot` derives account state from the gateway and simulator books under
the gateway's existing reentrant lock. Its version is an opaque SHA-256 integer
token over both books, not a monotonic revision number. Entry, management and command
processing use that same lock. A changed book invalidates a pending command's
expected version. The adapter never accepts caller-supplied position ownership,
halt state, confirmation flags or simulated after-state.

Only tracked, owned positions are close targets. External positions cannot be
closed through this adapter and block resume. Market/news restrictions are evaluated
through the gateway's configured journal gate. Synthetic fixture health flags are
not real provider qualification. Original quote age remains limited to two seconds;
existing management freshness and position-version checks still apply.

## Durable lifecycle

1. Validate scope, target, exact language grammar, expiry and state token. Rejected
   requests are retained without a simulator mutation.
2. Atomically save the request marker and any administrative entry pause/halt in
   the existing gateway journal. Pause and flatten restrictions are committed
   before management. Resume clears only administrative pause after all gates pass;
   it does not enable real trading or clear loss/integrity halts.
3. Route deterministic cancel/close request IDs through `Gateway.manage`, which
   journals SUBMITTING before its simulator mutation. Cancel known unfilled
   remainders first. Then close only actual remaining owned volume with the exact
   simulator position version. No new entry or reversal action is available.
4. Stop on rejection, uncertainty or expiry; never continue with another close after
   an uncertain cancellation. Check request and scope deadlines before each action.
   A previously unresolved execution or hidden history causes no new mutation.
5. Save the result only after the simulator reports its outcome. Completed closure
   also checks that targeted positions and pending remainders are gone. The receipt
   links the original message and lists the management operation IDs; those identify
   the corresponding execution evidence in the same gateway run.

These are READ_ONLY, unauthenticated conversation receipts labeled simulation-only
and execution-disabled, not real broker command authorization. COMPLETED means an
offline simulator operation completed; flatten covers owned/tracked exposure only.

A repeated request returns the original receipt, including unknown outcomes, even
if later reconciliation finds more evidence. Changed content under that request ID
conflicts. If a process fails after reserving a request but before saving the final
receipt, restart returns INTERRUPTED_NO_RESEND. It never guesses whether the action
ran or repeats it. Ordinary gateway reconciliation remains available to inspect and
manage outstanding simulated risk independently. Historical command receipts are
not silently rewritten as current account state.

A journal error fences the writer by closing its store. Failure before reservation
commit makes no simulator call. Failure after mutation retains the earlier marker
and management journal for recovery. The existing PostgreSQL session lock excludes
a second gateway writer; within one process, the gateway lock serializes commands
with entries and management. A pause preceding an entry blocks it; an entry that
changes state first makes an old command token stale.

## Verification and remaining work

```text
python -m pytest tests/test_advisor_command_gateway.py tests/test_advisor_commands.py
python -m pytest tests/test_advisor_command_gateway.py --integration
```

Tests use synthetic market data, the existing offline simulator and CI PostgreSQL.
They cover bilingual pause/resume/close, full/partial/pending-entry flatten, stale
state and quotes, negation, failed reservation writes, deadline exhaustion after
cancellation, lost replies, concurrent delivery, durable restart and a failed final
receipt after an actual simulated close. No paid API call or broker operation is
required. Existing broker/provider evidence and B01 remain unchanged.

This completes the offline gateway wiring for the supported command grammar.
Production authentication, unrestricted conversational interpretation, strategy
proposals and broader M4 evaluation remain open. Connected administrative controls
belong to later qualified milestones; this integration does not enable them.
