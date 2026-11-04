# M0B: offline execution and recovery

M0B builds on the immutable M0A records without resetting either database. The
completion target is an offline decision-to-reconciliation loop. Run:

```powershell
.venv\Scripts\fx-talanta migrate
.venv\Scripts\fx-talanta offline-demo
.venv\Scripts\python -m pytest --integration -q
```

The demo first records a validated scripted decision. It sizes and reserves an
entry, commits the exact request, loses the simulated broker's response, and
reconstructs the broker/gateway state in a new gateway session. It finds the fill,
verifies protection and closes at the configured exit time. Exactly one entry is
submitted. Reported prices and P&L are synthetic fixture results.

## Contracts and persistence

`domain/offline.py` defines market/specification, policy, entry, reservation,
request, order, deal, position, cash-flow and loss-ledger contracts. Amounts use
finite Decimals and timestamps use UTC. This increment uses USD-denominated
accounts and EURUSD/USDJPY fixture instruments. Inputs include coherent bid/ask
quotes, currency conversions, volume/stop limits, costs, and explicit
calendar/news/session gates.

Migration 003 adds `fx.offline_journal`, an append-only sequence of independently
committed gateway and broker snapshots, scoped by simulation ID within the bound
account database. A simulation is a separate research ledger, not another real
account. The database rejects LIVE/non-simulator bindings, changed account
identity, revision conflicts and backward recording time. Existing M0A records
remain intact; new audit records are labeled `OFFLINE_SIMULATION`.

Gateway checkpoints and linked execution/experience records commit atomically.
The broker commits its own orders, deals, positions, cash balance and fees before
returning a response. Losing that response therefore does not lose the fill.
Full snapshots favor inspectable recovery over storage efficiency; long-running
production compaction and archival are outside this offline increment.

## Risk and atomic reservations

Sizing takes the smallest applicable trade, aggregate, remaining daily-loss,
gross-notional, currency-leg, margin and position-slot allowance. Eligible equity
is capped by the persisted allocation; a deposit does not enlarge it. Costs include
round-trip commission, slippage and financing allowances. Entry-cost and spread
headroom also protect equity-dependent limits immediately after filling. Volume
rounds down to the lot step; an unaffordable minimum lot records rejection/HOLD
behavior without sending an order.

Open-position stop risk is measured from current liquidation value, floored at
zero per position. Pending remainders and outcome-unknown reservations retain
their risk and slot. Currency netting never offsets stop-risk sums. Partial fills
become actual exposure plus only the unfilled reservation, without double counting.
Reconciled post-fill risk breaches invoke a halt and controlled closure.

A session-level PostgreSQL advisory lock permits one gateway writer per account,
including across simulation IDs. An in-process lock serializes simultaneous
requests. Both simulator and gateway require that same live database session for
every mutation; a dead session cannot continue simulated execution. This is
simulator fencing, not a claim that a database lease can fence a future MT5 process.
Independent real PAPER/LIVE writers remain later broker-integration work.

## Order and recovery semantics

Entries record CREATED → VALIDATED → RESERVED → SUBMITTING before calling the
simulator. Results distinguish acknowledgment, partial/full fill, missing or
verified protection, completion, rejection, cancellation and unknown outcome.
The gateway checks allowed transitions. Orders, deals and positions have separate
identities. A request acknowledgment is never treated as a fill.

- A crash before SUBMITTING cancels the unsubmitted intention on restart.
- A crash after SUBMITTING is uncertain even if history currently has no match.
  The reservation remains; expiration does not authorize a replacement.
- Positive broker evidence resolves uncertainty. A fixture can provide an explicit
  non-execution attestation; an empty history lookup is insufficient.
- Duplicate intent/management delivery returns the original state. Changed content
  under the same identity is rejected. The simulator deliberately rejects repeated
  submissions rather than hiding gateway bugs behind broker-side idempotency.
- Unknown close, cancel or stop mutations block another management mutation for
  that entry until reconciliation resolves them.

The simulator supports rejection, acknowledgment without a fill, partial fill,
late remainder fill, gap fill, missing initial stop, timeout before execution,
response loss after execution, disconnected broker and unavailable order history.
These are deterministic failure fixtures, not a liquidity/backtesting model.

## Protection and loss controls

Both initial-stop and configured fill-then-protect flows are exercised. A missing
stop blocks entries, attempts a bounded attachment, and invokes controlled closure
on failure or deadline. The deadline begins at submission. Protection can continue
for a known owned position even when entry-order history is unavailable.

Position mutations verify ownership, expected version and remaining volume.
Stop removal/widening and oversized or stale closes are rejected. Stop/target
triggers and holding/session cutoffs close at observed executable prices, so gaps
can exceed planned loss. Definitively rejected closes/cancellations can retry at
most three times per position version; unknown outcomes cannot. A failed or
disconnected close remains visibly open.

Daily P&L includes unrealized equity, realized costs and external cash flows.
Daily baselines persist through process restarts. The next UTC day begins from
its first fresh reconciled snapshot; stale prices cannot roll the baseline. A
daily-loss pause survives restart and clears only on a later risk day with other
gates satisfied. Unitized NAV uses retained pre-cash-flow equity, so deposits and
withdrawals do not erase drawdown. Hard drawdown/integrity halts are persistent;
restarting with a different policy is rejected.

News/calendar failures, stale quotes or unavailable history block new risk.
Protection/exits continue with fresh prices when the simulator is reachable.
Recovery requires two distinct healthy snapshots. Unexpected external positions
or orders halt the gateway; unrelated positions are never claimed or liquidated.

## Boundaries and acceptance

No broker credentials, MT5, model calls, real feeds, UI, production authentication,
real release activation, application image or cloud deployment are introduced.
Calendar/session facts and exit cutoffs come from trusted fixtures; provider/DST
qualification remains later work. The model-facing M0A record source has no new
broker tooling. `ExecutionAdapter` describes the future execution interface, but
this gateway only enables the concrete database-fenced simulator.

Database loss blocks both new entries and simulated mutations. There is no real
external venue requiring an emergency side journal here. Native MT5 supervision,
out-of-database emergency actions, their durable journal and host fencing must be
implemented and qualified before broker execution is enabled.

Tests cover exact net accounting, every crash window, fresh-process recovery,
unknown-result retention, partial reservations, protection failures/deadlines,
stale closes, concurrent entry attempts, writer/account isolation, database-session
fencing, unavailable inputs, cash flows, persistent loss halts and post-fill limits.
M0C remains responsible for image/native/Codex parity and export/restore workflows.
