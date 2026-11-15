# Architecture walkthrough

Current delivery architecture: [AI-led trading lifecycle](trading-lifecycle.md),
with the system diagram and R0-R6 component/authority/failure trace.
The [roadmap](../product/roadmap.md) defines integrated UI acceptance for every stage.
Existing execution contracts below are reused; historical qualification is not reset.

FX-Talanta separates proposals from authority. Python owns orchestration and durable
records; deterministic controls reserve risk; one fixed reviewed EA owns the native
submission boundary. A model cannot replace the EA or bypass those checks.

## One decision, end to end

| Step | Responsible component and authority | Recorded evidence | Failure behavior |
| --- | --- | --- | --- |
| Observe | `observer/`, provider/calendar adapters and channel telemetry observe; no order authority | Source timestamps, receipt times, provenance, revisions and channel state | Missing, stale or unqualified inputs block readiness; connection health alone is insufficient |
| Propose | Bounded model selection and recorded/fixture runner integration; AI strategy design remains to integrate | Versioned intent, inputs, rationale and exact evidence references | Invalid/expired proposals are rejected; a model cannot grant itself execution rights |
| Reserve risk | `risk/`, `safety/`, bounded demo budget and coordinator | Deterministic sizing, account scope, reservation and policy/budget fingerprints | Reject or hold before admission; committed reservations are not replenished by retries/restarts |
| Execute | Fixed MQL5 EA validates native identity, authority, quote freshness and protection | Native attempt journal, request identity, broker response and protective state | Fail closed on bad identity/clock/freshness; uncertain submission is reconciled, never blindly resent |
| Reconcile | Native reconciliation and backend projection compare broker orders/deals/positions | Positive entry/exit witnesses, protected state, durable outbox/ACK and final closure | Flatness alone is not proof; unresolved ownership/protection halts entry and retains evidence |
| Explain | Implemented bounded conversational advisor reads scoped evidence, not broker credentials | Explanation tied to decisions, observations and versions | Uncertainty stays explicit; no inferred fill or invented success |
| Learn | Recorded experience/lessons and planned evaluation/promotion process | Outcome, cost, failure, candidate evaluation and promotion evidence | No automatic promotion from one success; fixed execution authority remains reviewed |

The earlier bounded demo required recovery; PR #25 later verified bounded same-session
closure without recovery. Neither proves the full fault matrix. Advisor engineering
exists, but the complete production learning loop remains unqualified. Read the
[status](../product/status.md) for the exact boundary.

## Code and data boundaries

- `src/fx_talanta/domain/` defines validated contracts. `storage/` provides account-bound
  PostgreSQL repositories, migrations and archive/restore. PAPER and LIVE use separate credentials.
- `src/fx_talanta/observer/`, calendar adapters and `provider_pipeline.py` collect inputs.
  `news_filter.py` applies point-in-time restrictions and coverage checks.
- `src/fx_talanta/demo/`, `connected_shadow/`, `integration/` and `execution_contracts/`
  implement distinct bounded, disabled, shadow and protocol paths; names do not imply LIVE authority.
- `mql5/` contains runtime EA programs and shared native libraries. `tests/native/`
  contains native checks and Tester-only programs, outside runtime deployment inputs.
- `src/fx_talanta/research/` contains synthetic demonstration records and observations.
  These ship for offline demos, but are not production strategy implementations.
- `tools/` contains development, fixture generation and qualification commands. It is
  not included in the runtime application image; the acceptance image includes it explicitly.

[Detailed specification](specification.md) · [Execution boundary](execution-boundary.md) ·
[ADR 001](../adr/001-fixed-ea-execution.md) · [Repository layout](repository-layout.md)
