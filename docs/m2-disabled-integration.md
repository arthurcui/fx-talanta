# M2 consolidated integration with trading disabled

This increment joins the typed request, operating-input, safety-state, authenticated
EA receipt and recovery paths. It does **not** complete M2D or authorize demo orders.
M0A–M0C, all M1 failures and provider gaps, the two-second entry ceiling and the
separate five-second observer ceiling remain unchanged. No sustained campaign was
started and neither broker terminal was changed for this increment.

## Implemented path and authority

| Step | Component and authority | Durable evidence / failure behavior |
|---|---|---|
| Operating inputs | `integration.inputs` resolves the five existing trusted-operator fact groups against the account scope and capture time | Content-addressed fact documents plus retained source bytes; missing, stale, future, mismatched or changed material holds/refuses. A hash proves integrity, not the truth or qualification of a source. |
| Request admission | `integration.coordinator.Coordinator` uses the original M2A envelope and shadow projection; no HTTP enqueue endpoint | Exact account/release/policy/snapshot binding, full original request in the journal, reconciled loss baseline and all persisted loss/owner/protection vetoes. No risk reservation or order is created. |
| Single writer | Existing account-wide `Authority`, including PostgreSQL authority when used with PostgreSQL | Active lease guards publication and new work. A replacement cannot silently adopt expired ownership. A new stream cannot bootstrap at a later authority epoch and thereby reset losses. |
| Native assessment | `mql5/integration/DisabledEA.mq5` and `DisabledKernel.mqh` join authenticated work, the loss replica and `SPreflight` | Native risk verdict and replicated loss state commit together before REPORT. The original observation continues ageing; a newer cache quote never refreshes it. The native dependency closure contains no broker send API. |
| Receipt / ACK | Original HMAC protocol and PostgreSQL shadow backend, wrapped by the coordinator | Backend independently recomputes native reason, age and proposed volume before a durable signed ACK. Same nonce/content and same receipt are idempotent; conflicts refuse. A database/unknown transport failure quarantines the coordinator. |
| Reconciliation | Trusted reconciler supplies a classified, account-scoped observation to `reconcile` | Event identity, retained evidence reference, observation and new loss state are atomic. Conflicting duplicates, backwards time and unknown cash flows refuse. A changed loss/protection state invalidates undelivered work. This is not a new broker-history adapter. |
| Protection | Backend `protect` and native `DgProtection` compose the existing protection reducer | Actual and proposed states stay distinct. An unsent repair/exit never becomes REPAIRING/EXITING. Unresolved protection vetoes entry; an exceeded exit deadline persists a sticky account hard halt. No SL/TP modification or exit is sent. |
| Restart / archive | Retained backend tip, native canonical journal tip, independent `integration.checkpoint` verifier and existing paired checkpoint contract | Missing files, torn records, changed bindings and retained-tip mismatch refuse. Receipt-only recovery can ingest already-persisted results after lease expiry for the unreplaced owner; it cannot publish/PULL new work. |

The M2B `FixedGateway` remains the separately tested, **Tester-only** execution
engine. This increment does not smuggle its dispatcher into a read-only EA.
Protection recommendations are advisory; their native helper is exercised by the
bounded fixture, not by managing a live position. Activation of the actual demo
execution adapter, broker reconciliation/protection timing and the demo-order
acceptance scenarios remain inside the explicit M2D gate. It would be incorrect
to describe the remaining gate as merely turning on Algo Trading.

## Operating evidence and readiness

Five groups remain mandatory: mandate, costs, baseline/exposure, session and
providers. Each `<canonical-json-sha256>.json` contains exactly:

- `schema: operating-facts/1`, `group`, full `account_scope`;
- integer `observed_at_ms` and `valid_until_ms`, with at most a 60-second interval;
- `values` containing exactly that group's existing fields;
- `sources`: SHA-256 references to retained `<sha256>.source` bytes.

These are trusted operator/reconciler artifacts. Models and HTTP callers cannot
supply them. Source bytes must exist and match, but the loader does **not** infer
provider coverage, broker timestamp mapping, actual fees or baseline truth from
those bytes. Existing qualification gaps still hold. There are no invented zero
costs or automatically approved news/calendar coverage.

A private-file readiness check is available without broker or database access:

```powershell
python -m fx_talanta.integration --capture <private-capture.json> --artifacts <private-directory> --references <private-references.json>
```

It prints only per-pair/side completeness and missing groups, and always reports
execution and demo acceptance as false. Captures, account identifiers, prices,
operating artifacts and credentials stay private. The CLI does not deploy an EA,
start a listener, publish work or fetch provider data.

For a bounded host, supply `Coordinator` with the existing account-bound
PostgreSQL stores and authority, and a verified clock source. The existing
`HostClock.read` can supply `clock_read`; authority's clock callback must return
the conservative upper bound. Its evidence expires: a constant low error bound
is only suitable for synthetic tests. The default unqualified clock error refuses
SYNC. A production continuously verified clock service is not claimed here.

The native host defaults off, requires a demo identity and terminal Algo Trading
off, refuses bootstrap into a non-flat account, uses private HTTPS and an explicit
journal bootstrap/checkpoint, and has a maximum 300-second lifetime. It inherits
the reviewed high-resolution clock model and its explicit physical-clock
assumptions. Its implementation is compiled in this increment; **no new live
native HTTPS deployment is claimed**. The successful existing-terminal handoff
belongs to PR #21's original source and evidence.

Backend channel status remains separate from stored quote age. Healthy transport
never implies a fresh quote, provider readiness or execution permission. The
coordinator additionally reports current persisted veto flags. M4 must retain
separate EA/Python/MCP channel and quote-latency indicators.

## Validation and evidence

See [the source-pinned report](evidence/m2-disabled-integration.json). It contains
actual native results, synthetic fixture artifacts and the isolated PostgreSQL
regression: **802 passed, zero skipped**. Native validation comprises 60 independently compared risk cases and
12 bootstrap, checkpoint, restart, ACK and suppressed-management checks. Both the
kernel harness and disabled EA compile with zero errors and warnings. Actual
native receipts are independently paired with committed backend journal records
in the public evidence tests.

The first compiler attempt reported two shadowing warnings and did not run; it
was corrected. A later successful run preceded checkpoint hardening; final source
was rebuilt and retested. The initial public-evidence test used the wrong
checkpoint attribute name; that test was corrected without changing native
results. Earlier private reports remain intact. No broker/provider acceptance
pass, fill, SL/TP action, live transport deployment or 24-hour result is inferred
from synthetic tests.

## M2 completion gate

Before an order-capable M2D acceptance run, require all of the following together:

1. Separately authorized existing demo binding and an explicit finite order/risk
   budget; qualified current clock, broker timestamp mapping, operating inputs
   and required M1/P0 gates. Preserve recorded gaps rather than substituting defaults.
2. Reviewed activation/integration of the fixed dispatcher with final native
   broker checks, durable submission/unknown-outcome handling, protection and
   complete broker reconciliation. The current Tester history bounds are not
   a resumable production-history cursor and must not be presented as one.
3. Actual demo evidence for fills/partials, SL rejection and bounded protection,
   lost responses, duplicate intents, terminal/backend/database restart/loss,
   stale quotes, wrong account, unexpected positions and closed-market exit.
4. Independent committed broker/journal reconstruction and an explicit verdict
   for every gate. Code merge, a working heartbeat or a short synthetic run cannot
   stand in for those results.

This is one consolidated disabled-integration PR. It is not a request for another
soak, a new broker account, automatic failover, or permission to execute orders.
