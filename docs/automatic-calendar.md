# Automatic FOREX.com calendar collection

The Windows deployment has two components: a read-only MQL5 **service** in the
FOREX.com demo terminal and a limited-user Windows scheduled importer. It does not
install into CMC, enable trading, launch/restart a terminal, change broker bindings
or write to either broker's PostgreSQL database. PRs #10 and #11 remain unmerged.

The service calls the same bounded exporter once per minute, after the previous
capture finishes. Every snapshot uses the explicit verified query window; it does
not silently roll that window forward. Each capture goes to a unique JSON file in
a deployment-specific terminal Files directory. Partial temporary files are ignored.
An exclusive file handle prevents two instances using the same output directory.
The service stops on expiry, a stop marker, account/build change or UTC rollback.
A disconnected terminal produces no successful capture; the importer detects age.
The native calendar-call budget remains cooperative, not a preemptive watchdog.

The importer runs once per minute while the Windows user is logged in. It archives
raw files by SHA-256, validates the pinned bridge/build/clock and query window, and
commits attempts and outcomes to an isolated SQLite journal. Outcomes are its
restart cursor. A crash before commit leaves an incomplete attempt; the next scan
can retry without duplicating event revisions. Reimport does not make old data
fresh. Each deployment pins its configuration hash; changing the clock or scope
requires a new deployment and journal, preserving the old evidence.

Status is `FRESH` only when the latest successful export is at most 120 seconds
old. Later failures, missing output and expiry are reported separately. Consumers
must check `checked_at`, export age and `expires_at`, not just a saved status word:
if the importer itself stops, its last status file cannot update. The shared
calendar filter independently evaluates producer age and actual query coverage at
the decision cutoff. Missing required inventories and unqualified sources still
block entries. The five-second quote ceiling and two-second entry rule are unchanged.

The scheduled task has a 45-second process limit and ignores overlapping invocations.
It retries on the next one-minute trigger rather than changing evidence or killing
the terminal. There is a final expiry check, including after a missed wakeup.
No Windows password is stored. The importer uses a private copy of the Python
package, so edits to the provider checkout do not change the deployed runtime.
The Python interpreter/dependencies must remain available at the specified path.
This is a Windows workstation deployment, not a Linux/Docker MT5 runtime.

## Install and activate

From the isolated provider checkout, compile a reviewed service with the official
installed MetaEditor. The helper uses an isolated portable compiler copy:

```powershell
./scripts/build_calendar_bridge.ps1 -MetaEditorPath 'C:/Program Files/FOREX.com CA MT5 Terminal/metaeditor64.exe' -Program CalendarService | ConvertTo-Json | Set-Content .local/calendar-service-build.json
```

Run `scripts/install_forex_calendar.ps1` with explicit `BindingPath`,
`ClockPolicyPath`, `ClockEvidencePath`, `BuildResultPath`, `PythonPath`,
`DeploymentPath`, `ServerFrom` and `ServerUntil` arguments. The two server times
are numeric wall-clock epoch representations, not UTC event instants. The installer
verifies the FOREX demo binding, terminal data-folder origin, build and evidence
hashes, rejects an existing deployment and uses unique terminal directories.
It creates `service-inputs.set`, `deployment.json`, `installation.json`, a private
runtime and `collect.ps1`. Keep all these files local; they contain machine paths.

In the FOREX terminal Navigator, refresh Services, expand the generated `FXCalendar_`
folder and add its `CalendarService` instance. **Uncheck Allow Algo Trading**, load
the generated `service-inputs.set`, and verify the server, dates, build, 60-second
cadence and `StopAtUTC` before starting. This one-time Navigator activation is
required; copying an EX5 alone does not activate a service.

Then register the importer with:

```powershell
./scripts/schedule_forex_calendar.ps1 -DeploymentPath '<absolute private deployment folder>'
```

Inspect `status.json` and Windows Task Scheduler's last result. The task name is in
`scheduled-task.txt`. Exit zero means fresh collection, a deliberate stop or expiry;
it never grants trading authority. `FRESH` means fresh export transport, not that
the underlying calendar has complete coverage or that a published value arrived
without delay.

[MetaQuotes documents](https://www.mql5.com/en/docs/runtime/running) that active
services reload when a terminal restarts. This deployment does not restart a
broker terminal to test that behavior. For a manual pause/restart, use the specific
service instance's Stop/Start menu. To stop both components permanently, put a
`STOP` marker in the deployment's terminal inbox and disable its named scheduled
task. Preserve the deployment, archive and journal. Removing a stop marker or
creating a replacement deployment must be an explicit operator action.

## Current bounded deployment

The first automatic deployment on November 3, 2026 uses the independently verified
clock from the [calendar smoke check](mt5-calendar-bridge.md). The query remains
server November 2 00:00 through November 4 00:00, corresponding to UTC November 1
22:00 through November 3 22:00. Both components expire at **November 3, 22:00 UTC**.
This boundary must not be extended without new clock evidence. There is no
automatic promotion of this source to trading-qualified status.

The remaining provider qualification is scheduled-release update latency, wider
currency/event inventory and new clock horizons/DST transitions. Starting automatic
collection does not establish these properties. Recovery tests use the isolated
calendar service and importer, never a new 24-hour quote campaign.

## Observed deployment and recovery

[Sanitized evidence](evidence/automatic-calendar-20261103.json) records the actual
scheduled task and terminal-service check. The first scheduled import was fresh
at 00:25:13 UTC, 27.057139 seconds after export. After stopping only the calendar
service, the scheduled importer reported `STALE` at 00:28:14 UTC with export age
148.417632 seconds. The filter independently rejected producer freshness and kept
both pairs blocked. Restarting the same service produced a new export; the next
scheduled import recovered to `FRESH` at 00:29:13 UTC, age 6.915726 seconds.

At the evidence cutoff, three snapshots were preserved and three outcomes were
committed; unchanged event data still had 19 revisions, not 57 duplicates. All
captures contained 29 records. The scheduled task returned zero after recovery.
The original terminal processes remained running, CMC was unchanged, and neither
broker observation campaign was restarted. Native fixture validation passed 336
tests; both the script and service compiled without errors or warnings. Partial
files, interrupted attempts, collector restart, expiry, configuration changes and
concurrent collectors were checked in fixtures. No actual release-delay measurement
or full-terminal restart test is claimed.
