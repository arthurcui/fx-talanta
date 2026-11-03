# M2A offline protocol implementation

M2A supplies additive Python contracts, a fixture inbox/reconciliation model,
USD/CAD reference calculations and a fixture-only MQL5 script. It does not change
the M0A–M0C record kinds, database migrations, USD simulator or governor.
PR #16's read-only comparison and all failed/stopped M1 evidence remain intact.

## Contract and authority

`src/fx_talanta/domain/ea_protocol.py` defines the five `ea-protocol/1` messages.
`Envelope` discriminates by `kind`, validates the full schema and verifies its
SHA-256 payload digest. The digest detects inconsistency; it is **not authentication**.

| Message | Meaning and limit |
| --- | --- |
| DecisionIntent | Untrusted strategy proposal with evidence cutoff; never admitted by the execution inbox |
| ExecutionRequest | Backend allowance bounded by account, release, policy, reservation, symbol, risk, volume and expiry; EA must independently validate before execution |
| ExecutionAck | Receipt or broker acceptance; has no fill quantity and cannot establish execution |
| ExecutionState | Versioned fill/open/protected quantities with broker provenance; confirmed states require positive evidence |
| ReconciliationResult | Cumulative filled/released quantities with request hash, predecessor and broker evidence; UNKNOWN cannot release an unresolved remainder |

Wire financial quantities are finite decimal strings, never JSON numbers.
Python also accepts Decimal for internal construction. All timestamps must have
an offset and normalize to UTC. Canonical serialization uses the validated model's
JSON representation, including defaults/nulls, sorted object keys, no whitespace,
ASCII JSON escapes, lowercase UUIDs and SHA-256. Decimal strings use fixed notation,
strip insignificant fractional zeros and normalize negative zero. UTC serialization
uses `Z` and includes microseconds when nonzero. The digest covers the payload only.
Unknown versions/fields, naive timestamps and malformed quantities raise schema
validation errors before a request can enter the reference inbox.

The [canonical request example](../tests/fixtures/ea_protocol/request.json) uses only
synthetic account and price data. It carries no real credentials or broker identity.

## Replay, uncertainty and reservations

`ReferenceInbox` is a synchronous in-memory reference model with a JSON checkpoint;
it is **not** durable storage or a dispatch service. It validates pinned identity,
release/policy, sequence, a supplied clock-uncertainty bound (0–100ms in this fixture),
TTL and management state version. It rejects proposals. ACCEPTED means recorded
by this reference model, with no authorization to trade. Production authentication,
capability negotiation, database transactions, crash-safe writes and risk checks
remain M2B/M2C responsibilities.

For an admitted sequence, both acceptance and terminal validation rejection are
remembered. Same ID and canonical hash returns the original outcome, including
after restart or expiry, without a new reservation. A rejected request cannot later
become accepted through replay. Different payload under the same ID conflicts.
Untrusted account/version and sequence gaps never advance the account stream.
A reservation already assigned to accepted work cannot be assigned again.

| Stable reference reason | Effect |
| --- | --- |
| ACCOUNT_MISMATCH / RELEASE_MISMATCH / POLICY_MISMATCH | Reject mismatched scope/authority |
| HASH_CONFLICT / SEQUENCE_GAP / RESERVATION_CONFLICT | Reject identity, ordering or allocation conflict |
| EXPIRED / FUTURE_MESSAGE / CLOCK_UNCERTAIN | Reject unsafe lifetime evaluation; replay never extends expiry |
| STATE_MISMATCH / NOT_OWNED / UNKNOWN_OUTCOME | No stale close, adoption or conflicting mutation |
| LOSS_BLOCK / HEALTH_BLOCK / STALE_QUOTE | Block entry; clearing owner pause does not clear other gates |
| UNSUPPORTED | Wrong message type at the inbox; schema-level unknown versions also fail validation |

`Allocation` checks immutable scope, predecessor, sequence, nonregression and
quantity conservation. A 0.09-lot allowance with 0.03 confirmed filled retains
0.06 reserved; it does not count 0.03 plus the original 0.09. Replayed evidence is
idempotent. Unknown outcomes retain the unresolved amount. Only a positive,
consistent reconciliation can release it. This reference tracks quantity allocation,
not position marking or the complete production loss ledger.

## Reference vectors and native boundary

[Risk cases](../tests/fixtures/ea_protocol/risk.json) contain hand-derived expected
outputs for BUY EURUSD/USDJPY in USD and CAD, conversion failures, downward lot
rounding, costs, gross/currency/margin/risk reservations, daily loss, persistent
halt and unknown cash flows. USD outputs are checked against the unchanged M0B
governor. The CAD cases scale capital and costs at 1.35 CAD per USD, producing the
same lots while changing monetary amounts. For EURUSD, 0.09 lots × 233 USD risk
per lot = 20.97 USD; the CAD equivalent is 28.3095 CAD.

`reference.py` is a deliberately bounded BUY-only calculator with fixed M0B default
fractions and synthetic rates. It receives persisted loss baseline inputs rather
than resetting them. It does not implement production conversion sources,
cash-flow reconciliation, SELL/native parity or the full EA safety engine.
Amounts are reported to six decimals after exact Decimal sizing.

[Replay cases](../tests/fixtures/ea_protocol/replay.json) drive both the actual Python
envelope inbox tests and a small native replay reference. The native export carries
symbolic digest tokens, not real authenticated messages. The MQL5 harness reads
normalized TSV rows and calculates results without reading expected outputs.
It does not parse the full wire JSON or compute its canonical digest. Its arithmetic
uses MQL5 double and has not established financial boundary parity.

Native compiler and Tester: **NOT RUN**. Native parity: **NOT QUALIFIED**.
Full JSON/hash validation, decimal boundary analysis, production state persistence
and independently produced native output belong to the later M2B/M2C validation.
No native binary was produced, attached or deployed by M2A.

## Offline invocation and artifacts

From the checkout, using its existing Python dependencies:

```powershell
$env:PYTHONPATH = "$PWD\src"
python scripts/m2a_reference.py --output .local/m2a-reference
python -m pytest tests/test_ea_protocol.py tests/test_ea_reference.py -q
```

The runner writes `Envelope.schema.json`, `ChannelTelemetry.schema.json`,
`risk.tsv`, `replay.tsv` and `report.json`. The report records expected/actual results
and SHA-256 hashes of sources and fixtures. The
[committed Python evidence](evidence/m2a-reference-20261103.json) contains the actual
27-case reference result, not a synthetic native pass.

For a future separately reviewed native exercise, the fixture script
`mql5/offline/ProtocolReference.mq5` reads `risk.tsv` or `replay.tsv` from its own
file sandbox, selected by `RunRisk`. It writes `risk-native.tsv` or
`replay-native.tsv`. Preserve compiler logs, source/fixture hashes and raw native
outputs before comparing every case with the JSON expected values. Require exact
volume/reason agreement and reviewed money precision; do not infer parity from a
source scan. File handling follows the official
[FileOpen](https://www.mql5.com/en/docs/files/fileopen) and
[FileReadString](https://www.mql5.com/en/docs/files/filereadstring) interfaces.
This document does not authorize invoking that script in either broker terminal.

## UI telemetry milestone

`ChannelTelemetry` is scoped by account, symbol, channel (EA / PYTHON_PACKAGE /
MCP) and capability (quotes, reconciliation, news or calendar). Configuration,
disabled/connecting/healthy/degraded/disconnected/error status is explicit.
Heartbeat, last success/error, original tick time and quote receipt are separate.
Latency percentiles require a window and nonzero sample count; unavailable data
stays null. Quote age always derives from the original tick, even if a heartbeat
just arrived. The entry ceiling remains **two seconds**; no telemetry grants
execution authority or rewrites the five-second observation ceiling.

The [channel fixtures](../tests/fixtures/ea_protocol/channels.json) deliberately
include a healthy transport carrying a 30-second-old quote and unavailable metrics
for disabled/unconfigured channels. These are synthetic examples, not new broker
measurements. M2B adds producers, M2C validates failures/recovery, M4 exposes
authenticated reads and M5 implements the indicators in the UI.

## Validation and remaining gates

The local regression suite passed 381 tests, with 119 PostgreSQL integration tests
skipped locally to avoid touching broker databases. The PR's existing CI checks run
those integrations in isolated services and build both containers. The test image
includes only the new MQL5 source for static checks; the runtime image has no new
terminal/deployment path.

M2A's Python/source deliverables are implemented. Native parity, M2B execution,
M2C deterministic safety and M2D connected acceptance remain pending. M1 failures
and provider coverage gaps are neither erased nor reclassified by this increment.
