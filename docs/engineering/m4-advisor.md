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
supplied evidence, with deterministic rendering and no trade authority. Production
spend reservation/journaling, strategy proposals and authentication remain pending.
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
