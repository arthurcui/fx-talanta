# Read-only operating dashboard

The M5 dashboard is a working local browser interface for **offline inspection**.
It shows EA/Python/MCP timing, evidence-backed advisor conversations, decision/risk
records and manual BLS calendar uploads. Default launch is entirely local and
offline. Optional explicit configuration adds bounded model citation selection
and a read-only historical broker-journal panel, as described below. It never
connects to MT5 or enables broker trading. The optional operator mode below
attaches only the existing offline PAPER simulator gateway.

## Open the UI

From an installed checkout (Python 3.11+ and the project's normal dependencies):

```powershell
$env:PYTHONPATH = "src;."
python -m fx_talanta.dashboard.server --state .local/dashboard-session-01
```

Or use `fx-talanta-dashboard --state .local/dashboard-session-01` after installing
the package. Open the **private URL printed by the command** in your browser.
The server does not open a browser automatically. Stop it with Ctrl+C. The state
directory must be new unless explicitly using `--resume`; choose another name for another session. Existing evidence
is retained, never reset by launch. Port 8765 is the default; `--port 0` selects an
available port without taking over another process.

The default developer launch URL carries a private bootstrap capability in its
fragment. The page removes the fragment, exchanges the capability for an HttpOnly,
SameSite=Strict session cookie, and discards its JavaScript copy. Reload uses that
cookie; there is no session-token text box or localStorage credential. Keep the
launch URL and optional `--session-file` private: either can open another session
until the server's eight-hour access window expires. Legacy programmatic bearer
access remains available only when owner mode is not configured.

### Owner sign-in

Create an owner credential file privately from an interactive terminal. The command
prompts twice without echoing the passphrase and refuses to overwrite a file:

```powershell
python -m fx_talanta.dashboard.sessions --output .local/dashboard-owner.json --username owner
python -m fx_talanta.dashboard.server --state .local/dashboard-owner-session --owner-file .local/dashboard-owner.json --tls-cert .local/server.pem --tls-key .local/server.key
```

Use a passphrase of at least 16 characters. The file contains a salted scrypt
verifier, not the passphrase; protect it using the operating system's account ACLs
and keep it outside Git and inspection backups. POSIX mode 0600 is requested but
is not a Windows ACL guarantee. Use a certificate trusted by your browser for the
exact configured host; no trust-store changes are made by these commands. Missing
TLS causes owner mode to fail before listening. Open the printed URL, sign in,
and use **Sign out** when finished. Owner mode never emits a bootstrap URL and
rejects the internal bearer capability as an alternate login.

Sessions are server-side, certificate-bound when mutual TLS supplies a client
certificate, and capped at 16 per process. Cookies use HttpOnly, SameSite=Strict,
Path=/ and, under HTTPS, Secure with the `__Host-` prefix. Cookie-authenticated
writes require an exact Origin and a session-specific CSRF header. Five failed
sign-ins within a minute throttle further attempts. Session expiry is 30 minutes
without authenticated requests (visible-page polling counts as activity), bounded
by the server's original eight-hour window. Sign-out revokes that browser session;
restart revokes all sessions. Changing credentials requires a controlled restart.
An expired server window requires a new explicit launch/resume; login cannot extend it.

Remote owner access **also** requires the existing mutual-TLS/client-certificate
and exact-origin configuration below. This is a single-owner inspection login,
not multi-user account management, passkeys, SSO, password recovery or production
deployment qualification. Signing in grants no broker authority and does not replace
the separate simulator operator capability. No real owner credentials or deployment
are created by the software acceptance tests.

Cookie and CSRF choices follow [MDN's cookie guidance](https://developer.mozilla.org/en-US/docs/Web/Security/Practical_implementation_guides/Cookies)
and [OWASP's CSRF guidance](https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html).

The default tour is visibly **SYNTHETIC**, with fixed historical timestamps. It is
not a broker account, live market or demonstration of strategy profitability.
The UI intentionally reports old quotes as stale rather than re-dating them.

## Inspect your existing offline records

Use an already exported JSON array from `fx-talanta history`. This conversion
does not open a database, contact a broker or modify the original file:

```powershell
python -m fx_talanta.dashboard.import_records --records .local/history.json --output .local/dashboard-snapshot.json
python -m fx_talanta.dashboard.server --snapshot .local/dashboard-snapshot.json --state .local/dashboard-session-02
```

Only one exact PAPER/SIMULATOR account is accepted, with 1–1000 records and an
8 MiB input limit. Mixed accounts, broker/live bindings, duplicates and future
records are rejected. Records keep their IDs, timestamps and content. No account
login is displayed by the dashboard. This import does **not** infer positions,
telemetry or performance from unrelated records. Channels stay unknown unless a
validated `dashboard-snapshot/1` includes explicitly supplied telemetry.

The snapshot contract is in `dashboard/models.py`: label, source, captured_at,
account, immutable records and up to three distinct channels. Each channel can
carry connection-at-capture, observed_at, original UTC quote_at, received_at,
clock_uncertainty_ms and symbol. Missing metrics remain unknown. Timestamp mapping
must be supplied by a separately verified collector; the dashboard cannot qualify it.

## What each indicator means

| Indicator | Meaning |
| --- | --- |
| Connection | Recorded state at capture; never presented as a current live connection |
| Quote age now | Server inspection time minus original quote timestamp |
| Transport delay | Recorded receive timestamp minus original quote timestamp; not poll interval |
| Clock uncertainty | Supplied bound; missing or over 100 ms prevents a fresh verdict |
| Fresh | Age plus uncertainty is at most 2,000 ms; does not authorize entry |
| Telemetry stale | The recorded observation is older than 15 seconds; a UI display threshold, not an execution-policy change |
| Entry | Always blocked; five-second observer and two-second entry ceilings are unchanged |
| Positions | Unknown without current reconciliation; historical fills never imply current flatness |

The page requests local inspection every five seconds while visible to update age
and reminders and optionally read the explicitly bound telemetry file, not to collect live prices. On service failure, the page explicitly
marks its retained display as last received and unavailable. Local clock rollback,
future quote/receipt times or negative delay prevent a valid freshness claim.

## Advisor and calendar

Select a journal record and ask the advisor to inspect it. It uses M4's authenticated
read API, exact-cutoff evidence projection, content hashes and original-rationale
label. English and Chinese responses are deterministic evidence views, **not**
open-ended LLM analysis. Workspace questions explain latency and trading blockers;
unsupported prompts receive a clear capability response. No command parser,
proposal generator, provider key or order route is exposed. Source and user text
is rendered as text, never HTML. Inspection receipts are durable and idempotent in
the separate local SQLite journal; source records are immutable.

The BLS file input uses the existing strict ICS importer and stores its archive and
revision journal under the new session directory. It never changes a campaign's
journal. Duplicate uploads do not postpone the seven-day review reminder. A bad
upload preserves previous evidence and raises the existing review warning. Calendar
coverage, required USD/EUR/JPY categories and freshness remain unqualified even
after a successful manual upload. News/health cards show only recorded evidence.

## Validation and scope

`tests/test_dashboard.py` covers timing, isolation, authentication, hostile origins,
request limits, durable citations, retry conflicts and calendar preservation.
`tools/dashboard-tests` contains pinned Playwright tests for desktop/mobile layouts,
chat, citations, successful/failed upload, injected text and unavailable-service
states. These launch a separate **headless** browser and synthetic server:

```text
cd tools/dashboard-tests
npm ci
npx playwright install chromium --only-shell
npm test
```

Set `FX_TEST_PYTHON` to the project Python executable if it is not on PATH. CI runs
these checks and uploads screenshots/results as `m5-dashboard-browser-evidence`.
Product HTML/CSS/JS ships inside the Python package; Node/Playwright is test tooling,
not a runtime dependency. No CDN, external fonts or external assets are loaded.

This completes the **read-only UI slice**, not full M5. Live telemetry adapters,
open-ended model chat, authenticated remote deployment and unattended PAPER
qualification remain separate work. M1–M3 gaps and B01's rejection remain unchanged.

## Resume inspection and inspect a telemetry file

Resume the **same** snapshot and local state with `--resume`. A new private session
URL is issued; previous credentials expire with the old process. Saved advisor
answers, incident transitions and upload evidence are retained. Questions are not
stored. The UI loads the latest 50 answers and indicates the total retained count.
A process lock prevents simultaneous servers from using the same state directory.
For an imported snapshot, repeat the original `--snapshot` argument on resume.

```powershell
python -m fx_talanta.dashboard.server --state .local/dashboard-session-01 --resume
```

An optional `--telemetry .local/inspection-feed.json --telemetry-run <UUID>` binds an
explicitly selected file and producer run to the inspection state. Both arguments
must be supplied together and repeated unchanged on resume. This is a **file input
contract**, not an installed broker collector. No terminal or credential discovery
occurs; only offline PAPER/SIMULATOR identity matching the snapshot is accepted.
The producer is separately responsible for verified UTC mapping and clock bounds.

`dashboard-telemetry/1` contains `account`, `run_id`, a positive integer `sequence`,
UTC `generated_at`, `provenance` (`SIMULATED` or `RECORDED`), `channels` (the same
channel contract as the snapshot), and `execution_enabled: false`. Files are bounded
to 64 KiB. Producers should replace files atomically, keep identical bytes for retries,
advance sequences, and preserve original timestamps. A sequence gap is allowed for
latest-state inspection; it does not prove uninterrupted observation coverage.

Accepted revisions are retained with raw-content SHA-256 hashes. Conflicting hashes
for the same sequence, sequence rollback, mismatched bindings, future publication,
negative latency and timestamp regression are rejected. Missing, invalid or over
15-second-old publication marks quotes SOURCE_UNAVAILABLE; retained evidence remains
inspectable. A newer sequence never renews an old quote's age. Inspection clock
rollback fails closed, including after restart. File contents are trusted local
inputs, not signed proof of broker delivery or qualification.

Incident history records initial states and subsequent changes only, with inspection
timestamps and evidence hashes. The UI displays the latest 100 transitions and total
retained count. These are sampled when the local overview is requested (normally every
five seconds while the page is visible), not continuous monitoring or a campaign.
Recovery adds a transition; it never deletes earlier failures. No acknowledgement,
auto-restart, failover, order route or execution authority is introduced.

The calendar lists up to 100 upcoming scheduled events, including cancellation state,
with an explicit shown/total count. Original timestamps and source hashes remain in
the local archive. Lesson records show M4's evidence-based memory eligibility at the
snapshot cutoff; a QUALIFIED label alone is insufficient. Neither view qualifies
provider coverage or promotes a strategy.

## Search, follow recorded links and export

Use **Search evidence** with the kind filter to find a record ID, provenance or
projected fact. Selecting a record opens its evidence trail and selects it for the
advisor. The trail follows explicit references in either direction, supersession,
and lesson supporting/contradicting-case links. It does not infer causality from
correlation IDs or timestamps. Cycles terminate; missing references are marked
MISSING and cannot bridge otherwise unrelated groups. Each present record retains
its original timestamp, provenance and SHA-256. Unsupported record kinds show
metadata only. A record's presence does not prove an order was executed, a position
is open or a strategy is qualified. No linked evidence is fetched from other accounts,
files, databases or the network.

**Search retained incidents** searches the entire local incident journal using
literal case-insensitive text (condition, state or evidence hash). Results show up
to 100 events per page, newest first. **Older matching incidents** uses an ID cursor;
new events do not shift earlier pages. **Latest incidents** returns to the newest
unfiltered page. Search results are a requested view, not a continuously refreshed
alert feed. Failures do not disappear when a condition recovers.

**Export inspection report** downloads JSON from the authenticated local service.
It contains a bounded overview, snapshot hash, projected records, timing, blockers,
and the displayed calendar/incident windows with total/shown counts. It excludes
session credentials, internal state paths, account login fields and chat answers.
Record facts and the source label are still local user data; this is not a public
redaction service. It is not a complete source archive or qualification certificate.
The report's `sha256` covers `payload` serialized as UTF-8 JSON with sorted keys,
compact separators and ASCII escaping (`json.dumps(payload, sort_keys=True,
separators=(",", ":"), ensure_ascii=True)`). The digest detects content changes; it
is not a signature or independent proof of broker activity.

All search, trace and report endpoints use the authenticated inspection session and exact
Host/Origin restrictions. Inspection endpoints cannot execute actions; optional
operator routes below are separately authenticated and simulator-only. Backend tests cover cycles,
missing links, unrelated correlated records, literal search, stable pagination,
export hashes and authentication. Headless browser acceptance exercises search,
trace, download and desktop/mobile layouts without opening user applications.

## Historical operating summary and M5 readiness

The outcomes/model-usage panel counts record versions at the imported cutoff,
including corrections. It deliberately does not add experience P&L into an account
balance or treat records as independent closed trades. Economic labels with unknown
or future outcome times remain unavailable. Model request IDs deduplicate repeated
identical traces; conflicting traces are excluded and counted separately. Usage
includes fixtures and is not billing evidence. Equity, net P&L, drawdown, exposure
and current positions stay unknown without authoritative reconciliation.

The qualification matrix shows M1–M3 gaps and the remaining connected, deployment,
matched-evaluation and sustained M5 requirements. These are explicit tracked gates,
not live monitoring or an activation switch. See the consolidated
[M5 engineering matrix](../engineering/m5-offline-acceptance.md) for reproduction,
offline comparison inputs and the exact unfinished scope.


## Optional read-only integrations

All options use the same isolated inspection state, eight-hour access ceiling,
exact Host/Origin checks and, by default, a loopback listener. Optional remote access
has the additional requirements below. Nothing here enables trading.
Do not put credentials, account identities or private configuration in Git.

**Bounded model explanations.** Supply both `--model-key-file .local/openai.env`
(containing `OPENAI_API_KEY`) and `--model-budget-file .local/advisor-budget.json`.
For a one-call development limit, the budget file is:

```json
{"max_calls":1,"reserve_per_call_usd":"0.02","total_reserved_usd":"0.02","basis":"One bounded development explanation"}
```

This is a conservative reservation policy, not measured API billing. The model
checkbox is opt-in per browser session. With it off, chat stays deterministic/local.
With it on, the question and bounded projected simulator evidence are sent to the
fixed M4 OpenAI transport. Credentials and broker-observation records are excluded.
The model can select citations or HOLD; it cannot execute or generate trusted facts.
Unknown responses expose a same-request retry button, which inspects/reuses the
original request rather than resending. Failures consume reservations; restart and
resume do not refund them. Keep the state directory: a new directory constitutes
a separate budget, not a way to retry uncertain calls. Omit both flags to disable
model calls. The UI shows reserved/unresolved counts, not a billing total.

**Offline comparison.** Upload a matched-study input through the comparison
panel (see the actual schema in `evaluation/matched.py` and the fixture referenced
by the engineering matrix). Inputs are bounded to 16 MiB, validated, hashed and
retained in the isolated journal; duplicates are idempotent. Invalid input preserves
the previous result. Results remain descriptive, retain excluded pairs and unknown
uncertainty, and never qualify a candidate or count broker trades.

**Broker observation journal.** Supply both `--broker-config .local/broker-view.json`
and `--broker-env-file .local/broker-view.env`. The env file contains only the
private `BROKER_READ_DSN` connection string. Prefer a separately provisioned
SELECT-only role; the reader additionally enforces read-only transactions.
Configuration must contain `label`, the exact `account` identity (PAPER/BROKER_DEMO),
`run_id`, `binding_hash`, and `source: "COMMITTED_OBSERVER_JOURNAL"`. Obtain expected
values from the preserved authorized campaign manifest, never by adopting an
unknown database's identity. Resume rejects a changed binding. No automatic source
discovery, role provisioning, broker login or collector startup occurs.

The separate panel refreshes latest committed records while open. Captured balances,
position/order/protection counts and quote ages are explicitly historical. Current
positions stay UNKNOWN and entry readiness stays false. Source errors clear the
panel. Native quote clock mapping is not certified by this reader. Do not infer
current flatness, usable prices or present account health from old records.

**Local alerts and TLS.** Enable the incident-alert checkbox for in-page notices on
new sampled transitions while the page is polling. No OS permission, email or
background notification is used. Optional `--tls-cert` and `--tls-key` must be
supplied together; the certificate must be valid for 127.0.0.1 and trusted by your
client. The service does not create/install certificates or change trust settings.
The printed/session-file URL switches to HTTPS; Host/Origin checks remain exact.
This is local TLS transport, not remote authentication/deployment qualification.


## Simulator operator workflow

Optional operator mode integrates the existing M4 gateway with the UI. It is
restricted to **PAPER/SIMULATOR**, uses an existing disabled simulation database/run,
and has no entry, proposal, LIVE or broker-management route. It does not create a
run, generate market observations or start a collector. Broker-view configuration
is entirely separate and never grants administration rights.

Supply all four options alongside the exact simulator snapshot:

```text
--simulator-env .local/simulator.env
--simulator-run <existing-simulator-run-uuid>
--simulator-market .local/original-market.json
--operator-token-file .local/operator-capability.txt
```

The env file uses the existing Settings format (FX_DB_* and PAPER password).
The original-market file is a validated `Market` JSON, bounded to 1 MiB. The UI
never updates its timestamps. Provide a separate, privately generated random ASCII
operator capability of at least 32 characters; do not reuse the viewer URL token.
No secret is stored in browser storage, the inspection journal or request logs.
Keep the capability file outside the inspection state directory. The session expires
with the viewer's eight-hour session. Revocation disables operator actions until a
new explicitly configured server session; it cannot undo a completed action.

Open the simulator panel, enter the capability and inspect the exact account/state.
Preview one action; verify its account and position; type `SIMULATOR ONLY` and
confirm within 20 seconds. The server binds the action to its original state version
and account. Concurrent state changes, expired requests and stale original market
inputs reject instead of silently changing intent. Confirmation retries inspect the
same durable request; an interrupted request stays unknown and is never redispatched.
A new preview is a new action, not a recovery mechanism for an uncertain result.

Supported actions are pause, resume, close an owned simulated position, flatten
owned positions and halt, and explicit simulator reconciliation. Startup places the
gateway in reconciliation state. Use explicit reconciliation with new original
market observations until the existing gateway's recovery conditions pass. This may
manage simulated protection/exposure; it never creates an entry. Resume clears only
the administrative pause and preserves loss, integrity, unresolved-order, news,
calendar and two-second quote gates. Close/flatten success requires the simulator's
confirmed state, not the button click or model response. All results are prominently
simulation-only; they are not evidence of broker execution or M5 qualification.

## Verified inspection backup and restore

Stop the dashboard first. Backups acquire the same exclusive state lock; an active
server is refused. Use new destination directories outside the source:

```powershell
python -m fx_talanta.dashboard.recovery backup --source .local/dashboard-session-01 --destination .local/dashboard-backup-01
python -m fx_talanta.dashboard.recovery verify --source .local/dashboard-backup-01
python -m fx_talanta.dashboard.recovery restore --source .local/dashboard-backup-01 --destination .local/dashboard-restored-01
```

The backup includes the inspection SQLite database and calendar evidence, uses
SQLite's backup API, checks integrity and records SHA-256 per file. Restore verifies
paths/hashes before creating a new destination and checks copied bytes. It refuses
overwrite and nested source/destination paths. A partial restore is marked incomplete
and cannot launch. Hashes detect corruption, not malicious replacement of the entire
archive; keep these private evidence archives in trusted storage.

A restored workspace is **inspection only**. It retains receipts, model reservations,
operator uncertainty and historical data, but cannot acquire model-call or simulator
operator authority. Resume it with the original immutable snapshot/broker-view binding
and without model/operator options. The original database is not restored or changed;
its recovery uses the existing storage procedure. Session/key/DSN files and arbitrary
state-directory files are not backed up. Do not delete the restoration marker to
bypass this boundary. Backup and restore do not retire or transfer execution authority.


## Browser-independent inspection and local notifications

The launcher now runs an inspection worker at `--monitor-interval 5` seconds
(allowed range 1–60). It reads configured inspection inputs while the server runs,
even with all browsers closed. It never starts MT5, collects native quotes, calls a
model, reconciles/operates the simulator or activates a strategy. Optional broker
journal reads remain read-only. Source timestamps and the two-second entry ceiling
are unchanged. This is monitoring of supplied inputs, not a new qualification run.

The UI exposes worker status and its last successful sample. A failed, stopped,
clock-invalid or overdue sampler is unavailable; a persisted old heartbeat alone
cannot make a new worker healthy. Shutdown joins the worker before closing its
journal. Running the web service does not establish unattended broker protection.

Incident transitions enter a durable local queue and produce immutable
`notifications/incident-<id>.json` files in the inspection state. Each includes its
incident ID, original sample time, condition, state and evidence reference, with no
credentials or raw quotes. File hashes are verified before marking delivery. A crash
between file creation and receipt reuses the matching file on restart. Conflicting
files are preserved and delivery remains unavailable; failed deliveries retry in
bounded batches without dropping older queued events. An already acknowledged
incident is not erased when the condition recovers.

Use **Refresh local notifications** and acknowledge individual delivered incidents.
Acknowledgment does not suppress monitoring, repair the source or authorize trading.
The panel shows the latest 100 notifications and total pending counts; the full local
queue remains retained. Local-file delivery is not email, push, external delivery or
proof that a human read it. No outbound notification endpoint is configured or called.
Verified backups now also include this spool and its database receipts.

## Optional remote inspection access

Default launch still binds only 127.0.0.1. No remote listener is started by installation,
upgrade or tests. Explicit remote inspection requires **all** of:

```text
--bind <explicit-IPv4-interface>
--public-origin https://<exact-host>:<port>
--tls-cert <server-certificate-chain.pem>
--tls-key <private-server-key.pem>
--tls-client-ca <dedicated-owner-client-CA.pem>
```

The server requires a valid client certificate at the TLS handshake **and** its
separate eight-hour viewer bearer capability for private APIs. The configured exact
HTTPS Host/Origin must match; forwarded headers are ignored. No plaintext remote
fallback, cross-origin access or remote simulator-operator mode exists. Remote
configuration with operator options is rejected before attachment, including
a loopback listener configured with a public origin or client CA. Do not forward
the local operator listener through a proxy or tunnel. A network-visible
listener also rejects missing TLS/client-CA configuration at the server factory.

Obtain server/client certificates through your controlled certificate process. The
server certificate must match the public hostname; clients must trust its chain.
Issue client certificates from a dedicated CA only to intended owners and keep client
keys private. Provision that certificate in the intended browser/client yourself;
this service does not install certificates, modify trust stores, firewall rules,
DNS, browser settings or OS services. Use short-lived client certificates and rotate
CA/session credentials with a controlled restart to revoke access. There is no SSO,
per-person user directory or online certificate-revocation service in this release.
A CA shared with unintended users is not an owner authentication boundary.

Eight concurrent request workers and five-second socket/handshake timeouts bound
slow connections; TLS handshakes occur within workers so one stalled handshake does
not stop other clients. This is a single-owner inspection service, not an Internet
edge proxy or a complete denial-of-service defense. Production ingress, network
policy, certificate lifecycle and host supervision require separate deployment
review. Test acceptance uses ephemeral certificates and loopback sockets only; no
public or cloud deployment has been performed and remote operational qualification
remains open. Never expose the service without the required client-certificate policy.

## Reading broker health correctly

The broker panel separates transport **at capture**, saved clock-policy status and
quote freshness. A recent journal receipt is not an independently verified quote.
`RECORDED_WINDOW_ONLY` means the stored policy covers the saved observation and the
current display time; the dashboard has not independently verified that policy.
`EXPIRED`, `INVALID_AT_CAPTURE` and `UNKNOWN` must not be treated as fresh inputs.

For this historical reader, `quote_freshness` remains `UNVERIFIED` and
`quote_ages_seconds` contains null values. `recorded_quote_ages_seconds` retains
the age calculated from saved timestamps for investigation. It is not measured
end-to-end latency. Current positions remain unknown and entry readiness is false.
The inspection worker records these dimensions separately, including an unavailable
journal and subsequent recovery, and delivers local notifications without a browser.
Recovery of the journal does not qualify its clock or quotes.

## Current demo account inspection

The optional current receipt view displays recent demo account counts and balances
separately from strategy history. Python receipt recency is not quote latency. EA
and MCP are `NOT_OBSERVED` in this view, and quote latency remains null. No account
receipt is a reconciliation result or a strategy input.

With the intended demo terminal **already running** and Algo Trading off, a bounded
background capture can write to a new private directory:

```powershell
python -m tools.qualification.current_broker_capture `
  --binding <private-demo-binding.json> `
  --output <new-private-inspection-directory> --samples 10
```

The tool pins terminal path/process, account identity, build, SDK version and demo
mode, and checks Algo Trading before and after each read. It does not change
terminal settings, select symbols, log in, request history, send orders or decode
broker timestamps. Up to 60 samples are permitted, with a 15-second SDK child
watchdog per sample. It stops on failure, invalidates the latest pointer and
retains prior receipts. It does not restart itself or run a qualification campaign.
The SDK has no documented attach-only switch: process checks bracket attachment,
but cannot eliminate a process-exit race inside SDK initialization. Do not use this
tool as a terminal supervisor or run it while closing/restarting the terminal.

Start the dashboard with `--broker-receipt-config <directory>/view.json` and a new
private `--state` directory. This is mutually exclusive with the historical
`--broker-config`/`--broker-env-file` options. The dashboard reads files only and
never starts the collector. Resume requires the identical source configuration.
Do not copy a configuration to adopt another account or collection run.

Receipts expire for display after 15 seconds, measured from the beginning of the
capture, not publication time. A missing or invalid receipt clears displayed
details; restoration cannot refresh its timestamp. A durable inspection cursor
rejects rollback, same-sequence content changes, future timestamps and rebinding
across restart. Original per-sample receipts remain private and immutable under
normal collector operation. A new capture uses a new run and a new directory.

This inspection path deliberately makes no clock-qualified quote claim. The strict
observer's expired-clock rejection and the two-second entry rule are unchanged.
Fresh independent timestamp mapping and proper observer evidence remain required
before qualifying quote latency or entry readiness.

## Verified timestamp mapping and reported quote age

The optional verified receipt mode now shows each symbol's original broker quote
age, its host-clock upper estimate and `FRESH`, `STALE`, `MISSING` or `INVALID`
state. This is **age since the reported broker timestamp, not network latency**.
The estimate includes the independently sampled host-clock error, a 100 ppm drift
allowance and 1 ms timestamp quantization. It does not independently bound the
broker's internal clock error. `FRESH` requires a nonnegative age with the upper
estimate at most **2 seconds**. The observer's separate five-second ceiling and
the execution entry rule are unchanged. Every dashboard result keeps entry
readiness and execution authority false, including a fresh quote.

Clock evidence pins the terminal binding, symbol set, host, UTC/monotonic anchor,
offset and evidence digest. It lasts at most five minutes and becomes unusable
earlier if total host uncertainty exceeds 100 ms. Host mismatch, reboot/monotonic
regression, UTC clock jump, expiry and missing/changed evidence never leave a
verified age on screen. A source receipt older than 15 seconds is separately
marked stale. Restoring an old receipt cannot refresh its original timestamp.

The browser labels ages as server samples. A fresh display expires conservatively
using the remaining two-second budget minus the full request elapsed time; it
also clears when the tab is hidden. This browser timer can only withdraw freshness,
never create or extend it. Server-side assessment remains authoritative.

For a bounded qualification session, the current helper supports an exact saved
BLS **Employment Situation** anchor on the same UTC day, corroborated against both
native Nonfarm Payrolls and Unemployment Rate calendar series. It checks live MCP
listener ownership before transmitting the private export, then terminal identity,
current UTC/server-time agreement and two independent NTP references. It does not
infer an offset from tick arrival time. This narrowly scoped helper is not a daily
clock service; on other dates it refuses issuance rather than reusing old evidence.

```powershell
python -m tools.qualification.inspection_quote_clock `
  --binding <existing-private-demo-binding.json> `
  --export <refreshed-private-MCP-export.txt> --reference <saved-bls.ics> `
  --output <new-private-clock-directory>

python -m tools.qualification.current_broker_capture `
  --binding <new-private-clock-directory>/binding.private.json `
  --quote-clock <new-private-clock-directory>/clock.json `
  --output <new-private-capture-directory> --samples 10
```

Launch the dashboard with that capture directory's `view.json` as described above.
The original binding, expired policies, failed campaigns and previous receipts
are preserved. The helper creates a new isolated binding; it never changes host
or terminal time. No unattended collector, automatic requalification, new campaign
or order path is installed. The default receipt mode remains explicitly unverified.


## Registered matched-study journal

An optional `--study-journal-config` file binds the dashboard to an existing offline
receipt journal with exactly `journal` (absolute path) and `plan_hash`. Its panel
shows registration/window/close status, missing decisions, pending outcomes,
corrections and the accepted receipt head. It does not register or advance a study.
Missing/invalid/rolled-back journals become unavailable and clear old details.
Binding and accepted-prefix checks survive dashboard restart. Follow the
[workflow operating guide](../engineering/m5-matched-workflow.md) for CLI schemas,
export and separate journal retention. Receipt counts are never broker trade counts.


## Optional bounded alert receiver

Local file delivery remains the default. External delivery requires both
`--alert-config .local/alert-receiver.json` and `--enable-alert-delivery`, a private
receiver token, exact HTTPS destination, fixed expiry and cumulative message cap.
See the [receiver protocol and recovery guide](../engineering/m5-alert-delivery.md).
This is not a generic email/Slack integration. A receiver must implement exact-ID/
digest acknowledgement and receipt lookup; uncertain POSTs are never blindly resent.
The UI separates local acknowledgement from receiver acceptance. Restored inspection
backups cannot reactivate delivery. No real receiver is configured by the tests.

## Pinned inspection deployment

For an explicit HTTPS launch with artifact/code drift checks and verified journal
backup/restore, use the [inspection deployment guide](../engineering/m5-deployment-readiness.md).
This restricted profile exposes no broker, model, operator or alert activation flags.
It does not replace an existing preview or qualify remote operation.

## Simulation runner results

[Incremental runner exports](../engineering/m5-paper-runner.md#existing-dashboard-integration)
use the existing matched-study receipt panel. Bind a new isolated inspection
workspace to the exported journal and returned plan hash. The panel remains read-only;
exported simulation evidence never enables trading or qualifies a candidate.

## Direct simulation runner inspection

The study journal configuration accepts `source_kind: RUNNER` to inspect an exact-bound
runner without exporting receipts. See the [operating guide](../engineering/m5-runner-operations.md)
for its schema and recovery limits. Receipt age is not quote latency; displayed positions
are simulated. The dashboard cannot enqueue, drain, stop or enable execution.

For queue counts and acknowledgement status, use `source_kind: OPERATIONS` with the
source journal and source binding hash. The [recovery guide](../engineering/m5-runner-recovery.md)
explains persistent rollback checks. Queue age and an empty queue do not establish
quote freshness or producer liveness; the view has no processing controls.

Runner inspection also shows normalized-input counts and asserted source channels.
These describe recorded simulation envelopes, not live channel connectivity or
qualified providers. See [typed input admission](../engineering/m5-input-admission.md).
