# FOREX.com secondary demo onboarding and expiry tracking

FOREX.com Canada is the comparison broker; CMC remains primary. This increment
provides account preparation instructions and a durable local expiry/alert tracker.
It does not create accounts, switch terminal logins, perform automatic handoff,
install a notification service or enable trading. A separate FOREX.com demo was
connected on 2026-11-02; private identity and signup evidence remain outside Git.

## Account preparation

1. Use the Canadian [MT5 page](https://www.forex.com/en-ca/trading-platforms/metatrader-5/)
   and its **Try an MT5 demo account** link. Choose the demo route rather than a
   funded account. Enter your personal details and set credentials directly with
   the broker; do not put passwords in chat, repository files or lifecycle metadata.
2. Record the actual signup timestamp, the demo server/login, currency and pricing
   mode, and any broker-confirmed expiry reference in private local storage.
   Do not assume that a generic web-platform demo is an MT5 demo or that its costs
   represent the eventual live account.
3. Keep CMC's terminal, data directory, database and ongoing test untouched. The
   broker's generic download instructions mention removing older MetaTrader
   installations; do not uninstall the active CMC terminal. Qualify an isolated
   installation/profile, separate Windows user or separate Windows host before
   connecting the secondary. No installer is run by this tracker.
4. Independently verify the new terminal's executable/data paths, build, company,
   demo mode, currency, exact symbols, Python/data permissions and timestamp
   convention. CMC's `.a` symbols and UTC+2 observation do not qualify FOREX.com.
5. Provision a dedicated `fx_forex_g1` namespace with new writer passwords and an
   explicit PAPER/BROKER_DEMO binding using the [MT5 workflow](mt5-observer.md).
   Keep generation-specific identities separate. Never restore CMC or an older
   FOREX.com account ledger into this new identity.

Official-source check on 2026-11-02: the Canadian
[FAQ](https://www.forex.com/en-ca/help-and-support/popular-faqs/) states that demos
expire 90 days after signup and cannot be renewed. The Canadian MT5 page supplies
the demo signup route. The tracker treats signup plus 90 elapsed days as a planning
estimate, not a broker-confirmed expiration. Replacement availability must be
confirmed with the dealer; no unlimited replacement entitlement is assumed.

## Local schedule

Copy `configs/forex-demo-lifecycle.example.json` to an ignored local file such as
`.local/forex-lifecycle.json`. Replace its placeholders with the verified demo
identity and a generated campaign UUID. Keep that campaign UUID across generations.
Record `signup_at` as an ISO timestamp including a timezone. All comparisons and
deadlines are normalized to UTC; 90 days means elapsed days, not three calendar months.
When only the confirmation email's timestamp is available, set `signup_at_estimated`
to true and provide `signup_source`. This explicitly records a proxy for signup;
it is not a broker-confirmed expiry or proof of the exact account-creation instant.

If the broker provides an expiry, add an entry to `confirmed_expiries`:

```json
{
  "expires_at": "2027-01-31T12:00:00Z",
  "observed_at": "2026-11-02T12:05:00Z",
  "source": "Private reference to the actual broker confirmation"
}
```

These are illustrative dates, not this user's account dates. One distinct confirmed
expiry supersedes the estimate, including an earlier expiry. Different confirmed
dates produce `CONFLICTING_EXPIRY` and an actionable pause recommendation; the
earliest is displayed provisionally. Resolve the evidence explicitly instead of
silently assuming a fresh 90-day period. Prior checked configurations remain in
the local audit history. With neither signup nor confirmation, status is
`UNKNOWN_EXPIRY` and no date is invented.

## Commands and alert delivery

The tracker has no MT5 or PostgreSQL connection. Run from the checkout containing
this increment; it uses the standard Python library SQLite for local administrative
metadata and the project's existing validation models.

```powershell
.venv\Scripts\python -m fx_talanta.demo_lifecycle --config .local/forex-lifecycle.json preview
.venv\Scripts\python -m fx_talanta.demo_lifecycle --config .local/forex-lifecycle.json check
.venv\Scripts\python -m fx_talanta.demo_lifecycle --config .local/forex-lifecycle.json ack <alert-UUID>
```

`preview` writes nothing. `check` atomically records the assessment, readiness by
UTC day and meaningful changes in `.local/forex-lifecycle.sqlite3`. `--state-db`
can select another private location. This sidecar is separate from PostgreSQL
broker/risk evidence and is not included in broker `.fxbackup` archives; back up
its database while tracker commands are stopped, along with its private config.

Default milestones are replacement notice at 14 days and handoff cutoff at 7 days
before expiry, inclusive at the exact UTC instant. Expiry itself is also inclusive.
Unknown/conflicting dates and future-dated evidence produce actionable states.
At cutoff, handoff remains blocked even if `replacement_ready` is an operator
attestation: retirement, reconciliation and backup barriers are not yet implemented.
The returned `secondary_pause_required` is a recommendation for the future
controller; this CLI does not stop a process or affect CMC.

`pending_alert_ids` is a durable outbox. Unchanged checks return the same pending
ID; a restart does not lose it. A delivery consumer should deduplicate by that ID
and acknowledge only after successful delivery. Acknowledged unchanged alerts do
not recur. Escalation or a meaningful evidence/readiness change creates a new ID
and supersedes older undelivered alerts without deleting their history. Delivery
is at-least-once until acknowledgement, not a promise of exactly-once external
messaging. No email, desktop notification or scheduled job is sent/installed here.

Once an actual demo is provisioned, a daily invocation can feed an authorized
notification consumer. Repeated same-day checks are deduplicated. Alerts are
scoped to the immutable account identity plus campaign; acknowledging another
account's alert is rejected. Live identities, another dealer, a successor equal to
its predecessor, or readiness without evidence are rejected.

## Remaining account replacement work

The [rollover requirements](demo-account-rollover.md) still govern the future
handoff. This tracker preserves administrative history, not campaign loss limits or
trading authority. It always reports `handoff_authorized: false` and
`execution_enabled: false`. A new virtual deposit cannot be treated as profit or
used to reset risk; campaign risk continuity and single-active-account retirement
barriers must be implemented separately before automatic trading rollover.

## Connected onboarding evidence

On 2026-11-02 the separate FOREX.com terminal reported a CAD hedging demo,
company GAIN Capital - FOREX.com Canada Ltd., and build 6295. Its visible symbols
were `EURUSD.` and `USDJPY.`. An independent clock probe observed UTC+2 for that
session; no annual DST rule is inferred. With an isolated database and explicit
binding, the first read-only observation was HEALTHY/CURRENT: eight completed
bars, no positions or pending orders, one deal-history record and no historical
orders. No orders were submitted. CMC's concurrent test retained its own terminal,
binding, namespace and run ID. This single observation is not sustained FOREX.com
qualification or proof of automated rollover.
