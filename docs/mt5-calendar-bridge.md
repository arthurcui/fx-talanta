# Read-only MT5 calendar bridge

This bridge is built and fixture-tested, but has **not been installed or run in a
broker terminal**. It does not qualify MT5 calendar availability, completeness or
release latency. CMC and FOREX terminals, bindings, databases and campaigns remain
untouched. PRs #10 and #11 remain unmerged. The bridge has no trading functions,
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
Re-running creates a new full snapshot, not an incremental cursor. There is no
background scheduler or automatic terminal installation in this increment.

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

After a **separately authorized** demo-terminal capture and independent clock check:

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

Next qualification requires a demo-terminal capture, clock verification across
the requested horizon, comparison against original release schedules, and repeat
collection through a release/update/outage. Full snapshots provide restart recovery
without cursor advancement, but can miss transient updates between captures; they
do not establish incremental-delivery completeness or latency. No new 24-hour
broker test is needed to complete a bounded calendar smoke check.

Official references: [calendar requests and errors](https://www.mql5.com/en/docs/calendar/calendarvaluehistory),
[calendar structures and values](https://www.mql5.com/en/docs/constants/structures/mqlcalendar),
[MetaEditor compilation](https://www.metatrader5.com/en/metaeditor/help/beginning/integration_ide).
