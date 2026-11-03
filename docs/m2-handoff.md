# First implementation PR: offline EA contracts and parity

**Proposed scope, not implemented or authorized by the design PR.** This replaces
the obsolete instruction to start M0A. Follow the [canonical architecture](architecture-plan.md)
and [EA boundary](ea-execution-boundary.md); preserve implemented M0A–M0C.

## Exact scope

1. Add versioned, additive Python contracts for StrategyProposal, AuthorizedWork,
   ExecutionEvent and EAHealth, with decimal-string units, UTC expiry, immutable
   account/venue, release/policy digests, reservation identity, canonical payload
   hash, sequence and stable rejection reasons. Do not repurpose existing M0A
   record kinds or alter historical migrations. Administrative work may reuse the
   existing typed action vocabulary; do not add conversational interpretation.
2. Add shared fixture JSON golden vectors and a Python reference runner for
   existing USD and proposed CAD EURUSD/USDJPY eligibility, conversion, downward
   lot rounding, costs, exposure, margin, partial/reserved risk and persisted loss
   baselines. Keep the existing USD simulator guard and behavior intact. Missing,
   stale, inconsistent conversions and minimum lots above budget must reject.
3. Add a small fixture-fed **MQL5 validation/replay harness source** for these
   contracts and deterministic policy calculations, with broker submission absent
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
The next separate gate is reviewed native build/Tester evidence, followed by
read-only shadow on an isolated terminal with fresh binding/clock checks. Actual
demo orders require resolved P0/M1 prerequisites and explicit provisioned demo
authorization; no shadow result or code merge silently enables them.

## Explicit exclusions

No FastAPI deployment, endpoint/relay, actual execution EA, chart attachment,
compiler invocation against installed broker terminals, new campaign, terminal
configuration change, shared Python environment modification, broker operation,
LIVE activation, B01 production engine, model calls, paid service or dashboard.
Do not edit frozen campaign sources or reclassify failed/stopped evidence.
