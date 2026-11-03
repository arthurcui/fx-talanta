# Read-only MT5 calendar bridge

The bridge passed a separately authorized **FOREX.com demo calendar smoke check**
on November 3, 2026 UTC. Two captures and an independent schedule comparison verified
the bounded time conversion described below. This does not qualify complete event
coverage, continuous availability or release latency. CMC remained untouched; no
broker observation campaign was restarted. PRs #10 and #11 remain unmerged.
The bridge has no trading functions,
DLL imports, article scraping or external HTTP requests.

## Export and import

`bridges/mt5/CalendarExport.mq5` is a one-shot script for a connected demo terminal.
The operator supplies an explicit trade-server date window, at most 31 days, and
a non-secret bridge ID and the exact expected demo server. The script checks the
server before and after collection and rejects an account change without exporting
the login. Three `CalendarValueHistory` requests retrieve USD, EUR and
JPY. Event/country lookups verify currencies and obtain importance, time precision,
units and multipliers. The exporter retains value IDs, event IDs, reporting periods,
source revisions and raw actual/forecast/previous/revised-previous values. It does
not export account login, credentials, balances or terminal paths.

The script rejects errors and a full 500-row buffer rather than accepting potential
truncation. It checks a thirty-second elapsed budget between API calls. This is a
**cooperative budget**, not a mechanism to interrupt a blocked native calendar call;
the importer rejects over-budget exports. A terminal-level watchdog must be assessed
separately before unattended use; never kill a shared broker terminal to enforce it.

Each output gets a unique filename in that terminal's local `MQL5/Files` sandbox.
It is flushed to a temporary file and renamed without overwrite. A failed export
has no partial values; interrupted temporary files are not importable evidence.
Re-running creates a new full snapshot, not an incremental cursor. The optional
[automatic deployment](automatic-calendar.md) adds a background service and an
isolated scheduled importer for the separately authorized FOREX demo terminal.

The Python `fx_talanta.mt5_calendar` importer checks the exact schema, duplicate
JSON keys/IDs, currency counts, collection timing, clock/build/bridge identity,
time windows and numeric ranges before appending to the provider journal. Failed
validation is recorded as a failed attempt. Raw exports remain in their original
files. Revisions and normalized exact-time events reach the existing per-pair
blackout filter through the journal; entry authority remains false.

## Time and value semantics

MQL5 calendar timestamps use **trade-server time**, not the user's local timezone.
The importer requires a separate calendar clock policy with an independently
checked evidence hash and verification timestamp. It never derives this policy
from the quote adapter, a workstation timezone or the difference between two
unverified clocks. Explicit offset segments are bounded to 31 days. Ambiguous DST
folds, missing spring-forward times, gaps and dates outside the policy are rejected.
The query boundaries must lie inside the qualified intervals too.

`configs/mt5-calendar-clock.fixture.json` is deliberately synthetic and cannot
authorize a real import. Create a private, independently verified policy before
terminal qualification. The policy pins bridge ID and terminal build. Changing
the clock policy/bridge requires a separate provider journal; old rows are never
reinterpreted with a new offset.

Only `CALENDAR_TIMEMODE_DATETIME` rows become exact scheduled events. Other time
modes remain in raw evidence and an uncertain-time list; they do not become invented
midnight releases. Previous exact-time observations are retained conservatively if
an event subsequently becomes uncertain or disappears. Missing events are not
cancellations. Coverage remains unqualified, including when a query returns zero
rows. The bridge does not manufacture cancellation messages absent in this API.

`LONG_MIN` becomes null. Other raw values are divided by one million with Decimal,
preserving negative values and avoiding binary floating-point rounding. Units and
display multipliers are retained separately; scaled values must not be mistaken
for universally comparable amounts. Reporting-period fields retain their source
representation rather than being treated as UTC event instants.

Source revision numbers describe indicator revisions, not every schedule/forecast
update. The journal assigns its own immutable revision when a value changes, even
if the source revision is unchanged. Source revision regressions, value identity
changes, earlier exports and conflicting exports at the same producer time fail
closed. Reimporting the same file does not reset its export age or duplicate events.
Local import time is the earliest availability credited to FX-Talanta; a release
found in history never receives a fabricated earlier receipt time.

## Reproduction

Compile with an isolated copy of MetaEditor; the helper never launches a terminal:

```powershell
./scripts/build_calendar_bridge.ps1 -MetaEditorPath 'C:/Program Files/FOREX.com CA MT5 Terminal/metaeditor64.exe'
```

The helper prints the artifact path and hashes. Compiler version 5.0.0.6295 produced
zero errors and warnings in the initial isolated check. Neither the proprietary
compiler nor generated EX5 binaries are committed to the repository.

After an authorized demo-terminal capture and independent clock check:

```powershell
python -m fx_talanta.mt5_calendar --export .local/export.json --clock-policy .local/calendar-clock.json --journal .local/mt5-calendar.sqlite
python -m fx_talanta.provider_pipeline --journal .local/mt5-calendar.sqlite --symbol EURUSD
```

Do not run this example against a synthetic clock file or label fixture output as
live data. Import success means structurally valid shadow evidence only. The source
is optional and the required inventory/news gates remain closed. Policy version is
now `provider-shadow/2`; existing gateway mandates cannot silently change to it.

## Website alternative and remaining qualification

The public [MQL5 calendar](https://www.mql5.com/en/economic-calendar) is useful for
visual checks without a terminal. Its web display is not a documented ingestion
API established by this work, and agreement with MT5 is not independent-source
confirmation. Verify important event times against their original publishers.
General news headlines are separate from this scheduled-release bridge.

Further qualification requires broader event-inventory checks and repeat collection
through a release/update/outage, with new clock evidence for any wider horizon.
Full snapshots provide restart recovery
without cursor advancement, but can miss transient updates between captures; they
do not establish incremental-delivery completeness or latency. No new 24-hour
broker test is needed to complete a bounded calendar smoke check.

## FOREX.com demo smoke check: November 3, 2026 UTC

[Sanitized capture evidence](evidence/mt5-calendar-capture-20261103.json) records
two successful snapshots for server wall time November 2 00:00 through November 4
00:00. Each contained 29 records: USD 12, EUR 16 and JPY 1. The first took 828 ms;
the second reported 0 ms at the terminal clock's resolution, which is not a claim
of zero network latency. Cached calendar data can satisfy a repeat request.

The first snapshot was used only for clock calibration. The official
[ISM release schedule](https://www.ismworld.org/supply-management-news-and-reports/reports/rob-report-calendar/)
places Manufacturing PMI on November 2 at 10:00 Eastern, and the
[BLS schedule](https://www.bls.gov/schedule/2026/11_sched.htm) places JOLTS on
November 3 at 10:00 Eastern. Both are 15:00 UTC on these dates. The exporter
returned 17:00 server time for both events: subtracting 7,200 seconds matched
exactly. The [MQL5 book](https://www.mql5.com/en/book/advanced/calendar/calendar_trading)
provides the event-ID crosswalk (840040001 and 840030021); it is not the independent
time authority. No quote-clock policy was reused.

The clock policy was recorded at 00:06:44.547310 UTC, before the second capture
at 00:07:23 UTC. Its interval is narrowly bounded to this query, with one second
beyond the decoded end boundary to satisfy the importer's half-open clock segments.
Two US schedule anchors support this post-DST smoke mapping, not other dates,
DST transitions or independent validation of every EUR/JPY event.

The second capture was imported into a separate local SQLite journal at
00:07:39.716566 UTC, 16.716566 seconds after export. It produced 19 exact-time
events and retained 10 date-only/tentative records as uncertain. Both checked
events still matched their official UTC times after import. Reimport left the
revision count at 19 and preserved export time/age. Assessments for EURUSD and
USDJPY kept calendar and news gates closed: transport freshness alone does not
establish provider qualification.

The EX5 was hash-verified against the isolated build and installed only under the
FOREX terminal's local Scripts folder. Each launch explicitly unchecked the
script's Allow Algo Trading option; it defaults to checked on a new launch.
Input preset datetime values must be numeric server-wall epoch representations:
date strings were observed to load incorrectly and were corrected and visually
verified before either script execution. The one-shot script exited; no recurring
collector, terminal restart, trading call or new 24-hour run was introduced.
Raw exports, policy and journal remain private; published evidence contains hashes,
counts and scheduled times without account IDs, credentials or quote prices.

Official references: [calendar requests and errors](https://www.mql5.com/en/docs/calendar/calendarvaluehistory),
[calendar structures and values](https://www.mql5.com/en/docs/constants/structures/mqlcalendar),
[MetaEditor compilation](https://www.metatrader5.com/en/metaeditor/help/beginning/integration_ide).
