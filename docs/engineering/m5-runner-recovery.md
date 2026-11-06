# Simulation source inspection and portable recovery evidence

The local simulation runner now supports queue-aware dashboard inspection and a
verified archive of its paired source and runner journals. This closes the paired
backup and source-queue visibility gaps left by the [operating integration](m5-runner-operations.md).
It does not start a collector, model, broker connection or prospective campaign.

## Queue-aware dashboard

Use the existing `--study-journal-config` option with:

```json
{"source_kind":"OPERATIONS","journal":"/absolute/path/source.sqlite","plan_hash":"<source binding SHA-256>"}
```

Here `plan_hash` identifies the **source binding**, rather than a runner registration.
The persisted configuration cannot be rebound on dashboard resume. Existing RECEIPTS
and RUNNER configurations retain their prior meaning and serialization.

Inspection shows queued, acknowledged and pending inputs, the oldest pending receipt
age and whether the runner committed an input whose acknowledgement is still absent.
These are factual observations, not a liveness or freshness guarantee. Producer liveness
is explicitly UNVERIFIED; an empty queue does not certify a healthy collector. Pending
age is not quote latency. The original two-second entry restriction remains intact.

The dashboard atomically saves source-prefix, acknowledgement-prefix, seal and runner
checkpoints. Removal of a previously observed enqueue, acknowledgement or stop fails
inspection, even if the runner alone still looks valid. Missing or invalid evidence
clears old details. Concurrent collection can yield a transient unavailable view;
inspection never repairs, skips or acknowledges inputs and cannot grant authority.

## Stopped paired archive

`fx_talanta.evaluation.archive` exposes three explicit operations:

```powershell
# Source hash is the pinned binding hash returned when the queue was created.
python -m fx_talanta.evaluation.archive capture --source .local/source.sqlite --hash $bindingHash --destination .local/archive-new
# Keep the returned manifest hash separately from the archive.
python -m fx_talanta.evaluation.archive verify --source .local/archive-new --hash $manifestHash
python -m fx_talanta.evaluation.archive restore --source .local/archive-new --hash $manifestHash --destination .local/inspection-new
```

Capture refuses an open source or unstopped runner, including a source sealed during
an interrupted stop. It holds the consumer lock, uses SQLite backup for both journals,
pins their hashes, the package engine hash, source binding and a fixed inspection time,
then reconstructs the copied evidence before returning success. The command never stops
a source on the owner's behalf. Finish its explicit stop first and keep producers stopped.

Verification checks the separately pinned manifest hash, bounded fixed filenames, exact
file bytes, absent SQLite sidecars and matching engine version. It reconstructs the full
runner history against queued inputs and acknowledgements. The saved and reconstructed
reports must agree, and both sealed/stopped states must remain present. Original paths
inside the immutable source binding are retained; inspection uses only the archived
runner, so the original location may be unavailable. No journal binding is rewritten.

Restore creates a **new inspection directory**, never overwrites an existing destination,
and verifies the copied files again. It does not resume processing, restore execution
authority, change limits or extend a deadline. Results explicitly say inspection-only
and not current readiness. Pending inputs, committed-but-unacknowledged transitions,
open simulated positions and unknown outcomes remain unresolved evidence. No synthetic
closure is invented. Inspect a restored bundle through `archive verify`; it is not a
replacement for the bound operating queue or a running dashboard's source.

Archives contain private raw inputs and the original local path; store them privately.
Only sanitized synthetic reports belong in Git. Hashes detect substitution relative to
a trusted saved hash; they are not signatures or encrypted storage. Replacing an archive
and its trusted hash defeats that protection. Engine drift fails verification: retain
the matching code/environment for historical inspection. Failed capture/restore may leave
an incomplete new directory; preserve it for diagnosis and choose a fresh destination.

## Reproducible acceptance

```powershell
$env:PYTHONPATH = "src;."
python -m tools.qualification.runner_recovery_acceptance --output .local/recovery-new
python -m tools.qualification.m5_acceptance --output .local/recovery-checks-new.json
```

The exercise runs six synthetic inputs, stops the journals, captures and restores the
pair, then independently reconstructs the restored report. Fault tests exercise missing
original paths, wrong manifest/file bytes, unexpected sidecars, interrupted stop,
unacknowledged commits, rollback and persisted dashboard checkpoints. The headless
browser verifies queue counts, explicit unverified liveness and clearing unavailable data.

This is engineering evidence only. B01 remains `REJECT_FOR_PROMOTION`; M1–M3 gaps,
qualified source/model integration, connected reconciliation/fault/administrative
acceptance, real deployment/delivery and the eight-week **AND** 100-closed-PAPER-trade
requirements remain open. Full M5 is not complete, and no new campaign is authorized.

The [source-hashed acceptance report](../evidence/m5-runner-recovery-checks-20261106.json)
records 208 backend checks and 11 headless browser scenarios passed, with zero skips
or flaky results. The [synthetic recovery report](../evidence/m5-runner-recovery-synthetic-20261106.json)
records six acknowledged inputs and verified inspection restoration. Source hashes
were checked against the tested local bytes; no broker or external model was called.
