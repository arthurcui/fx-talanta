# M2A: first implementation PR, intent + EA protocol

**Proposed scope, not implemented or authorized by the design PR.** This replaces
the obsolete instruction to start M0A. Follow the [canonical architecture](architecture-plan.md)
and [EA boundary](ea-execution-boundary.md); preserve implemented M0A–M0C.
Start this increment after M1 qualification and separate implementation
authorization. The canonical sequence is M2A protocol, M2B fixed EA execution,
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
