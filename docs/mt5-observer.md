# Read-only MT5 adapter

## Current design boundary

This Python adapter stays read-only. The proposed [fixed EA boundary](ea-execution-boundary.md)
is the sole future connected mutation path; do not add order functions to this
observer or use its five-second readiness ceiling as the two-second entry gate.
The [concluded broker results](broker-campaign-conclusion.md) supersede any
earlier progress statement as acceptance status. No run is resumed by these
reproduction instructions; old evidence, terminal bindings and campaign sources
remain preserved.


Implementation is available. On 2026-11-02 a connected CMC demo observation returned
`HEALTHY / CURRENT` after explicit session clock qualification. The account reported
CAD, hedging mode and build 6295; the selected symbols were EURUSD.a and USDJPY.a.
Three separate CLI processes on the same durable run recorded `HEALTHY / CURRENT`,
`DEGRADED / STALE_TICKS`, then `HEALTHY / CURRENT`, with the five-second tick-age
threshold unchanged and no orders submitted. This verifies recovery from one stale
sample, not a sustained soak or a terminal-disconnect exercise.
Synthetic tests cover failure paths, but sustained connected qualification remains
pending. An installed/logged-in terminal is not proof of Python/data permission.

The Windows worker imports the optional official SDK inside its supervised child.
The core, storage and Linux tests have no MT5 dependency. No login, password,
`order_send`, order modification, market subscription or `symbol_select` call is
available through the adapter. Select required symbols manually in Market Watch.
`initialize` can start the configured terminal and uses its remembered account;
the adapter does not supply credentials or switch accounts.

## Local preparation

Copy `configs/mt5-demo.example.json` into ignored `.local/`. Replace the placeholder
login/data path and verify **all** identity fields, currency, company, account
margin mode, terminal build and exact symbol names. USD in the example is not an
assertion about your account. Margin mode 2 means hedging; 0 means retail netting.
Keep passwords out of binding files and Git. Investor credentials are preferred
where the dealer supports them; a method allowlist is not a credential boundary.

Leave `permissions_confirmed` false and `permission_evidence` null until applicable
dealer terms/support evidence confirms Python access and private retention/use of
the collected data. The reference is an operator attestation, not automatic legal
verification. The CLI rejects unqualified observation **before** opening a database
or importing the SDK. Do not change the flag merely to get past this check.

Use a dedicated local environment file with a unique `FX_DB_NAMESPACE` (for example
`fx_cmc_g1`), fresh PAPER/LIVE writer passwords, and the existing local PostgreSQL
administrator connection. Never reuse fixture or another broker's writer secrets.
The default `fx` namespace is rejected for demo provisioning. Provisioning refuses
any existing database whose immutable identity differs, before applying migrations.
Each pair contains the configured PAPER/BROKER_DEMO account and a disabled LIVE
fixture; this does not provision a real live account.

After configuration and qualification, install the optional SDK on Windows:

```powershell
.venv\Scripts\python -m pip install -c requirements.lock -c requirements-mt5.lock -e '.[dev,mt5]'
.venv\Scripts\fx-talanta --env-file .local/cmc.env --binding .local/cmc.json migrate
.venv\Scripts\fx-talanta --env-file .local/cmc.env --binding .local/cmc.json observe --run-id <UUID>
```

`observe` collects once and exits. The [CMC runner](cmc-readonly.md) provides bounded
scheduled polling, health reporting and restart recovery with `observe-run`.
Reuse the same UUID for subsequent polls/restarts
to retain backoff/halts. No Windows service or rollover controller is installed.
The binding fingerprint includes qualification evidence, SDK version and policy.
Changing it requires a deliberately new observation run; it cannot clear an old
run's halt. This is not an execution-risk campaign reset mechanism.

The optional worker lock targets Windows CPython 3.14.7, SDK 5.0.6231 and NumPy
2.5.4. Installation/import were verified without calling `initialize`; this does
not qualify the broker connection. Linux/core installs do not request this extra.

## Collection and failure semantics

### Broker timestamp qualification

The default SDK timestamp convention remains UTC. Some server feeds expose a
server wall clock encoded as an epoch instead. On 2026-11-02, the CMC demo's
EURUSD.a and USDJPY.a ticks were approximately 7,200 seconds ahead of independently
checked UTC; bars showed the same shift. This is observed evidence for that session,
not a confirmed annual CMC timezone or DST rule.
A separate same-day read-only history probe found one deal record: querying within
one second of its raw SDK timestamp returned it, while querying around that timestamp
minus two hours returned zero. This corroborates the server-clock query convention
for deal history; nonempty order-history behavior remains unverified on this account.

For such a feed, explicitly configure `sdk_time_offset_seconds` (server minus UTC),
`time_policy_from`, `time_policy_until` (UTC, start inclusive/end exclusive), and
`time_policy_evidence`. A nonzero offset requires all three qualification fields.
The interval may be at most 48 hours and must cover the requested history window,
every returned event/bar opening and the completed observation. Outside that interval
the reader halts with `INVALID_DATA`; older positions/orders also fail closed until
their timestamp periods are qualified. This short-window mapping does not support
history spanning a DST transition.

The reader subtracts the configured offset from tick, bar, position, order and deal
timestamps (including order completion), and adds it to SDK history-query endpoints.
Snapshot metadata retains the offset, interval and evidence so normalized values
can be traced back to their SDK time convention. System observation timestamps stay
UTC. Future/stale-data checks remain active; no offset is inferred automatically.
An offset change requires renewed qualification and a new binding/run, preserving
previous halts. Do not extend a policy across an unverified DST change.

Permission status is separate from clock qualification. The operator authorized the
local CMC check on an assumption of permission; that assumption was recorded locally
and is not represented as broker confirmation. Private account details and observations
remain outside Git.

### Snapshot checks

- Check login, exact server, demo trade mode, company, currency, margin mode,
  terminal/data paths, build and SDK version. Check identity before collection,
  between symbol/history batches and after collection. A mismatch halts the run.
- Collect symbol precision/volume constraints, bid/ask, two closed M15 and H1 bars,
  positions, pending orders and bounded order/deal history. Preserve trade types,
  IDs, initial/current volume, fees, P&L, cashflow deal types and protection prices.
  This is an observation schema, not a complete execution-capability qualification.
- Query 1–24 hours of history in hourly windows; deduplicate inclusive boundaries
  and compare counts before/after. None, truncation, conflicting duplicates or more
  than 2,000 items fail closed. A successful empty response is distinct from None.
  Completeness refers only to the requested window. This is not a full account
  history export, and dealer-side retention gaps cannot be ruled out by counts.
- Convert SDK floats through decimal strings and epoch timestamps to UTC. Metadata,
  account balances and positions are sampled through separate calls, not an atomic
  broker snapshot. Use a dedicated terminal without manual account switching.
- The parent process enforces call deadlines and terminates hung children, retains
  sanitized failures, exponential retry deadlines and halts. Stop after the bounded
  failure budget; stale market-closure quotes require operator/session-calendar
  interpretation, not automatic approval of new entries.

No real broker orders are enabled. FOREX.com uses its own binding, namespace,
writer secrets and terminal/data paths; it is not an automatic failover account.

## Storage and archive

Migration 006 admits BROKER_OBSERVATION only for PAPER/BROKER_DEMO observation
records. Fixture provenance cannot enter demo storage, or vice versa. Runtime SQL
cannot rewrite identities/history; the offline trading journal rejects demo accounts.

All `export`, `restore` and `verify-restore` operations for a demo pair require the
same explicit `--binding`. Their archive format differs from fixture archives.
The expected identity comes from the caller, never from untrusted archive contents.
An archive from a different login/server is rejected before staging. Archive contents
include account IDs and market/account data: keep them private and encrypt backups
as required by the applicable rights. Archives do not include passwords.

```powershell
.venv\Scripts\fx-talanta --env-file .local/cmc.env --binding .local/cmc.json export .local/cmc.fxbackup
```

Stop the source observer first. Restore into an empty, independently provisioned
destination with the same identity and schema version. Verify with the same binding
and `verify-restore <archive> --source-retired` only after retiring the source writer.
Observation halts survive restore. Retain the matching application revision for
older archives: cross-schema restore remains deliberately unsupported.

## Acceptance still needed

Actual CMC SDK/build qualification, currency/symbol verification, read-only credential
capabilities, connected zero-order soak/reconnect tests, full initial history coverage,
provider rights, session-calendar handling and independently qualified FOREX.com
expiry/handoff are outstanding. SDK 5.0.6231 is a candidate pin, not proof that it is
qualified with terminal build 6295. No connected run was performed for this increment.

Sources: [official Python interface](https://www.mql5.com/en/docs/python_metatrader5),
[initialize](https://www.mql5.com/en/docs/python_metatrader5/mt5initialize_py),
[account information](https://www.mql5.com/en/docs/python_metatrader5/mt5accountinfo_py),
[closed bars by position](https://www.mql5.com/en/docs/python_metatrader5/mt5copyratesfrompos_py),
[deal history](https://www.mql5.com/en/docs/python_metatrader5/mt5historydealsget_py),
[SDK release](https://pypi.org/project/MetaTrader5/5.0.6231/).
