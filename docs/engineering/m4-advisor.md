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

| Work | Required acceptance |
| --- | --- |
| Bounded provider integration | Strict proposal schema, candidate/account allowlists, versioned model/prompt/input hashes, original two-second freshness, timeout/expiry and configured spend/retry caps; failures produce recorded HOLD |
| Durable decision/conversation integration | Existing append-only records retain input/evidence IDs, model trace, costs, rejection reasons and deterministic idempotency; no raw secrets |
| Authenticated evidence API | Server-derived read grants, account isolation, private transport and unauthorized/cross-account tests; exact windows and deterministic metrics |
| Evidence-backed explanation | Cite exact records, distinguish rationale from later interpretation, mark unknown/stale facts, resist injected source text; English/Chinese semantic parity |
| Memory | Qualified and activated evidence only at decision cutoff, retained contradicting cases, no future-outcome leakage or conversational promotion |
| Simulated administrative commands | Explicit account/position/expiry/state version; questions, quotations, negations and ambiguity cannot mutate; retries retain one identity; simulator only |
| Evaluation | Frozen fixtures plus malformed/timeout/budget/expiry/injection cases; separate engineering success from any AI economic claim; prospective benefit remains an M5 gate |

No provider SDK/API calls or key setup are included in this first slice. Completing
it does not mark all M4 acceptance passed. The model cannot create execution
authority, qualify missing market inputs, alter policy or deploy itself.

## Verification

```text
python -m pytest tests/test_advisor_evidence.py
python -m pytest tests/test_advisor_evidence.py --integration
```

Unit tests cover account/time isolation, duplicate/corrupt inputs, exact-version
queries, missing links, bilingual citation identity and memory cutoffs. The
PostgreSQL test projects existing demo records and confirms the stored history is
unchanged. It runs on CI's isolated fixture database; no local broker database or
terminal is required.
