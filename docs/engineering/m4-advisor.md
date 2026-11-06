# M4 bounded AI and advisor

Read the [consolidated M4 acceptance matrix](m4-completion.md) for current scope,
verification and retained limits. This page describes the implemented application
interfaces. Trading is disabled; M1/M2/M3 gaps and B01 rejection remain unchanged.

## Authenticated local API

`advisor.access.AdvisorAPI` is the supported application boundary. A trusted host
constructs `AccessControl` from protected `Principal` configuration: actor, exact
account, expiry, permission set, allowed command actions and SHA-256 digest of a
random bearer credential. No client-supplied actor, ReadGrant or action scope is
accepted. Verification uses constant-time digest comparison; invalid, expired,
revoked and cross-account credentials fail before provider or gateway work.

`read`, `explain`, `rationale`, `snapshot`, `command` and `propose` have separate
permissions. The host supplies repositories, gateway, budget, transport, strategy
allowlist and proposal-source callback; a proposal caller supplies only request
identity. Reads/explanations recheck authority before delivery; proposals recheck
after model work and before dispatch. Commands serialize revocation with command
start. Revocation cannot undo an already completed action.

This API runs in-process and opens no listening socket. Local process/OS access is
the private transport boundary. A network adapter, TLS, login UI and deployment
are separate work, not implicit permission to expose these methods publicly.
Lower-level modules remain trusted internal interfaces. Authenticated audit
messages are distinct from legacy unauthenticated service receipts; no token is
stored in either. Host configuration must persist revocation across restart.

## Evidence and explanations

`evidence` and `journal` retain exact record IDs/hashes, account, actor, cutoff,
provenance, unavailable and unresolved references. Reads are bounded to 32 requested
IDs and 1,000 dependencies, with the existing 4,096-character record limit. Missing,
unsupported or future data never becomes a fabricated balance, close or health
pass. Queries pin versions; historical views do not claim current account status.

`service.answer_question` saves a request manifest, an exact projection, a reserved
provider outcome and an answer referencing those receipts before returning. Model
selection accepts only supplied citations; displayed values come from typed facts,
not model prose. English/Chinese rendering shares citations. Unsupported text has
no route to administrative commands. Original decision rationale is available
through `rationale`, explicitly labeled as an untrusted original quotation. Later
model selection is separately labeled and never rewrites that original record.

An identical request within its deadline returns its saved answer. Changed scope,
question, language, conversation, budget or deadline conflicts. Storage failures
propagate; uncertain provider reservations never permit a resend. An answer is
saved only after read authority remains valid. See [provider details](m4-provider.md).

## Bounded strategy proposals

`proposal_contracts` defines server-owned candidates and allowed exit options.
`proposals` sends only structured candidates and the safe evidence projection to
the fixed provider. Account/credential data, source instructions, raw rationale and
unqualified lessons are omitted. The model can SELECT one candidate/allowed exit
or HOLD. It cannot generate account, volume, stops, risk policy or execution code.

The exact input snapshot, prompt/model/hash/usage trace, shared budget reservation,
provider outcome and decision are durable. Decision and experience-case records
commit atomically. Failed, expired, malformed or over-budget responses produce HOLD;
uncertain in-flight requests remain explicitly unresolved and cannot be resent.
No favorable outcome or lesson promotion is invented from a successful API call.

The model call occurs outside gateway/control locks, so deterministic protection
can continue. The original two-second quote ceiling is checked before/after the
call and before dispatch. A valid schema is not approval: the existing offline
gateway performs deterministic sizing, spread/exposure/loss checks, reservation,
protection and reconciliation. An identical decision retry is a historical receipt,
not a fresh dispatch capability. A crash between saved decision and dispatch does
not authorize a catch-up order. B01 cannot be promoted via this interface.

## Memory and simulated commands

Only qualified, activated lessons whose referenced cases and outcome-known times
are available by cutoff are eligible. Supporting and contradicting evidence is
retained; no chat message or proposed lesson can activate memory. See the existing
projection tests and consolidated acceptance report for future-leakage cases.

[The offline command adapter](m4-command-gateway.md) supports explicit bilingual
pause/resume, owned close and flatten/halt through the existing simulator gateway.
Questions, quotations, negations, missing targets and unsupported clauses cannot
mutate. Pending cancellations precede closes; outcome uncertainty and interrupted
receipts cannot cause a blind resend or a fabricated completion.

## Verification

```text
python -m tools.qualification.m4_acceptance --integration --output .local/m4-acceptance.json
```

The [acceptance matrix](m4-completion.md) maps each requirement to implementation
and tests. The actual API observations remain separate from deterministic fixture
results and economic qualification. No connected strategy operation is enabled.
