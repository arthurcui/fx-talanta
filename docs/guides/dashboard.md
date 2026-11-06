# Read-only operating dashboard

The M5 dashboard is a working local browser interface for **offline inspection**.
It shows EA/Python/MCP timing, evidence-backed advisor conversations, decision/risk
records and manual BLS calendar uploads. It does not connect to MT5, read broker
credentials, call a model, attach a gateway or enable any trading operation.

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
