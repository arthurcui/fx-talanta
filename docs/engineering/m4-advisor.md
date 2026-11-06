# M4 bounded AI and advisor

M4 development is authorized after the [M3 research closure](m3-research-closeout.md).
The M3-Q1–Q4 evidence gaps, M1 operational gaps, M2 fault matrix and B01 rejection
remain unchanged. Trading stays disabled; B01 is not promoted into an AI strategy.

## Implemented first slice: offline evidence projection

`advisor.evidence` accepts a bounded snapshot of existing typed `Record` objects,
a trusted-caller `ReadGrant`, and an explicit account/as-of/record-ID query. It
returns exact record citations, payload hashes, provenance, allowlisted facts and
unavailable/unresolved references. It never fetches a terminal or invokes a model,
repository writer, command router, risk override or broker API.

The caller's grant is **not authentication** and must never be accepted directly
from a client or model. This slice supports SIMULATOR accounts only. There is no
HTTP server, credential handling or production authorization claim. A later
authenticated read API must derive the grant from server-verified identity.

Each request revalidates models (including constructed/copied objects), enforces
the exact account, grant expiry, as-of bound, 32 requested IDs and 1,000-record
snapshot ceiling. Duplicate IDs and malformed/mixed-account snapshots fail closed.
Missing, unsupported and future records return unavailable; they do not become
zero P&L, a confirmed close, a health pass or an empty successful trade history.

Queries pin specific versions. They do not infer current account state or silently
replace an old record with its latest correction. News availability and experience
outcome times are constrained by the existing Record validators. Future health
checks are withheld. Missing reference/correction targets are explicit.

Only typed enum/numeric/time facts are projected. Raw model responses, rationale,
news text, hypotheses and conversation text are excluded. This deliberately narrow
boundary prevents stored instructions from becoming actions; it is not a completed
LLM prompt-injection defense. Original rationale and later AI interpretation remain
future, separately labeled capabilities. No performance aggregates are invented.

Lesson eligibility requires QUALIFIED status, activation by the query cutoff,
nonempty supporting cases, distinct supporting/contradicting identities, resolved
dependencies and case outcome-known times by cutoff. Eligibility is a temporal
filter over supplied records, not independent validation of the qualification
process or strategy promotion. Proposed/rejected/later lessons are never activated.

Fixed English/Chinese labels share the same typed facts and citation IDs. This is
deterministic rendering, not natural-language understanding or a chat UI. Repeated
queries have no side effects; no account state, source record or authority changes.

## Remaining M4 acceptance

### Durable offline read conversations

`advisor.journal.read_and_record` now loads exact evidence IDs and their bounded
dependency closure from the existing account-bound repository, projects the answer,
and atomically appends a typed query and exact JSON answer as two conversation
messages. The receipt retains citation IDs/hashes, unavailable IDs, provenance,
as-of and generation times. Fixed bilingual rendering can be applied to that same
saved receipt; no free-form user text or command interpretation is accepted.

Request UUIDs derive stable message IDs. Re-delivery validates actor, account,
conversation, language and query, then returns the original receipt. Later evidence
does not change a previously unknown answer; a genuinely new query needs a new
request ID. Changed content under the same ID, partial receipts, expired access,
wrong accounts and future receipts fail closed. Concurrent delivery cannot append
another pair. A caller whose captured clock predates a winning concurrent receipt
must retry with a current time; it cannot overwrite that receipt.

The existing 4096-character message contract is retained. Both messages are fully
validated before the atomic append, so oversized evidence results fail without
truncation or a partial conversation. Request fewer records in a new query. Source
records and execution history remain unchanged. Dependency traversal is capped at
1,000 identities and never scans account history or follows future-record links.

These are trusted-caller offline records with `authenticated=false`, not a claim of
real owner authentication. They are explicitly READ_ONLY and create no command,
risk reservation or broker call. PostgreSQL failure returns an error, not an
unrecorded successful response. Production authentication, model traces and
natural-language conversation/command handling remain unfinished.

| Work | Required acceptance |
| --- | --- |
| Bounded provider integration | Strict proposal schema, candidate/account allowlists, versioned model/prompt/input hashes, original two-second freshness, timeout/expiry and configured spend/retry caps; failures produce recorded HOLD |
| Durable decision/conversation integration | Existing append-only records retain input/evidence IDs, model trace, costs, rejection reasons and deterministic idempotency; no raw secrets |
| Authenticated evidence API | Server-derived read grants, account isolation, private transport and unauthorized/cross-account tests; exact windows and deterministic metrics |
| Evidence-backed explanation | Cite exact records, distinguish rationale from later interpretation, mark unknown/stale facts, resist injected source text; English/Chinese semantic parity |
| Memory | Qualified and activated evidence only at decision cutoff, retained contradicting cases, no future-outcome leakage or conversational promotion |
| Simulated administrative commands | Explicit account/position/expiry/state version; questions, quotations, negations and ambiguity cannot mutate; retries retain one identity; simulator only |
| Evaluation | Frozen fixtures plus malformed/timeout/budget/expiry/injection cases; separate engineering success from any AI economic claim; prospective benefit remains an M5 gate |

The [bounded provider evaluation](m4-provider.md) adds a real API smoke for selecting
supplied evidence, with deterministic rendering and no trade authority. Durable simulator
provider reservations are implemented; strategy proposals and authentication remain pending.
Completing these slices does not mark all M4 acceptance passed. The model cannot create execution
authority, qualify missing market inputs, alter policy or deploy itself.

## Verification

```text
python -m pytest tests/test_advisor_evidence.py tests/test_advisor_journal.py
python -m pytest tests/test_advisor_evidence.py tests/test_advisor_journal.py --integration
```

Unit tests cover account/time isolation, duplicate/corrupt inputs, exact-version
queries, missing links, bilingual citation identity and memory cutoffs. The
PostgreSQL test projects existing demo records and confirms the stored history is
unchanged. It runs on CI's isolated fixture database; no local broker database or
terminal is required.
Journal tests additionally cover restart/re-delivery, changed request identity,
late-arriving evidence, storage failure, oversized receipts and concurrent delivery.
The PostgreSQL cases verify exactly two durable messages and unchanged source
records. Test doubles are unit fixtures, not a SQLite substitute for production.

## Integrated simulator advisor service

`advisor.service.answer_question` connects a trusted read grant and explicit
account/as-of/record IDs to the durable evidence journal, provider budget ledger
and a saved, deterministically rendered answer. It does not take caller-supplied
model evidence or expose an HTTP endpoint. The provider transport is injected;
there is no auto-started worker or broker path.

The append-only trail is:

1. A service request binds actor, account, conversation, language, query, question
   hash, deadline, budget and deterministic provider request ID. Raw question text
   is not saved in the journal; it is still sent to the provider. A trusted caller
   must avoid including secrets. Hashing is not authentication or redaction.
2. The existing journal saves the exact evidence projection before any model call.
3. The provider ledger reserves budget before sending and saves the result. Unknown
   outcomes cannot become a successful saved answer or trigger another call.
4. The service rechecks read access, renders the selected original facts, then saves
   an answer with references to the service request, evidence and provider result.
   No answer is returned until this final write commits.

An answer is explicitly labeled `LATER_EVIDENCE_SELECTION_NOT_ORIGINAL_RATIONALE`.
Its as-of/scope remain visible; historical evidence never becomes a current-account
health claim. English/Chinese explanations share cited typed facts. HOLD reason
codes are retained; the existing HOLD display string remains English.

Identical retries within the original deadline return the same saved answer.
Changed questions, actor, account, language, conversation, budget or deadline fail
before another provider call. A failed final write can be retried using the saved
provider result without another call. Expired grants/deadlines fail closed; expiry
never authorizes a new request ID. An unresolved reservation raises an explicit
error, preserving all intermediate receipts for investigation. This is a staged
workflow, not one transaction held open across the external request.

Tests use fake transport and isolated CI PostgreSQL, including a separate disabled
SIMULATOR database fixture for the service's immutable lifetime budget. There are
no real API calls or terminal operations in these tests. Verify with:

```text
python -m pytest tests/test_advisor_service.py
python -m pytest tests/test_advisor_service.py --integration
```

This completes the evidence-selection conversation path for trusted simulator
callers. It does not complete authenticated access, unrestricted chat, original
rationale narration, strategy selection, simulated administrative commands, or M4
as a whole. Questions and imperatives have no administrative interpretation in this
service. M1/M3 gaps, B01 rejection and the two-second entry rule remain unchanged.

## Simulated administrative command boundary

`advisor.commands` implements a pure command evaluator and an append-only
PostgreSQL evaluation journal. It does **not** call the offline execution gateway,
change its state, dispatch an EA request, or operate a broker. This closes the
interpretation/state-transition test slice; the [offline gateway adapter](m4-command-gateway.md) now supplies execution wiring.
Authenticated command intake remains open M4 work.

The trusted harness supplies a `SimulatedScope`, a typed request and explicit state.
The scope is test authority, not authentication. Only PAPER/SIMULATOR bindings are
accepted. Receipts remain unauthenticated READ_ONLY messages with
`simulation_only=true` and `execution_enabled=false`; they are deliberately not
executable AdministrativeCommand records.

Supported commands are PAUSE_ENTRIES, RESUME_ENTRIES, CLOSE_OWNED_POSITION and
FLATTEN_OWNED_AND_HALT. `command_text` exposes the exact English/Chinese grammar,
including canonical full account identity and an exact owned position UUID for a
close. This narrow grammar is intended for deterministic evaluation, not a polished
chat UI. No substring, fuzzy match or model interpretation is used. Questions,
negations, quotes, extra clauses and unsupported wording are rejected without a
transition. Dashboard account selection cannot supply a missing target.

Evaluation checks scope, action permission, request/grant expiry, expected state
version and a state snapshot no older than two seconds. Resume additionally needs
healthy/qualified inputs, no unresolved orders, no loss/integrity/hard halt and an
original quote between zero and two seconds old inclusive. It clears only the
administrative pause in the returned simulation state; it never enables trading.
Pause and flatten never clear existing halts. Flatten sets pause and hard halt
before its simulated closure outcome is evaluated.

The harness must explicitly inject a simulated confirmed-close observation.
Without one, positions remain present and the result is SIMULATED_OUTCOME_UNKNOWN.
Already unresolved orders cannot be turned into success by another confirmation
flag. Reconciliation is deliberately not invented here. Confirmed close removes
only the specified owned position; flatten removes only the supplied owned set.
There is no volume, reverse-position or new-entry action in this evaluator.

`evaluate_and_record` commits one request/result pair atomically under a PostgreSQL
transaction lock. Concurrent identical deliveries return the original pair.
Changed content under a request ID conflicts; retrying an unknown result with a
confirmation flag cannot rewrite it as completed. Records capture before/after
simulation state, reason, action and scope; the original request remains linked.
An expired scope cannot retrieve a receipt. A valid scope can retrieve a prior
receipt after request expiry without re-evaluating it. Storage failure returns an
error, not a claimed simulated action. These receipts are historical evaluation
results, never proof of current gateway state or broker closure. The harness owns
state sequencing; this journal does not serialize autonomous gateway entries.

Verification:

```text
python -m pytest tests/test_advisor_commands.py
python -m pytest tests/test_advisor_commands.py --integration
```

Tests cover bilingual parity, hostile/ambiguous wording, target/version/time
checks, two-second boundaries, resume restrictions, unknown closes and concurrent
PostgreSQL replay. Existing M1/M2/M3 gaps and B01 rejection remain unchanged.

The [offline command gateway](m4-command-gateway.md) derives state from the existing
gateway and routes management through its journaled simulator lifecycle. It does
not use the evaluator's injected confirmation flag as execution evidence.
