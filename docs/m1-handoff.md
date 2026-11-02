# M1 implementation handoff

Status: proposed work breakdown after the [P0 qualification](p0-feasibility.md).
M0C is merged; no external broker observation is implemented yet. Preserve the
MT5-first mandate unless a different interface is explicitly chosen.

The [M1A observer foundation](observer-foundation.md) now provides synthetic
snapshot collection, process deadlines, durable recovery and archive tests.
It does not satisfy the connected broker acceptance gates below.

Broker order is **CMC Markets Canada first, FOREX.com Canada second**. Implement
the shared read-only MT5 worker against CMC, then qualify FOREX.com independently.
Each broker has its own account binding, database/role, terminal paths and worker.
The secondary is a comparison deployment, not automatic failover for CMC orders.
Account replacement follows [demo rollover](demo-account-rollover.md): M1 provides
expiry tracking and observation handoff; M2 adds the trading drain/reconciliation
steps. No runtime rollover controller exists yet.

## M1A: read-only terminal observation

Build a separate Windows worker with pinned Python/MetaTrader5 versions and one
configured demo identity. Keep MT5 dependencies out of the native/Linux core and
out of the M0 fixture databases. Introduce a deliberately provisioned
PAPER/BROKER_DEMO database binding; never rewrite the existing immutable
PAPER/SIMULATOR binding or relabel simulator records as broker evidence.

Provisioning inputs: chosen Canadian dealer, demo server/login, account currency,
dedicated terminal executable/data paths and confirmed observation permissions.
Keep passwords in local secret storage, never in configuration committed to Git.
Prefer provider-supported read-only credentials where available; a Python method
allowlist alone is not a broker credential privilege boundary.

Expose only terminal/account information, symbol discovery, quotes/completed bars,
positions, pending orders and execution history. No `order_send` access, automated
login switching, or order-modification route belongs in M1. Observe and record
account changes; reject mismatches rather than adopting the new identity.

Supervise blocking native calls from a separate process with bounded deadlines,
restart backoff, terminal-build checks and a finite reconnection state machine.
Persist exact observations and failure incidents with account/environment,
terminal build, source timestamp, UTC observation time and acquisition provenance.

Acceptance: fresh demo observations, account/symbol capability snapshot, wrong
server/login/mode rejection, blocked-call recovery, build-change handling,
terminal reboot/reconnect, stale/absent ticks and retained history. Demonstrate
that all exercised paths submit **zero orders**.

## M1B: calendar and news observation

Enable only qualified providers and retained fields. Keep a calendar schema
separate from unscheduled news. Preserve original publisher timestamps, timezone
evidence, first observation, revisions/corrections, and availability at decision
cutoffs. Retain the original event when a correction arrives.

Persist feed health independently of articles: silence, failed transport,
authentication, rate limiting, unexpected schema and missing coverage are distinct
conditions. A successful empty response is not proof that the feed is current.
Keep raw payload storage bounded and within the agreed rights; external evidence
files, if introduced, must extend the M0C backup contract before use.

Acceptance: duplicate events, reordered/late revisions, UTC/DST conversion,
missing currency mappings, null values, source outages, quota errors and historical
cutoff queries. Search remains bounded to approved sources and explicit budgets.
Source content is untrusted data and cannot change risk policy or execute tools.

## M1C: end-to-end observation qualification

Run the native Windows observer beside the portable core and PostgreSQL. Confirm
account isolation, secret separation and reconnect behavior. Exercise export and
restore of the new observed evidence and account binding; M0C's archive deliberately
supports fixture identities only, so broker-demo support needs an explicit schema/
archive extension with migration and wrong-account tests.

Produce an evidence bundle of terminal/account capabilities, data-health behavior,
source rights references and unresolved constraints. Keep broker-demo observations
distinct from replay and synthetic results. Complete M1's read-only exit gate
before M2 introduces demo execution or qualifies protection flows.
