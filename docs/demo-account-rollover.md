# Demo account lifecycle and replacement

Accepted requirement, 2026-11-02: CMC Markets Canada is primary; FOREX.com Canada
is secondary. FX-Talanta must support replacing an expiring FOREX.com demo while
retaining project evidence and qualification history. This document specifies
future M1/M2 behavior; it is not an implemented account-switching feature.

## Broker constraints and timing

FOREX.com's Canadian FAQ states that demo access ends 90 days after signup and
renewal is unavailable. Replacement is a new broker identity, not an extension.
Confirm the actual MT5 account expiry and the permitted replacement procedure
with the Canadian dealer; this review has not established a signup API or a right
to create unlimited replacements. Account creation/verification and delivery of
new credentials remain a provisioning step until an authorized automation route
is established. Never work around broker account limits.
[Canadian FAQ](https://www.forex.com/en-ca/help-and-support/popular-faqs/).

Store signup time, broker-confirmed expiry, evidence source and whether expiry is
estimated. Use signup + 90 days only as an explicitly labelled planning estimate;
earlier confirmed expiry takes precedence. Unknown or conflicting expiry raises
an actionable provisioning incident rather than assuming another 90 days.

Proposed configurable defaults:

- **14 days before expiry:** notify once that replacement provisioning is needed;
  repeat only on escalation or meaningful status change. Record readiness daily.
- **7 days before expiry:** target completion of validation, final reconciliation
  and handoff. Use an earlier cutoff when the trading calendar requires it.
- **Before the cutoff:** stop accepting entries that could remain open beyond the
  handoff window. Account for maximum holding time, market closures and a cleanup
  buffer. Do not wait for expiry to manage existing positions.
- **Replacement missing or checks fail:** pause the FOREX.com deployment. Do not
  route its outstanding work to CMC or LIVE. A local secondary-account incident
  does not stop an otherwise healthy CMC account; shared integrity/data failures
  still follow their own halt policies.

CMC publishes a different condition: MT5 demos stay active with a login at least
every 30 days. Track confirmed successful logins with a configurable advance
warning; ordinary database/process heartbeats are not proof of broker activity.
[CMC MT5 conditions](https://www.cmcmarkets.com/en-ca/trading-platforms/metatrader-5).

## Controlled handoff

The lifecycle is ACTIVE → REPLACEMENT_DUE → PREPARING → DRAINING → RECONCILING →
RETIRED for the old identity. The replacement follows PROVISIONED → VALIDATING →
READY → STARTUP_RECONCILE → ACTIVE. Failure leaves the affected deployment blocked,
with durable state so a process restart cannot skip a gate.

1. Provision a separate demo and dedicated terminal/data path. Verify the Canadian
   dealer, server, login, BROKER_DEMO mode, currency, pricing, symbols, volume steps,
   stop constraints and capabilities. Never switch a running account-bound worker
   into another login. A replacement mapping cannot contain a LIVE identity.
2. Persist a replacement operation ID linking predecessor and successor plus the
   continuous research campaign. Credentials stay outside this record. During
   preparation both accounts may be observed, but the successor cannot trade.
3. In M2 and later, stop new entries on the old account, cancel known pending
   entries and close positions through its own protected execution gateway. In
   M1 there are no FX-Talanta order mutations; unexpected external positions are
   recorded and require resolution rather than being silently adopted or closed.
4. Reconcile orders, deals, commissions, positions and unresolved requests. Require
   positive evidence of no remaining exposure or pending mutations. A timeout,
   expired login or empty/unavailable history is not proof of a flat account.
   Unknown outcomes keep the handoff blocked and remain in the incident history.
5. Export and verify the old account's final evidence before losing access. Retain
   the original immutable ledger and binding; stop its writer and disable restart.
   Record final reconciliation, backup reference and retirement. An administrator
   must resolve incomplete evidence if expiry occurred before this step finished.
6. Activate the successor only after its own startup reconciliation and the
   retirement barrier. Revalidate approved strategy/configuration and campaign
   risk restrictions. Generate fresh decisions; never replay old intents/orders.

Handoff operations must be idempotent and enforce a single active trading identity
within the FOREX.com campaign. Once the successor has activated, rollback cannot
silently reactivate the predecessor. No per-trade approval is introduced; missing
account provisioning is an administrative dependency.

## What continues, and what remains account-specific

Retain strategy artifacts, qualified lessons and linked research history with
their original provenance. Keep account balances, positions, transactions,
reservations and loss ledgers bound to the original identity. The new broker's
virtual deposit is not trading profit, and old positions are not recreated there.

Maintain a separate, durable campaign record across demo generations so replacing
an account cannot erase losses, incidents, experiment failures or a hard halt.
Preserve the campaign's allocated-capital ceiling and loss restrictions; a new
virtual balance cannot increase risk authority or clear a halt. This campaign
ledger needs explicit implementation and tests before trading rollover is enabled.

Reports show each account segment and the boundary/gap. Any combined research
performance must use documented cash-flow-neutral accounting, disclose resets and
avoid presenting the result as one uninterrupted broker equity curve. Qualification
coverage does not automatically become continuous merely because a replacement
was opened. Keep matched CMC/FOREX.com comparisons separate and attributable.

M0C restore is **not** account rollover: it preserves the same fixture account
binding and intentionally rejects a different identity. Do not restore the old
FOREX.com database into a new account or rewrite archived payload identities.
M1 must extend account provisioning and archive support for broker-demo evidence;
M2 must implement the campaign continuity and execution retirement barriers.

## Acceptance cases

- Confirmed/estimated/unknown expiry, UTC boundaries and shortened broker expiry.
- One useful advance notification; escalation without repeated unchanged alerts.
- Replacement absent at cutoff; secondary pauses without redirecting its work.
- Wrong dealer/server/login, LIVE successor, incompatible currency/pricing/symbols.
- Open orders, rejected close, partial fill, lost response and unavailable history.
- Expiry before final export leaves an explicit evidence gap and blocked handoff.
- Crash/retry at each handoff boundary; duplicate requests cannot activate twice.
- Old writer alive or auto-restarted; new writer cannot acquire trading authority.
- Old history remains readable; a new virtual deposit cannot erase campaign losses
  or hard halts, inflate performance, or expand the allocation.
- Prepared replacement reconciles successfully and receives only fresh signals.

No scheduled reminder has been created: signup/expiry dates and actual demo
accounts do not exist yet. Lifecycle monitoring belongs in the application once
those accounts are provisioned.
