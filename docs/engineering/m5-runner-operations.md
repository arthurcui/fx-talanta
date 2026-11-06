# Simulation runner operating integration

The bound local queue in `fx_talanta.evaluation.operations` connects an incremental
input producer to the [PAPER runner](m5-paper-runner.md), with durable acknowledgements
and a direct read-only dashboard projection. This is simulation engineering, not a
prospective campaign or qualified source adapter. Trading remains disabled; the
original two-second risk ceiling and B01 `REJECT_FOR_PROMOTION` verdict are unchanged.

## Authority and recovery

`Binding` pins a source UUID, absolute runner journal path, registration hash and
capacity. It may bind only an empty, current runner. Capacity cannot exceed the
runner mandate (hard ceiling 250 observations). The returned binding hash must be
supplied on every operation. A UUID/hash identifies local data; it does not authenticate
a provider or establish external provenance. Keep the queue and runner on a trusted
local filesystem with their saved checkpoints.

Each queued `Tick` retains its original timestamps, sequence, UUID and exact content.
Inputs form an immutable hash chain. A same-ID/content enqueue is idempotent; changed
content, future data, out-of-order sequence or exhausted capacity fails. The producer
must supply qualified, correctly normalized inputs before any future operating
acceptance; this implementation provides no network collector, credentials or model.

`drain-one` serializes consumers and admits only the oldest pending input. It first
checks every existing runner input against the source, plus acknowledged runner hashes.
The runner commits all three simulated arms before the queue commits its acknowledgement.
A crash between those commits leaves one exact unacknowledged transition: retrying the
same item returns the original runner receipt and completes its acknowledgement.
A divergent write or rolled-back acknowledged runner fails closed. Do not write directly
to a bound runner or bind multiple producers independently to it. Inputs that fail
admission remain pending; there is no automatic skip, repair, budget reset or retiming.
Stale quotes retain their age and cannot acquire entry authority from queue receipt time.

`stop` seals the source before stopping the runner. If interrupted, retry with the same
reason; it cannot reopen the source. Pending inputs and open simulated positions remain
evidence, not fabricated closes. If stop intervenes after an unacknowledged commit, that
pending/committed distinction remains visible. Back up both databases consistently with
producers and consumers stopped. Local hash chains do not defend against replacement of
all evidence and checkpoints by an attacker.

## Interfaces

The strict `Binding` and `Tick` models define input JSON. Commands have no endpoint,
broker credential or execution-enable option:

```powershell
python -m fx_talanta.evaluation.operations create --queue .local/source.sqlite --input binding.json
python -m fx_talanta.evaluation.operations enqueue --queue .local/source.sqlite --binding-hash $hash --input tick.json
python -m fx_talanta.evaluation.operations drain-one --queue .local/source.sqlite --binding-hash $hash
python -m fx_talanta.evaluation.operations report --queue .local/source.sqlite --binding-hash $hash
python -m fx_talanta.evaluation.operations stop --queue .local/source.sqlite --binding-hash $hash --reason "input ended"
```

These describe the interface, not campaign activation. The report distinguishes queued,
acknowledged, pending and committed-but-unacknowledged inputs. Source OPEN does not mean
runner readiness: inspect the nested runner status, deadline, capacity and arm decisions.

The dashboard's existing `--study-journal-config` also accepts:

```json
{"source_kind":"RUNNER","journal":"/absolute/path/runner.sqlite","plan_hash":"<registration SHA-256>"}
```

For this source kind, `plan_hash` is the runner registration hash. The view has no write,
drain or stop endpoint. It shows receipt age separately from quote latency, explicit
scripted-selector identity and simulated positions. Durable dashboard checkpoints reject
rollback, including removal of a previously observed stop; unavailable/corrupt sources
clear old details. Legacy receipt-view configuration remains compatible. The queue report
is a separate CLI view; the dashboard does not claim to monitor producer liveness.

## Acceptance and remaining boundary

Run the bounded synthetic exercise in a new output directory:

```powershell
$env:PYTHONPATH = "src;."
python -m tools.qualification.runner_operations_acceptance --output .local/runner-operations-new
python -m tools.qualification.m5_acceptance --output .local/runner-operations-checks-new.json
```

The exercise enqueues six inputs, reopens the consumer between inputs, verifies idempotent
enqueue, closes one simulated position per arm and seals/stops the journals. Fault tests
cover lost acknowledgements, interrupted stop, rollback, source/target divergence, stale
inputs and dashboard invalidation. A headless browser reads the actual generated runner.
No real broker, provider or external model is called. Source-hashed reports are retained
in the [198-check / 11-browser report](../evidence/m5-runner-operations-checks-20261106.json)
and [six-input synthetic report](../evidence/m5-runner-operations-synthetic-20261106.json).
All checks passed, with zero skipped or flaky browser scenarios; all source hashes
were verified against the tested local bytes.

Still open: qualified source/model adapters and provenance, broker reconciliation and
fault/administrative acceptance, deployment and real receiver delivery, eligible strategy
and cost qualification, and the specification's eight weeks **AND** 100 closed PAPER
trades. These bounded synthetic closes do not count toward that gate. Existing M1–M3
failures and gaps remain preserved; full M5 is not complete.

## Queue inspection and paired recovery

The [recovery guide](m5-runner-recovery.md) adds queue-aware dashboard binding,
persisted source/acknowledgement checkpoints and stopped paired archive verification.
Restored evidence is inspection-only; no producer, model or trading is activated.
