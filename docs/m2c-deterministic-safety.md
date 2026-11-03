# M2C deterministic safety

PR #18 merged as `f98767c4cbf4e38b66cad3a50876a0514634e1dc`. This change adds
offline safety components and actual native evidence on that foundation. It
does not enable broker execution, install an EA on CMC/FOREX, or start a campaign.
The M0 USD simulator, M2A contracts and M2B Tester gateway remain unchanged.

## Implemented boundary

`safety/preflight.py` binds an M2A entry request to its account, release, policy,
snapshot hash and expiry, composes persisted loss/owner restrictions, ages the
original quote/conversion observation to the decision instant, and compares the
independent native verdict. Every result has `send_enabled=false`. It rejects
connected venues. `mql5/safety/Preflight.mqh` independently composes the native
loss state, narrows the supplied request allowance and rechecks elapsed age.

The safety libraries contain no broker send function. The native entry point
refuses non-Tester execution. Production work pull/upload, real broker snapshot
construction and integration with a connected order sender are not supplied by
this PR. The old M2B synthetic Tester sender is not relabeled as a qualified
M2C-connected gateway.

| Component | Responsibility / authority | Failure behavior |
| --- | --- | --- |
| Python `safety/risk.py`, native `Risk.mqh` | Independently calculate USD/CAD BUY/SELL bounds for EURUSD/USDJPY from validated observations and a pinned mandate | Reject missing/stale conversion, clock uncertainty, quote age, required-input health, blackout/session, position/risk/cost/margin/currency breaches; never increase an allowance |
| `exposure.py`, `Exposure.mqh` | Current-liquidation-to-stop loss plus incremental exit costs, actual gross/margin/currency legs, and unresolved unfilled reservations | Unprotected, unknown and external exposure block entry; mixed accounts, duplicate records or expanded rounded allocations reject |
| `control.py`, `Control.mqh` | Unitized cash-flow-adjusted NAV, daily loss, state precedence, bounded protection recommendations | Deposits/restarts cannot erase a halt; unknown repair/close is not repeated; missing storage prevents mutation; deadline or clock failure escalates |
| `journal.py`, native `StateStore.mqh` | Durable account-scoped loss/event replicas, explicit bootstrap, persistence and fencing checks | Missing journal is not a new baseline; conflicting scope, sequence, content or replica checkpoint blocks readiness |
| `Fence.mqh` and Python journal authentication | HMAC-SHA256 parity, scoped identities/sequences/expiries and bounded writer leases | Bad signature, stale writer, expired lease, unavailable storage or unreconciled startup rejects |

A partial fill counts actual open exposure plus the unfilled remainder, with one
slot for that reservation. Confirmed cancellation releases only the remainder.
Unknown outcomes retain it. Every broker position must be included, including
external exposure, although external positions gain no management authority.
The aggregation functions require fresh reconciled data; they do not establish
that a real broker snapshot is complete or fresh.

## Policy, units and numerical scope

The architecture's mandate is unchanged: 0.25% per trade, 0.50% aggregate risk,
two positions/one per symbol, 1% daily loss, 5% persistent drawdown, 2x gross,
1x absolute currency exposure and 20% margin/equity. Eligible capital is the
lower of current equity and configured allocation. Entry costs reduce capacity.
The larger formula, broker-profit and tick-value loss estimate wins; margin is
a supplied broker estimate, not a hardcoded leverage assumption. Commission,
slippage and financing have explicit conversion. CAD commission or USD-to-CAD
commission is supported; other conversion routes reject until specified.

Financial wire values are decimal strings. Money is conservatively rounded to
one account-currency micro-unit with a 0.1 micro-unit arithmetic guard; volume
rounds down to its step. Intermediate money is limited to 100 million. The
bounded search visits at most 4,096 lot-grid candidates, then returns HOLD with
`COMPUTE_BUDGET`. A refusal is never permission to round up or enlarge capital.
These bounds are implementation limits, not broker calibration.

**Two seconds remains the entry ceiling.** The entire quote-age interval,
including clock uncertainty and time since capture, must fit within it. A
heartbeat cannot renew a quote. Conversion uses the same bound. Clock error
above 100 ms blocks the fixture preflight; a claimed bound still needs actual
clock evidence before any connected qualification.

Loss rollover requires reconciled **00:00 UTC boundary equity**; the first late
poll cannot invent a new day's baseline. Classified flows require pre-flow
equity and durable deduplication by their source event ID. Owner pause is
independent of loss/unknown/protection/startup/degraded states. Precedence never
allows a less restrictive state to clear a more restrictive one.

Protection recommendations use caller-supplied, predeclared deadlines. The
native tests use synthetic 1,000/2,000 ms repair/exit deadlines, not deployment
defaults. Persist the next state before any future action. Confirmed rejected
repair can recommend one controlled exit; rejected exit escalates. An uncertain
action stays unresolved until positive evidence; restarting cannot restart its
timer. Rebooted deadlines require reconciliation, not a new grace period.

The SQLite journal is a **local acceptance reference**, not the production
PostgreSQL authority or an HTTPS server. HMAC does not replace TLS. Native
file exclusivity proves one local writer, not multi-host fencing. The backend
requires an independently retained peer checkpoint to reject a valid-prefix
restore. Coordinated restores, actual lease distribution, stable epoch authority,
secret provisioning and authenticated production delivery remain deployment
gates. Do not obtain a restore's expected checkpoint from the restored file itself.

## Actual validation

[Machine-readable native evidence](evidence/m2c-native-20261103.json) records:

- **56/56** independently computed risk cases matching Python, MQL5 and reviewed
  expected reason/volume; accepted risk, gross and margin match exactly.
- **52/52 native assertions** for partial exposure, loss/deposit/UTC behavior,
  precedence, protection faults, fencing, persistence, missing-store refusal,
  wrong-account refusal and prevention of clearing a persisted hard halt.
- Matching native/Python HMAC; MetaEditor/terminal build **6295**, final compile
  **zero errors and zero warnings**.
- Worst native calculation **1,820 microseconds**, under the **20,000 microsecond**
  predeclared offline computation budget. This is one pass per synthetic input;
  it excludes network, broker, terminal scheduling and transport/flush latency.

The math Tester used a separate directory, no copied account profile, local
agents only, remote/cloud agents disabled, and no order API. No new broker
account was needed. The existing CMC and FOREX.com accounts were not changed.
Earlier compiler attempts and intermediate results remain in the private native
archive. A Python cash-flow/drawdown boundary regression was fixed and rerun;
the final evidence is tied to the final sources, executable, input and logs.
The final portable regression run passed **488 tests** with **119 PostgreSQL
integration tests skipped locally**. Ruff checks and formatting passed. The
pull-request CI separately runs the PostgreSQL, container and profile checks.

Reproduce portable checks with `pytest tests/test_m2c_safety.py`. Export only
inputs with `python scripts/m2c_evidence.py --export <private>/m2c-risk.tsv`.
Compile `mql5/safety/NativeTests.mq5` with its adjacent headers and the preserved
M2B Core/Wire headers. Run it in an isolated **Model=3** math Tester. Compare
actual output with `--native <m2c-native.tsv> --hmac <m2c-hmac.txt> --output <report>`.
Expected answers are not exported to the native risk calculator. The source
hash check in portable CI rejects evidence made stale by a source change.

## Exit gate status

The offline implementation and bounded evidence above are delivered. **Full M2C
connected readiness is not claimed.** Remaining gates are real account/spec and
cost/conversion sourcing, authenticated deployed transport and distributed writer
fencing, broker-derived protection deadlines, and measured end-to-end no-order
shadow timing under network/storage faults. A CPU fixture is not that timing
qualification. P0/M1 broker/provider failures and coverage gaps remain unchanged;
M2D connected PAPER still requires those prerequisites and explicit authorization.
No new 24-hour test is scheduled or required to review this implementation PR.
