# M4 consolidated engineering acceptance

M4 joins authenticated local access, evidence-backed explanations, bounded model
proposals, deterministic risk, simulator execution, administrative controls and
retained learning evidence. The implementation is complete for the offline scope;
the source-bound report and CI below determine acceptance. No connected strategy,
LIVE trading, new campaign or deployment is enabled.

## Acceptance matrix

| Gate | Implementation and decisive evidence |
| --- | --- |
| Identity and account authority | `access.py` verifies a configured high-entropy bearer digest, expiry, revocation, permission and exact PAPER/SIMULATOR account; server-derived grants; denial/cross-account tests in `test_m4_consolidated.py` |
| Private API | In-process application API, with no listening socket; host process/OS access is the transport boundary. Cloud/HTTP exposure requires a separate TLS and deployment design |
| Durable verified access | Authenticated audit receipts precede permitted operations; tokens and digests are never journaled; internal legacy receipts remain marked unauthenticated |
| Bounded strategy proposal | Strict SELECT/HOLD schema; at most eight server-defined candidates and their exit options; no model account, size, stop, policy or code fields; rejected B01 release cannot be selected |
| Model failure and resource limits | Shared append-only call/reserve budget; one send, no refund/retry; request/response byte and token caps; malformed/refusal/wrong-model/tool/usage/invented-candidate failures become retained HOLD |
| Timeliness and deterministic risk | Original quote ceiling of two seconds checked after model response and before simulator dispatch; existing gateway repeats freshness, exposure, loss, spread, sizing, ownership and protection checks |
| Evidence and explanations | Exact record versions, hashes and as-of cutoff; original recorded rationale returned as an untrusted quotation, separately labeled from later evidence selection; fixed English/Chinese rendering |
| Qualified memory | Existing projection checks qualification, activation, resolved support and contradicting cases and outcome-known cutoff; the proposal excludes ineligible lessons and source prose |
| Command behavior | Explicit account/position, exact bilingual grammar, expiry, state token, resume restrictions; existing gateway lock, persistent writer ownership and management lifecycle; no model command route |
| Restart and uncertainty | Durable request/provider/decision/experience links; retries cannot reissue paid calls or simulator orders; incomplete provider or management outcomes stay unknown |
| Subsequent learning | Every completed proposal creates an atomic decision/case pair. Entry economics remain UNKNOWN until execution outcomes; HOLD has no invented P&L. Nothing automatically qualifies or promotes a lesson |
| Evaluation | Frozen candidate fixture, adversarial and failure tests, real PostgreSQL full pipeline, native/container suite and source-bound machine-readable acceptance report |

The reproduction command is:

```text
python -m tools.qualification.m4_acceptance --integration --output .local/m4-acceptance.json
```

Run against the configured disposable local/CI PostgreSQL service. The tool creates
a fresh namespace, refuses to overwrite an output, and emits PASS only when every
selected M4 test passes, integration is enabled and no case is skipped. It does not
read API keys, contact a model, open MT5 or touch broker campaigns. CI uploads the
report as `m4-engineering-acceptance`.

Acceptance execution results will be recorded in this PR after CI completes.

## Actual provider observation

The [proposal smoke](../evidence/m4-proposal-smoke-20261106.json) made exactly one
OpenAI call with constructed input. The schema validated and the model returned
HOLD / INSUFFICIENT_EVIDENCE: 297 input tokens, 34 output tokens, 1,874 ms elapsed,
and 1,875 ms original input age. No entry was selected or dispatched. This proves
that the proposal schema reached the API and its HOLD response validated, not that
SELECT quality, economic benefit or sustained two-second service is qualified.
The earlier [evidence-selection smoke](../evidence/m4-provider-smoke-20261106.json)
remains unchanged, including its 2,611 ms latency above the entry ceiling.

Both preserve exact source hashes. Archived sources retain the version used for
the observation if later integration code changes. Requested/returned model aliases
are recorded; an alias is not an immutable model snapshot. Fixed response fixtures
prove validator behavior, not model reasoning quality.

## Retained boundaries

- B01 remains REJECT_FOR_PROMOTION. There is no promoted AI strategy in this PR.
- M1 broker/provider gaps, M2 connected fault-matrix gaps and M3 cost/source gaps
  remain mandatory before applicable connected strategy qualification.
- Bearer configuration belongs to the trusted local host. Use random tokens with
  at least 32 bytes of entropy; store only digests in protected configuration.
  Runtime revocation is process-local: persist removed/revoked credentials in host
  configuration before restart. No user login UI, remote endpoint or deployment is
  supplied by M4. A process administrator is outside this credential boundary.
- The configured monetary reserve is not invoiced cost. Actual usage is retained,
  and unknown outcomes are not refunded. Candidate and data source configuration
  remains server-owned and must not be accepted from model or client fields.
- This is engineering acceptance. Broader natural-language coverage, real strategy
  quality, comparative economic value and unattended operation require M5 evidence.
  Unsupported wording remains non-mutating instead of being guessed.

No new 24-hour test is required or authorized by this closeout.
