# M0A: records and account contracts

Source: [FX-Talanta Architecture and Implementation Plan, baseline v0.3](https://chatgpt.com/space/page_33b155951df08191a6bd0d477c965002).
This increment implements only the M0A handoff. The source plan is retained in
`architecture-plan.md` for subsequent increments.

## Storage and authority

Each PostgreSQL database has one immutable account binding containing environment,
broker, server, login and venue. The `fx_paper_writer` and `fx_live_writer` roles
can connect only to their own application database. They can select records and
insert record columns, but cannot update, delete, truncate, change the binding,
create schema objects, assume owner/other-account roles or grant themselves
privileges. Non-login owner roles own the schemas; privileged bootstrap is a
separate operation. Superusers and migration owners remain administrative trust
boundaries. This is permission-enforced append-only history, not cryptographic
protection against database administrators.

The development CLI loads `.env` for setup and testing. It is not a production
worker or authentication service. Repositories receive only an account-specific
DSN. Separate process identities and runtime secret distribution are later
deployment work. Credentials are local configuration and are never packaged as
application resources. No broker/model credentials are used.

`fx.records` is a common journal for the discriminated typed record bodies. The
same repository persists events and experience cases atomically. `sequence` orders
inserts within the account; sequence gaps after rollback are expected and are not
lost committed events. Correlation IDs group related records. Each record ID is
unique within its database/account. Repeated insertion of identical content is
idempotent, including concurrent delivery; different content for that ID fails.

References are materialized into `fx.record_links` by a fixed-search-path database
trigger in the source record's transaction. Foreign keys enforce existence and
trigger checks enforce relation types and temporal availability. Runtime roles
cannot write the links table directly. Both the repository and database check
the account binding, so changing a payload or constructing a new repository with
the wrong account cannot route a record into the other database.

## Corrections, evidence and outcomes

Corrections append a new record with `supersedes` pointing to the original. The
original stays queryable. A correction must have the same kind and a later or
equal time, and there is only one direct successor per record. Command corrections
may alter status/outcome but cannot alter actor, account, conversation/message,
request, action, position, expiry or expected state version. News corrections
retain source/item identity and increase the revision number.

News records distinguish publication, optional source update, first observation,
ingestion and availability. Decisions link exact versions, not an implicit
"latest" record. Links to late-observed news fail even if its publication time
is old. Source health is independently typed. `news_available(cutoff)` returns
all historically available versions so a consumer cannot silently replace an
original with a later correction.

Operational result, policy compliance and economic outcome are separate fields.
An unknown execution remains unknown until a subsequent observation provides
evidence. A discovered open fill does not establish realized profit. P&L and
costs use finite Decimal values; floats and ambiguous local timestamps fail
validation. Records use UTC, preserving the source timezone separately for news.

## Conversation contract

Messages retain actor, authentication assertion, language, conversation/message
IDs, account and interpretation. M0A's authentication assertion is a test fixture,
not proof from a real identity provider. Exact English/Chinese pause strings are
the only allowlisted mutation-intent fixtures. Read-only, ambiguous, negated,
quoted, hypothetical, wrong-account and unauthenticated inputs record no command.

Commands retain original-message references, authenticated actor, explicit account,
request ID, expiry, expected state version and status/outcome. Database checks
require exactly one matching authenticated explicit-command message. Unique
request/message indexes prevent multiple original commands from one message.
Replaying the same fixture preserves its original request identity. The demo
stops at INTERPRETED and has no broker mutation method.

## Migration discipline

SQL files are applied in filename order in a transaction per account. Applied
version/checksum pairs are durable; a changed applied file is rejected. Advisory
locks serialize setup. `001_records.sql` creates the journal. The follow-up
`002_correction_validation.sql` corrects JSON operator grouping in the correction
validator without rewriting the first migration or discarding recorded fixtures.

## Interfaces for later increments

- M0B extends `BrokerAdapter` with typed execution requests and reconciled snapshots,
  and implements deterministic sizing, atomic reservations and order/recovery state
  transitions. `FixtureBroker.observe()` currently plays recorded observations;
  it does not simulate fills or implement a reconciliation algorithm.
- M0B can persist transitions and experience changes through `append_batch`, using
  immutable command identities and exact evidence references. Enforcing transition
  legality and broker ownership is M0B work; M0A records typed observations.
- M0C packages the same application and migrations, supplies isolated PostgreSQL
  services to Codex tasks, tests image/native parity, and implements export/restore.
- M1 adds qualified news adapters and broker observation. M4/M5 add real model,
  owner authentication and conversation handling. Scripted raw response/message
  capture currently accepts synthetic inputs only; external adapters must redact
  secrets and enforce retention rights before recording real provider content.
- Promotion evidence is a contract only. `activation_enabled` is fixed false,
  the database binding forbids enabling execution, and no release controller runs.

## Acceptance evidence

Run `python -m pytest --integration -q` from the installed virtual environment.
The tests use actual PostgreSQL credentials and role boundaries, and read committed
history in a new Python process. The manual container-restart check in the README
also verifies the named-volume history survives a PostgreSQL service restart.
This establishes the M0A record foundation, not the M0B trading loop or M0C
deployment qualification.
