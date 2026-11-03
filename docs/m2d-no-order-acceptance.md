# M2D no-order preparation

M2D's **preparation is implemented; connected PAPER execution acceptance is open**.
The November 3 authorization permits progressing with trading disabled and no
new 24-hour campaign. This increment composes existing M2A/M2C components, probes
the two existing demo accounts read-only, and retains the original failed/stopped
qualification evidence. It deploys no EA, starts no terminal and changes no
account, binding, database, permission, clock, or entry threshold.

## Delivered checks

`scripts/m2d_acceptance.py` defaults to the simulator-only fault harness. It binds
the M2A request, account, release, policy and snapshot to M2C safety preflight,
then records the request and transitions in the existing authenticated,
hash-chained SQLite safety journal. Native sizing uses the **archived M2C fixture
result**, checking every recorded source/fixture hash first; no new native run
or production transport is implied.

Thirty scenario assertions exercise admission, ageing during delivery, missing
news, blackout/closed sessions, lost native response, storage/fence vetoes, wrong
account/release, clock regression, expiry, duplicate/hash conflict, lost-ack
restart, retained unknown reservation, partial fill and cumulative cancellation,
wrong/unowned position, rejected protection, unknown close without resend,
backend/storage failure, retained loss halt, bad signature, competing writer and
expired lease. Recommendations are persisted but never dispatched. Simulated
broker evidence is explicitly labelled `SYNTHETIC_ONLY`.

The restart closes and reopens the actual local journal, verifies its retained
checkpoint, reconstructs the admitted request, and preserves its allocation.
Partial reconciliation consumes the original allocation; duplicate evidence does
not consume it twice. Cancelling an unfilled remainder does **not** mean the
already filled position has closed. Protection and exit recommendations remain
unknown until positive synthetic reconciliation; no timeout grants a resend.

This is a local component integration test. Network, PostgreSQL availability,
multi-host fencing, terminal restart and real broker rejection/partial-fill
behavior require their own connected evidence. Passing a synthetic storage flag
test is not a measured production storage outage.

## November 3 read-only observations

Both existing CMC and FOREX.com demo terminals passed identity/build/path/currency
checks. Each successful capture collected 30 one-second sampling slots for
EURUSD and USDJPY using the Python package. Both accounts reported CAD, zero
positions and zero pending orders at sampled checks. Terminal process identity
and binding hashes remained unchanged. No account was created or switched.

Freshness includes the larger pre/post NTP error bound plus a 2 ms guard. Two
public NTP references corroborated the host clock without changing it; the
resulting bounds were about 66 ms for CMC and 67 ms for FOREX. This is bounded,
unauthenticated clock corroboration, not ongoing clock qualification. Existing
broker timestamp mappings and their expiration were preserved.

| Account / symbol | Samples within 2 s entry ceiling | Samples within 5 s observer ceiling | Quote age upper-bound p95 | SDK read p95 |
| --- | ---: | ---: | ---: | ---: |
| CMC EURUSD | 8 / 30 | 17 / 30 | 26.130 s | 0.192 ms |
| CMC USDJPY | 24 / 30 | 29 / 30 | 3.037 s | 0.108 ms |
| FOREX.com EURUSD | 5 / 30 | 10 / 30 | 20.308 s | 0.142 ms |
| FOREX.com USDJPY | 16 / 30 | 26 / 30 | 6.217 s | 0.093 ms |

These are different short sampling windows, not a broker ranking. Fast IPC reads
and a connected terminal do not make an old broker quote fresh. The **two-second
entry ceiling remains intact**. EA and MCP channels were not exercised in these
captures; their health must not be inferred from Python results. The required UI
channel cards and latency indicators remain assigned to the existing UI milestones.

For each pair and BUY/SELL direction, read-only
[order_calc_profit](https://www.mql5.com/en/docs/python_metatrader5/mt5ordercalcprofit_py)
and [order_calc_margin](https://www.mql5.com/en/docs/python_metatrader5/mt5ordercalcmargin_py)
returned finite negative hypothetical stop P/L and positive margin at minimum
volume. The loss estimate agreed with the sampled tick-value calculation within
one account-currency cent in all eight cases. These APIs estimate account-currency
amounts; they do not submit an order. Margin is a standalone estimate excluding
existing positions/pending orders. Commission, financing, executable fills,
conversion provenance and actual protective execution remain unqualified.

The first CMC attempt reported `HOST_CLOCK_CHANGED` before its sampling loop
completed. Inspection found that the new detector could compare wall time after
an SDK identity read with monotonic time before that read. The corrected detector
compares corresponding instants, and a delayed-response regression test passes.
The original attempt is retained. Its generic error is not proof of a host clock
change and does not explain the earlier CMC campaign's `INVALID_DATA` failure.
The subsequent short CMC capture completed. FOREX's successful first capture is
retained; neither historical campaign was restarted.

## Evidence and use

The sanitized [M2D evidence](evidence/m2d-no-order-20261103.json) contains actual
scenario results, short-capture summaries, retained attempt hashes, source hashes
for the final portable harness, and unchanged historical qualification verdicts.
Private raw samples/specifications, journals, NTP measurements and diagnostics
stay under the isolated checkout's ignored `.local` directory. No account IDs,
credentials or raw broker prices are published. The earliest probe artifacts
precede automatic source-manifest recording; their final-harness hashes must not
be represented as contemporaneous hashes of those earlier captures.

From this checkout, using an existing environment and a **new** output directory:

```powershell
$env:PYTHONPATH = "$PWD\src"
python scripts/m2d_acceptance.py --output .local/m2d-offline-unique
```

A separately scoped short read-only capture can use an existing private binding:

```powershell
python scripts/m2d_acceptance.py --binding <private-binding.json> --output .local/m2d-capture-unique --seconds 30
```

The latter requires Windows, the already installed pinned SDK, the already running
bound demo terminal, visible pinned EURUSD/USDJPY symbols, current bounded clock
policy, and successful fresh clock measurements. It never logs in, selects symbols,
calls `order_check`/`order_send`, changes terminal settings, installs packages or
extends a clock policy. The existing M1 SDK allowlist is unchanged; a separate
minimal probe allowlist adds only the two read calculations. The MT5 initialize
API can auto-launch a terminal if it exits between process checks; the probe
checks the same existing PID immediately before and after and refuses a changed
process. This check is not an atomic terminal-lifecycle lock.

Each invocation makes one attempt, uses a new evidence directory, and supervises
only its SDK child with a hard timeout of sampling slots plus 60 seconds (at most
180 seconds). Slow SDK calls may make slots longer than one second. On timeout it
terminates that child, retains partial evidence, reports failure and never retries
or terminates a terminal. Account counts verify sampled continuity, not absence
of all possible transient activity by another client.

## Acceptance status

| Boundary | This increment | Remaining gate |
| --- | --- | --- |
| M2A/M2C composition | Durable no-order fault trace passes; archived native fixture parity retained | Authenticated deployed transport, distributed fencing and measured end-to-end shadow timing |
| Existing demo capabilities | Read-only identity, specs, quote-age and calculation observations captured | Calibrated fees/conversions, stop/freeze/fill behavior and protection deadlines |
| M1 brokers/providers | Original evidence and verdicts preserved | Original reliability, freshness and USD/EUR/JPY coverage gaps remain |
| Connected M2D | Execution unavailable; `m2d_accepted=false` on every output | Applicable P0/M1/M2A–C gates, scoped demo-order authorization, then actual fault/reconciliation/protection evidence |

No result in this tool enables execution or schedules a campaign. Further
connected qualification is outside this increment.
