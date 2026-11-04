# Current M2 handoff

PR #22 is merged after CI. The [disabled demo execution integration](m2-demo-execution.md)
now carries full requests into the native dispatcher and separately journals native outcomes.
The new host is compiled and fixture-tested, not deployed; broker submission and
protective mutations stay disabled. Reviewed activation and demo-order acceptance remain.

PR #21 completed the bounded native HOLD/ACK handoff and was merged after CI.
The [consolidated disabled integration](m2-disabled-integration.md) now joins
operating-evidence loading, durable safety state, fenced delivery, native risk
assessment and receipt recovery. Connected execution remains disabled; full M2D
still requires the explicitly authorized demo execution/acceptance gate.

The M2A scope below is retained as historical implementation context, not a new
instruction to repeat M2A or a claim that the later native handoff is unfinished.

## Historical M2A: first implementation PR, intent + EA protocol

**Owner-authorized on 3 November 2026; offline implementation delivered.** See
the [M2A implementation and evidence](m2a-protocol.md). PRs #17 and #18 are merged;
the [M2B native implementation](m2b-fixed-ea.md) and the separate
[M2C offline safety/native parity evidence](m2c-deterministic-safety.md) now follow it.
Real snapshot sourcing, deployed transport/fencing and end-to-end shadow timing
remain gates; connected execution is disabled. This replaces
the obsolete instruction to start M0A. Follow the [canonical architecture](architecture-plan.md)
and [EA boundary](ea-execution-boundary.md); preserve implemented M0A–M0C.
Start this offline increment now under the owner's M2 progression authorization.
Carry unresolved M1 evidence explicitly; do not require another broker soak before
protocol work. Connected orders remain disabled. The canonical sequence is M2A protocol, M2B fixed EA execution,
M2C deterministic safety, then M2D connected PAPER acceptance.

## Exact scope

1. Add versioned, additive Python contracts for DecisionIntent, ExecutionRequest,
   ExecutionAck, ExecutionState and ReconciliationResult, with decimal-string units, UTC expiry, immutable
   account/venue, release/policy digests, reservation identity, canonical payload
   hash, sequence and stable rejection reasons. Do not repurpose existing M0A
   record kinds or alter historical migrations. Administrative work may reuse the
   existing typed action vocabulary; do not add conversational interpretation.
2. Add shared fixture JSON reference vectors and a Python reference runner for
   existing USD and proposed CAD EURUSD/USDJPY eligibility, conversion, downward
   lot rounding, costs, exposure, margin, partial/reserved risk and persisted loss
   baselines. Keep the existing USD simulator guard and behavior intact. Missing,
   stale, inconsistent conversions and minimum lots above budget must reject.
   These prepare M2C parity; M2A does not implement or qualify the full EA risk engine.
3. Add a small fixture-fed **MQL5 validation/replay harness source** for these
   contracts and reference calculations, with broker submission absent
   (no OrderSend, CTrade, trade-capable DLL or WebRequest path). It reads fixtures
   and emits results; it is not the deployable execution EA. Share cases and
   reason codes rather than generating expected outputs from the code under test.
4. Test same-ID/same-hash replay, conflicting hash, cross-account/version/expiry
   rejection, reservation consumption without double counting, pending/unknown
   exposure, stale closes and action precedence offline. Use the existing
   simulator as the behavioral oracle for already-supported USD cases.
5. Document invocation, expected artifacts and limitations. Record source checks
   and Python fixture results; explicitly report native compiler/Tester execution
   as NOT RUN if that separate environment was not exercised. Do not claim
   cross-language parity until independently produced MQL5 outputs match vectors.

Suggested new paths: `domain/ea_protocol.py`, `execution_contracts/` reference
helpers under `src/fx_talanta/`, `mql5/offline/`, `tests/fixtures/ea_protocol/`
and targeted contract/parity tests. Names are implementation choices; the authority
and scope limits above are fixed. Existing `gateway/offline.py`, simulator,
governor, records and migrations remain the reference rather than being rewritten
into a real broker adapter.

## Reviewable exit artifacts

* Versioned schemas and canonical examples, rejection-code table and invariant tests.
* Human-auditable USD/CAD expected vectors including boundary/rounding counterexamples.
* Python results linked to source/fixture hashes, and fixture-only MQL5 harness source.
* Existing M0 regression results and unchanged historical evidence/migration hashes.
* Explicit capability audit: no credentials, endpoints, terminal mutation, deployment
  script, production dispatch service, database migration or broker submission.

Required repository CI retains the name **M0A checks**. This first PR may finish
without native compilation, but then **native parity and M2 stay pending**.
M2B implements fixed EA execution and supplies reviewed native build/Tester
evidence. M2C proves deterministic safety, USD/CAD parity and isolated no-order
shadow behavior with fresh binding/clock checks. M2D performs actual demo
acceptance only after M1 and M2A–C prerequisites pass and demo access is explicitly
authorized. M2B order code must not enable connected submission before M2C passes.
No shadow result or code merge silently enables orders.

## Protocol terminology

The message names refine the earlier design without discarding its safeguards:

| Canonical contract | Earlier design term | Meaning |
| --- | --- | --- |
| DecisionIntent | StrategyProposal | Untrusted bounded proposal with evidence/cutoff; never execution authority |
| ExecutionRequest | AuthorizedWork | Backend-validated expiring allowance with shared reservation ID; EA can narrow/veto |
| ExecutionAck | ExecutionEvent: receipt/acceptance subtype | Durable receipt or request acceptance; never proof of fill |
| ExecutionState | ExecutionEvent: lifecycle subtype | Versioned order/deal/position/protection state with immutable event identity |
| ReconciliationResult | ExecutionEvent: reconciliation subtype | Broker evidence resolving or preserving unknown outcome and reservations |

EAHealth remains a separate read-only health envelope. Existing M0A record types
are not renamed; new protocol types have explicit versioned adapters. Stable event
identity/hash/sequence and append-only storage apply to all three event subtypes.
Protocol acknowledgments distinguish backend receipt, EA receipt and broker
acceptance so an HTTP success cannot become a confirmed execution.

## Explicit exclusions

No FastAPI deployment, endpoint/relay, actual execution EA, chart attachment,
compiler invocation against installed broker terminals, new campaign, terminal
configuration change, shared Python environment modification, broker operation,
LIVE activation, B01 production engine, model calls, paid service or dashboard.
Do not edit frozen campaign sources or reclassify failed/stopped evidence.

## Required UI telemetry contract in M2A

Include an additive read-only contract with account/symbol scope, channel
(EA / Python package / MCP), capability, configured/enabled state, transport
health, last heartbeat/success/error, original tick timestamp/age, receipt time
and measured delivery delay with window/sample count. Unknown metrics are nullable.
Heartbeats cannot refresh tick age and telemetry cannot grant execution authority.
M2A provides schemas and fixtures only, not a dashboard or connected deployment.
M2B emits telemetry; M2C validates stale-quote/healthy-channel and failure/recovery
cases. M4 exposes authenticated reads. M5 delivers latency and channel-status UI
with explicit source/capability labels and the two-second entry-block reason.
