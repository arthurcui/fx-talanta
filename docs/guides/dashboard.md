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

The URL contains a random session capability in its fragment, which is removed
from browser history after loading. It is not sent in the URL to the server or
stored in browser storage. The page keeps it in memory and sends it in an
Authorization header. Reloading requires reopening the private URL. Sessions
expire after eight hours. Do not share the URL or the optional `--session-file`.
This is a loopback/local-OS boundary, not a remotely deployable login service.

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

All search, trace and report endpoints use the existing bearer session and exact
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

All options use the same isolated inspection state, eight-hour bearer session,
exact Host/Origin checks and loopback listener. Nothing here enables trading.
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
