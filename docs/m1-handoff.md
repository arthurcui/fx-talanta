# M1 implementation handoff

## Current status and execution handoff (2026-11-03)

The broker and provider campaigns are concluded without sustained acceptance; see
[broker results](broker-campaign-conclusion.md) and [provider results](provider-campaign-conclusion.md).
Manual BLS import/reminders and optional native MCP calendar shadow import now
exist. USD/EUR/JPY category delivery, rights, timestamps and recovery qualification
remain open. No new campaign is authorized here. Preserve old evidence and freeze
any future active collector checkout while developing elsewhere.

The revised [architecture](architecture-plan.md) retains M1 as read-only. Python
will not become a connected order writer: a fixed reviewed EA is the planned sole
broker mutator, reached via backend validation/reservation and EA-initiated pull.
[M2's first slice](m2-handoff.md) is offline-only; native/shadow/demo stages remain
separate, with P0/M1 prerequisites before connected execution. The retired MQL5
calendar service and automatic browser downloader remain retired.


Status: M0C and the MT5 adapter are merged; connected CMC demo observation works.
The [CMC read-only milestone](cmc-readonly.md) tracks the runner and remaining
sustained acceptance. Broader [P0 qualification](p0-feasibility.md) remains open. Preserve the
MT5-first mandate unless a different interface is explicitly chosen.

The [M1A observer foundation](observer-foundation.md) now provides synthetic
snapshot collection, process deadlines, durable recovery and archive tests.
Synthetic evidence alone does not satisfy the connected broker acceptance gates below.
The [MT5 adapter increment](mt5-observer.md) adds Windows collection,
explicit demo provisioning and archive support; connected sustained qualification remains open.

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
restore of the new observed evidence and account binding. Explicit broker-demo
archive support, migration and wrong-account tests are now implemented alongside
the original fixture archive contract.

Produce an evidence bundle of terminal/account capabilities, data-health behavior,
source rights references and unresolved constraints. Keep broker-demo observations
distinct from replay and synthetic results. Complete M1's read-only exit gate
before M2 introduces demo execution or qualifies protection flows.
