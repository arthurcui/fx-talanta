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

This file reservation is an evaluation artifact, **not a replacement for the
PostgreSQL production journal**. The next integration must reserve model spending
and request identity durably under account-scoped concurrency control before sending,
persist provider outcomes/traces alongside the existing conversation receipts, and
enforce a cumulative configured spend cap. The current one-call/token/byte bounds
do not claim a service-wide monetary cap across arbitrary new directories. No
unattended worker or production caller is enabled by this module.
