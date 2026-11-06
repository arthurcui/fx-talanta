# Bounded model-provider evaluation

M4 now has a real OpenAI Responses API adapter for **evidence selection**, separate
from the trading decision loop. It is simulator-only. The model selects up to five
supplied citations or returns HOLD; it cannot supply display prose, numbers, orders,
tools, policy, risk sizing or deployment instructions. Selected facts are rendered
from the original deterministic evidence projection in English or Chinese.

This completes a bounded API integration slice, not all M4 acceptance. It does not
implement strategy selection, production authentication, a conversation UI or
simulated administrative commands. B01 stays REJECT_FOR_PROMOTION, M1/M3 gaps stay
open and trading stays disabled.

## Boundary and failure behavior

- The explicit model is `gpt-6-luna`, with reasoning disabled, strict JSON Schema,
  no tools, no streaming and `store=false`. No automatic model fallback is allowed.
  The requested and returned identifier must match. The successful smoke returned
  the same alias; it did not establish an immutable model snapshot. Future behavior
  changes require new evaluation, not an assertion of version-pinned reproducibility.
- Requests send the question and projected evidence only. Account identity, actor,
  broker credentials, source prose and conversation history are not included by the
  adapter. A trusted caller must supply the projection and an appropriate question;
  this is not an authenticated public endpoint or a general-purpose secret redactor.
- The endpoint is fixed to HTTPS `api.openai.com/v1/responses`; TLS verification
  remains enabled. Proxy inheritance and HTTP redirects are disabled. The key is
  read privately by the explicit smoke CLI and is not printed or copied into Git.
- Input is capped at 16,000 serialized bytes and output at 512 model tokens and
  65,536 response bytes. HTTP socket timeout is 15 seconds; a result arriving after
  the 15-second acceptance window or explicit expiry becomes HOLD. Socket timeout
  is not a guaranteed hard wall-clock cancellation deadline; this adapter must not
  run inside protective management or the EA event loop.
- One exclusive, flushed reservation file is written before any network call. The
  same path is consumed after success, failure or process interruption. Concurrency
  allows one sender. There are no repair retries, refunds or blind resends. A failed
  result write leaves a consumed reservation rather than authorizing another send.
- Refusal, incomplete output, unexpected model/tool content, unknown/duplicate
  citations, malformed usage and schema violations produce HOLD. HTTP failures
  retain only a status code; exception text and provider error bodies are excluded.
  The local code validates citations independently of Structured Outputs.
- Result receipts bind request/evidence/response hashes, prompt version, model,
  elapsed latency and usage where accepted. Changed evidence is rejected by the
  renderer. Source availability and fact accuracy still depend on the supplied
  projection; this is not proof of general semantic relevance or prompt-injection
  robustness. It cannot turn selected text into a command.

## Actual API evidence

The [sanitized smoke result](../evidence/m4-provider-smoke-20261106.json) records
one request on November 6, 2026 UTC: EXPLAIN/EVIDENCE_SELECTED, 435 input tokens,
45 output tokens and 2,611 ms latency. Only the constructed zero-volume risk-check
record was supplied, and its exact citation was returned. No terminal or broker
request occurred. This verifies API access and the bounded schema/citation path,
not economic value, latency reliability, authenticated users or full M4 completion.

**2,611 ms exceeds the unchanged two-second entry ceiling.** This advisor smoke
does not exercise or pass that entry gate. Its explanatory deadline cannot be used
to extend trading freshness; a future strategy adapter must recheck original quote
age at completion and every existing risk/dispatch gate.

The [model documentation](https://developers.openai.com/api/docs/models/gpt-6-luna)
was checked before implementation. API integration follows
[Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=responses).
These sources describe supported contracts, not guarantees of correctness or
account-specific billing. Usage is recorded; no invoice-equivalent charge is claimed.

## Reproduction and remaining integration

Offline tests never require a key or contact the API:

```text
python -m pytest tests/test_advisor_provider.py tests/test_advisor_evidence.py tests/test_advisor_journal.py
```

An explicitly authorized live smoke uses a **new** private directory:

```text
python -m tools.qualification.provider_smoke --key-file <ignored-local-env-file> --output <new-private-directory>
```

The smoke always constructs its own evidence; it cannot accept account data or
external prompts from the CLI. The key file contains `OPENAI_API_KEY`; it is not
bundled into containers or CI. Run directories and their reservations must be
preserved. Creating another directory is another explicit evaluation attempt,
not an automatic retry or cumulative budget reset.

## Durable provider reservation service

`advisor/provider_ledger.py` adds simulator-only PostgreSQL orchestration. Before
sending, one transaction verifies the database binding, locks the shared budget,
and appends the immutable policy and request reservation. Request identity binds
serialized input, evidence and expiry. Concurrent workers cannot consume the same
request twice or exceed the configured call/reserve allowances.

The policy is one lifetime budget per bound database: maximum calls, a positive
USD reserve per call, total reserved USD and a stated costing basis. It cannot be
changed or reset. A reservation remains spent after timeout, failure or process
interruption. This is a conservative configured reserve, **not actual billing**:
the operator must justify the reserve against input/output limits and current
pricing. No invoice, hard billing limit across other clients, or automatic refund
is claimed. Usage is retained separately in accepted result receipts.

The result is committed before returning. An identical retry retrieves a stored
result; an unresolved reservation returns OUTCOME_UNKNOWN_NO_RESEND without a
network request. A result-commit failure propagates and keeps the reservation
spent. Budget exhaustion returns HOLD. Unknown outcomes require investigation;
there is no automatic resend, reconciliation against provider billing or reset.
The service does not hold a database transaction open during the network call.

Policy, reservation and result use append-only conversation-message records with
versioned components and deterministic IDs. They are service receipts, marked
unauthenticated and READ_ONLY, not owner instructions. No schema migration or
broker authority is introduced. A trusted caller supplies an already authorized
projection; authentication and full conversation/request linking remain separate
integration work. The two-second trading rule is unchanged.

The standalone file-based smoke remains a separately authorized evaluation tool;
it does not use or bypass this service as a production worker. No unattended
worker, public endpoint or deployment is enabled. Tests use constructed evidence
and fake transport: no additional paid API call or broker operation is needed.

Run `python -m pytest tests/test_advisor_provider_ledger.py` for offline failure
checks. With the existing isolated CI PostgreSQL bootstrap, `--integration`
additionally exercises concurrent last-slot admission, restart idempotency,
unknown outcomes, immutable policy and cumulative exhaustion. Run that integration
suite in a fresh test database because its append-only lifetime budget is retained.

Remaining M4 acceptance includes authenticated access, strategy proposals and
risk integration, simulated administrative commands, and broader model evaluation.
This service completes durable reservation mechanics, not those acceptance gates.
