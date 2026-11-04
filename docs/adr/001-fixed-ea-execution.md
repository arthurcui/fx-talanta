# ADR-001: Fixed EA owns connected broker mutations

Date: 2026-11-03. Status: proposed for design review; no runtime deployment.

## Context

At `main` `adc864017d29eca0b3dd1769164171a2a26b0fd9`, M0A–M0C provide
append-only records, account isolation, USD simulator risk/execution/recovery and
profile/archive parity. The Windows Python observer and native MCP calendar
adapter are read-only. Broker/provider campaigns concluded without full acceptance.
The previous architecture placed connected execution in a future Python gateway
and described an EA as optional. The accepted handoff instead requires a fixed
terminal-resident enforcement boundary while retaining the portable Python core.

## Decision

Adopt one reviewed, versioned MQL5 EA per dedicated account as the sole connected
broker mutator and final risk/protection authority. Python selects eligible
registered candidates; deterministic backend validation reserves a maximum
allowance and exposes expiring work for authenticated EA pull. The EA independently
checks trusted policy and fresh broker state, journals before sending, may narrow
or veto, reconciles and protects. Keep `gateway/offline.py` as the simulator oracle.
No runtime model receives broker mutation, shell, compilation or deployment tools.

The detailed [canonical architecture](../architecture/specification.md),
[boundary/runbook](../architecture/execution-boundary.md) and
[migration gates](../architecture/design-migration.md) define this decision. A local relay is
transport only. PostgreSQL locking alone cannot fence a disconnected terminal;
writer replacement requires old-host fencing and reconciliation.

## Alternatives and consequences

* A connected Python writer would reuse more simulator code, but is rejected as
  the final connected boundary. Python remains the reference and an independent
  backend veto; cross-language risk parity becomes a mandatory gate.
* Per-decision generated MQL5 or unrestricted MCP trading would broaden runtime
  authority and complicate reconciliation. Both are excluded. MCP remains a
  separately qualified read interface; MetaEditor belongs to isolated research.
* EA pull simplifies inbound terminal exposure, but synchronous network calls can
  delay protection. Bounded transport and measured callback/protection latency are
  mandatory. Failure to meet the budget requires separately isolated transport,
  not a relaxed protection gate.
* A durable local EA journal and backend mirror require explicit deduplication,
  recovery and version compatibility. No broker-side exactly-once guarantee is
  claimed; unknown sends retain risk and cannot be blindly repeated.

## Acceptance and scope

This PR changes documentation only. Runtime acceptance requires the staged M2
contract, native, shadow and qualified-demo gates. Existing failures remain
failures; the two-second entry restriction and original PAPER risk mandate remain.
No new deployment, campaign or broker execution is authorized by this ADR.
