# M1A observer foundation

This increment implements the broker-neutral observation harness while P0 remains
open. **It does not connect to CMC or FOREX.com, complete M1A, or place orders.**
Only PAPER/SIMULATOR bindings and SCRIPTED_FIXTURE evidence are accepted, in Python
and PostgreSQL. Existing fixture identities are never relabeled as broker accounts.

Run after applying migrations:

```powershell
.venv\Scripts\fx-talanta migrate
.venv\Scripts\fx-talanta observer-demo
```

The demo persists four observations: healthy, disconnected/backoff, recovered,
and halted on a terminal build change. It reopens the observer between polls to
exercise durable state. Its dates, terminal paths, account, prices and build are
synthetic. Use `history --run-id <printed UUID>` to inspect the evidence.

## Implemented behavior

- Typed snapshots carry the account identity before and after collection,
  terminal/data paths, build, currency, source observation time, symbol metadata,
  quotes, completed M15/H1 bars, positions, pending orders and deal history with
  an explicit completeness flag and query window. The trade-item contract is a
  fixture abstraction; mapping actual broker order types, cash flows, fees and
  paginated history is pending adapter qualification.
- Reject a changed account/server/environment, path, build or currency. Reject
  future data and incomplete bars; flag missing data and stale quotes/bars.
  Stale market-closure quotes are not automatically treated as healthy. A qualified
  session calendar is still needed for that distinction.
- A spawned process isolates each collection. The timeout includes process startup;
  termination and bounded cleanup follow a missed deadline. Response size is capped
  at 1 MiB. Native diagnostic text is not copied into persisted failure records.
  This is a timeout boundary for trusted readers, not a credential sandbox.
- Persist failures, last success, exponential retry deadlines and terminal halts.
  The same run cannot restart with a changed binding/policy fingerprint. Backoff
  and halts survive restart and verified fixture archive/restore. A new synthetic
  run is independent; this is not a campaign risk or execution-halt controller.
- Share the M0C account-writer lock so an active observer prevents export and
  another writer. A staged restore cannot poll until verified and released.
  Runtime roles cannot mutate observation history or change its fixture provenance.
- No MetaTrader dependency is imported by the core. The reader callable accepts
  a binding and timestamp and returns a snapshot; no command/order interface exists.

`observer-demo` is a finite acceptance demonstration, not a background service or
an expiry reminder. There is no automatic account creation, rollover or broker
failover. CMC stays first and FOREX.com stays second.

## Remaining broker-connected M1A work

1. Provision a CMC Canada MT5 demo locally and confirm eligibility, Python access
   and data-use permission. Keep passwords out of chat and Git. Prefer investor
   credentials if supported; a method allowlist alone does not reduce credential
   privileges. Record the chosen server, account currency, terminal/data paths and
   tested terminal/Python/SDK build combination.
2. Add separate immutable PAPER/BROKER_DEMO provisioning, real-source provenance,
   archive support and explicit qualification evidence. The fixture-only checks
   in this increment must not simply be bypassed or relabeled.
3. Implement the Windows MT5 adapter with the documented read-method allowlist,
   account checks around collection, symbol mapping, complete/paged history and
   bounded native calls. Validate it on the provisioned terminal with zero orders.
4. Run the connected soak/reconnect tests, then qualify FOREX.com independently
   and implement the expiry tracking and observation handoff described in
   [demo rollover](demo-account-rollover.md). Account replacement remains subject
   to the dealer's permitted procedure; execution draining belongs to M2.

Calendar/news qualification and ingestion remain separate M1 work. See the
[handoff](m1-handoff.md) and [P0 evidence](p0-feasibility.md) for the remaining gates.
