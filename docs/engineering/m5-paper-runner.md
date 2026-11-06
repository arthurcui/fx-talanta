# Incremental PAPER runner: simulation acceptance

The runner in `fx_talanta.evaluation.runner` implements the incremental decision,
risk, execution and outcome loop needed for prospective PAPER operation. **This
version runs only local simulation.** It has no broker adapter, credential input,
model transport, background collector or campaign activation path. Constructing a
runner does not enable trading. Neither this document nor its test results authorize
a new campaign.

The available strategy is the existing B01 research kernel. B01 remains
`REJECT_FOR_PROMOTION`; executing it in simulation does not promote it. The two AI
arms use an explicitly named `SCRIPTED_TEST_DOUBLE`, not a production model.
Qualified live input and model adapters are still needed before prospective
operating acceptance. Simulation receipt order is not verified external provenance.

## One observation through the system

| Stage | Component and authority | Durable evidence and failure behavior |
| --- | --- | --- |
| Registration | Runner freezes symbol/specification, risk/cost terms, limits, deadline, selector and package source hash | Immutable header and caller-pinned registration hash; no rebind or automatic code upgrade |
| Observation | Caller supplies the next `Tick`; runner records its own receipt/decision cutoff | Exact input JSON and stable UUID/sequence; future bars, nonadvancing markets, gaps and changed specifications reject admission |
| Strategy | Existing B01 kernel sees only completed bars available by cutoff | Candidate/hold rationale and visible-input hash; incomplete history remains HOLD; a quote must follow signal availability |
| Selection | NO_AI uses the candidate directly; two scripted selectors use the M4 strict `Selection` contract | All three decision receipts share the observation; only AI_NEWS receives the news field; HOLD/timeout/malformed scenarios cannot invent an intent |
| Risk | Existing deterministic governor and gateway own sizing, reservations, portfolio limits and freshness | Original risk records, checked limits and reasons; shared safety applies to all arms; rejected attempts consume the signal/entry-count allowance |
| Execution | Existing `Gateway.for_replay` plus costed simulator; no EA or real broker | Separate account/book per arm, original reservation/order/protection/reconciliation journal; uncertain outcomes reconcile without a new entry |
| Outcomes | A later admitted observation reconciles earlier decisions | Commission and financing explicit; spread/slippage embedded in simulated fills; no ending-data liquidation or guessed outcome |
| Explanation/learning | Decision, risk, execution and experience records retain causal references | Original immutable transition journal; export supplies dashboard comparisons; no automatic promotion, new learned policy or execution authority |

Every tick commits its input and all three arm transitions in one SQLite
transaction. All matched decisions are constructed before local simulator entry.
The simulator is an in-memory, deterministic calculation: it has no external side
effect to resend. A precommit exception leaves no accepted tick; after a committed
but lost response, retrying the **same UUID and identical content** returns the
existing receipt. Changing content under that UUID fails. Concurrent writers
serialize with `BEGIN IMMEDIATE`.

Restart reconstructs the frozen engine from committed inputs and compares each
computed transition with the saved result and chained hash. Original risk/loss
state, consumed signals, budgets and open simulated positions survive this process.
Code drift, corruption and a mismatched registration fail closed. A saved sequence/
hash checkpoint can detect rollback on report. Hash chaining is local integrity,
not a signature or protection against an attacker controlling the journal and all
checkpoints. Back up the runner journal consistently while its writer is stopped.

## Limits and time semantics

The original quote/conversion timestamps reach the unchanged risk governor. Its
ceiling remains at most **two seconds**; receipt time never replaces quote time.
The runner captures admission time after reconstruction, and aborts a newly
submitted simulated transition if processing crosses that ceiling before commit.
Clock rollback or a deadline crossed during processing also aborts admission.
This is a simulation safety check, not independent broker clock qualification.

Instrument specifications and explicit commission/slippage/financing assumptions
are frozen. They are test assumptions, not calibrated broker execution costs.
Each arm retains its own capital, equity, percentage-risk limits and one-position
limit. The maximum entry-attempt count includes rejected submissions and is never
refunded. News ablation affects selector content only: common calendar/news/session
safety flags remain mandatory for every arm.

The default bound is 100 observations and ten entry attempts per arm; hard maxima
are 250 observations, 100 attempts per arm, 20,000 accumulated bars and 64 MiB of
input/transition content. Each observation must fit the existing 64 KiB receipt
contract. Supply bar deltas rather than repeating the entire history. Full history
reconstruction favors auditability over throughput; this implementation is not a
high-frequency or eight-week production collector.

`stop` irreversibly closes admission, preserving open simulated positions and
unknown outcomes. It does not invent a closing quote or trade. No final outcome
is synthesized for decisions on the last tick. Outcome timestamps in the derived
comparison mean **later reconciliation availability**; original simulated deal
timestamps remain in the runner journal. A known HOLD/rejection has zero trading
P&L and cost when reconciled, whereas an unresolved entry stays pending. Scripted
selector latency is zero by construction, not measured model latency. There are
no real model charges or claimed broker closed trades.

## CLI and reproducible bounded acceptance

The application interface defaults to system UTC and consumes one input per
invocation. `Config` and `Tick` in the module define the strict JSON schemas.
There are no endpoint/credential/real-venue fields or execution-enable option.

```powershell
python -m fx_talanta.evaluation.runner register --journal .local/new-runner.sqlite --input config.json
# Use the returned registration hash on every operation; do not replace it.
python -m fx_talanta.evaluation.runner admit --journal .local/new-runner.sqlite --registration-hash $hash --input tick-1.json
python -m fx_talanta.evaluation.runner report --journal .local/new-runner.sqlite --registration-hash $hash
python -m fx_talanta.evaluation.runner stop --journal .local/new-runner.sqlite --registration-hash $hash --reason "input ended"
python -m fx_talanta.evaluation.runner export --journal .local/new-runner.sqlite --registration-hash $hash --output .local/derived-receipts.sqlite
```

These are interface examples, not instructions to start a campaign. Registration
requires a current window; historical fixtures must not be relabeled as current.
For the authorized simulation-only exercise, use the separate bounded harness:

```powershell
$env:PYTHONPATH = "src;."
python -m tools.qualification.paper_runner_acceptance --output .local/paper-runner-fixture-new
python -m tools.qualification.m5_acceptance --output .local/m5-runner-checks-new.json
```

The harness uses an injected fixture clock; it never changes the host clock or
waits for simulated hours to elapse. It feeds six synthetic inputs one at a time,
reopens the runner between inputs, repeats each input's ID, then stops and exports.
It saves the config, ticks, original runner journal, derived receipts and report
to a new directory. No desktop application, broker, live model or public listener
is used. The wider M5 suite uses isolated loopback/headless browser fixtures.

## Existing dashboard integration

Export constructs the existing matched receipt format with three separate arms
and frozen artifact bytes, suitable for `--study-journal-config` and the registered
study panel. It is an immutable **derived export**, not a live subscription: repeat
export uses a new destination. Export refuses overwrite. Keep the source runner
journal plus the returned source registration/head hashes; the derived journal is
not a substitute for original risk/execution evidence. Failed partial exports must
be retained or inspected, never silently adopted as complete.

The source runner remains authoritative for its transition history. Existing
`Ledger.report` and dashboard views retain offline-only/prospective-unverified
labels. Exported comparisons can be read by the advisor; no HTTP endpoint can
advance the runner. Inspection backups do not include external runner journals.

## What this closes and what remains

This closes the **incremental simulation-runner engineering slice**, including
strategy selection, shared risk enforcement, isolated execution, later outcomes,
restart/idempotency, evidence export and existing dashboard integration.

It does not close candidate eligibility, M1-M3 input/cost qualification, real model
integration into this runner, trusted prospective source admission, broker/EA
administration and fault acceptance, actual deployment, or M5's **eight weeks AND
100 closed PAPER trades**. No campaign has begun. B01 and all previous failed
qualification evidence retain their original verdicts.

## Recorded acceptance

The [source-hashed local engineering report](../evidence/m5-paper-runner-engineering-20261106.json)
records **187 backend checks and 10 headless browser scenarios passed**, zero skipped
or flaky. The [bounded synthetic runner report](../evidence/m5-paper-runner-synthetic-20261106.json)
records six observations, 18 matched decisions, one closed simulated position per
arm and three pending final HOLD outcomes. It preserves source/receipt hashes and
explicitly reports zero broker/model calls, no campaign and full M5 incomplete.

Final Python API admission hardening revalidates copied Pydantic models, so callers
cannot bypass literal simulation-only fields or strict sequences. The final
[source-hashed report](../evidence/m5-paper-runner-api-engineering-20261106.json) records
**188 backend checks and 10 browser scenarios passed**, zero skips/flaky results.
The [matching synthetic report](../evidence/m5-paper-runner-api-synthetic-20261106.json)
retains the same six-input lifecycle verdict. Earlier reports above remain preserved.
