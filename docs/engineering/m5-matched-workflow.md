# Matched-study receipt workflow

## Scope and authority

`fx_talanta.evaluation.ledger` records an explicitly registered offline study as
observations, decisions and outcomes arrive. It closes the gap between uploading a
finished comparison and retaining its chronological inputs. It does **not** run a
strategy, invoke a model, connect to a broker, start a campaign, or authorize PAPER
or LIVE trading. Both supported provenance labels (`SYNTHETIC`, `RECORDED_OFFLINE`)
remain offline. Local receipt order is not independently verified prospective delivery.

The dashboard is a read-only consumer of this journal. CLI writes require an exact
plan hash and a stable caller-owned event UUID; there is no HTTP registration,
receipt-write, campaign-start or broker-order route. The existing two-second entry
rule, M1-M3 gaps and B01 `REJECT_FOR_PROMOTION` verdict are unchanged.

## Frozen inputs

A `matched-receipt-plan/1` extends the existing matched-study definition with a
`run_id` and `max_snapshots` (1..1000, default 250). `samples` must be empty. The
three separate arm ledgers, shared safety hash, baseline without AI/news, and
shared AI policy/model/prompt are validated by the existing study contract.
Registration supplies an exact `artifacts` mapping from SHA-256 to UTF-8 content for
every referenced candidate/dataset-manifest/criteria/features/lessons/news/policy/
safety/model/prompt hash. Hashes are checked against bytes; arbitrary unsupported
hash strings alone no longer establish a registered workflow. Content is evidence,
never executable code. A model artifact can be a frozen model configuration, not
proprietary model weights. Dataset manifests describe the planned inputs; snapshots
are recorded separately as received.

The artifacts are bounded to 1 MiB in total. Hashes establish byte identity, not
strategy eligibility, model quality, news completeness or correctness of costs.
Registration is durably timestamped by the injected/system clock. Its deadline,
artifacts and policy cannot be changed on resume. Observations must be at or after
registration, so an old manifest timestamp cannot manufacture elapsed observation.

## Receipt lifecycle

| Receipt | Required checks | Failure behavior |
| --- | --- | --- |
| REGISTER | New file, valid frozen plan/artifact bytes, registration before deadline | Refuses overwrite; a failed partial creation is retained for inspection |
| OBSERVE | New content hash, original timestamp between registration and receipt, capacity available | Rejects duplicate/future/backdated input; no invented snapshot |
| DECIDE | Existing snapshot, one decision per arm, unique decision ID, decision content/hash, no outcome fields; decision timestamp at/after observation receipt | Rejects missing observation, conflicting identity and look-ahead |
| OUTCOME | All three decisions already durable; actual claimed outcome time strictly after all decision receipts and no later than its receipt | Rejects incomplete groups, backdated/future outcomes; unknown costs remain unknown |
| OUTCOME correction | Explicit `supersedes` points to the current outcome event; nondecreasing outcome time | Preserves original rows, rejects correction forks; newest valid revision is projected |
| CLOSE | Nonempty reason, nondecreasing clock | Irrevocably closes new writes; exact retries remain readable |

Each write validates the entire bounded chain inside a SQLite `BEGIN IMMEDIATE`
transaction. Concurrent retries of the same event ID/content return the same
receipt; changed content with that ID fails. A new ID never bypasses an already
recorded arm decision. Connection/process loss leaves either a committed receipt
or no receipt; retry the same ID rather than creating a replacement. SQL triggers
reject normal updates/deletes. Registration and all receipt hashes are revalidated
on resume; prior receipt hashes link every row. There is no deadline extension,
budget reset, automatic resend or automatic recovery write.

Hard limits are 12,000 receipts plus a final close and 32 MiB of journal payload.
Capacity exhaustion fails before changing the journal; if payload space is fully
used even close can be refused. Expired windows reject new data but can be closed.
A report marks an unclosed expired window `WINDOW_EXPIRED`, not completed or passed.

## Operator interface

All JSON inputs use UTC-aware timestamps. Receipt files follow the Pydantic models
in `evaluation/ledger.py`: `Registration`, `Observation`, `Decision`, `Outcome` and
`Stop`. The CLI reads at most 2 MiB per input. Supply a new isolated journal path
whose parent exists; do not reuse campaign databases or dashboard inspection files.

```powershell
python -m fx_talanta.evaluation.ledger register --journal .local/study-receipts.sqlite --input .local/registration.json --event-id $registrationId
# Save the printed plan hash. Keep each event UUID stable when retrying.
python -m fx_talanta.evaluation.ledger observe --journal .local/study-receipts.sqlite --plan-hash $planHash --input .local/observation.json --event-id $observationId
python -m fx_talanta.evaluation.ledger decide --journal .local/study-receipts.sqlite --plan-hash $planHash --input .local/decision.json --event-id $decisionReceiptId
python -m fx_talanta.evaluation.ledger outcome --journal .local/study-receipts.sqlite --plan-hash $planHash --input .local/outcome.json --event-id $outcomeReceiptId
python -m fx_talanta.evaluation.ledger close --journal .local/study-receipts.sqlite --plan-hash $planHash --input .local/stop.json --event-id $closeReceiptId
python -m fx_talanta.evaluation.ledger report --journal .local/study-receipts.sqlite --plan-hash $planHash --output .local/receipt-report.json
python -m fx_talanta.evaluation.ledger export --journal .local/study-receipts.sqlite --plan-hash $planHash --output .local/matched-study.json
```

These commands document the interface; this change does not provision a study or
start a collection campaign. Reports/exports refuse existing destinations. Export
produces the existing `matched-offline-study/1`, suitable for dashboard study upload.
Export does not include full content or receipt-chain proof; retain the original
journal and report as well. With no decisions, report works and export is refused.

Reports show observations without any decisions, missing arm decisions, pending
outcomes, corrections and the receipt head. Existing paired comparisons cover
snapshots represented by at least one decision; observations without decisions are
reported separately and must not disappear from a future qualification denominator.
Unknown costs/outcomes are excluded rather than imputed as zero. Supplied
`latency_ms` is metadata, not independently measured execution latency. No closed
broker-trade count or economic acceptance is inferred.

## Dashboard and recovery

Create an explicit private binding JSON containing `journal` (absolute path) and
`plan_hash`, then launch an isolated dashboard with
`--study-journal-config .local/study-view.json`. Existing viewer/owner authentication
applies. The registered-receipt panel shows status and counts; it never sends raw
artifact/snapshot/decision contents or local paths to the browser. A missing,
corrupt, wrong-plan, future-receipt or rolled-back journal displays `UNAVAILABLE`
and clears previously displayed details.

The dashboard durably saves the latest accepted sequence/hash in its own inspection
journal. On resume, the source must still contain that exact prefix; changing or
removing the source binding requires a different inspection workspace. Normal
append and recovery of the same source can resume the view. The source is opened
with SQLite `mode=ro` and never created by dashboard reads.

The external study journal is **not** included in the dashboard's inspection-only
backup. Retain it separately using a consistent SQLite backup while its writer is
stopped, along with exported reports/checkpoints. Restoring a dashboard copy does
not copy study contents or grant execution authority. Hash chaining is not a signed
attestation: an attacker who controls both journal and all checkpoints can rewrite
evidence. External timestamps, custody, provenance and operational qualification
remain separate gates.

## Acceptance and remaining scope

Synthetic tests exercise chronological registration, frozen bytes, missing arms,
late outcomes, same-ID concurrency/restart, corrections, deadline/capacity limits,
clock rollback, corruption, immutable rows, export and dashboard prefix rollback.
Headless browser acceptance checks pending outcomes, failure clearing and recovery.
No broker, live model, public endpoint, host-clock change or visible application is
used. The consolidated source-hashed M5 report records the actual test results.

This completes the **offline receipt-workflow engineering slice**. A prospective
strategy/model runner with actual receipt provenance, qualified candidate/inputs/
costs, predeclared uncertainty/economic review, broker operating acceptance and
actual deployment remain outstanding. Full M5 still requires the original eight
weeks AND 100 closed PAPER trades per candidate after its prerequisites; M6 stays blocked.

[Local acceptance evidence](../evidence/m5-matched-workflow-20261106.json):
**135 backend checks and nine headless browser scenarios passed**, zero skipped/flaky.
The report pins source hashes and explicitly records zero broker/model calls, trading
disabled and full M5 incomplete. Earlier acceptance reports remain unchanged.

## Incremental producer

The [simulation runner](m5-paper-runner.md) now produces these receipts from an
actual incremental strategy/risk/simulator loop. Export is derived from its original
atomic transition journal and remains offline-only. This adds an engineering
producer; the prospective qualification gaps above still apply.
