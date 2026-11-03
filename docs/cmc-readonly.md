# CMC read-only milestone

## Current acceptance status

The [consolidated conclusion](broker-campaign-conclusion.md) records the halted
v2 run and earlier failures. It did not pass; the exact INVALID_DATA trigger
remains unproven. The procedures below are historical reproduction guidance,
not authorization to resume or overwrite any concluded run. A future campaign
needs a new plan and authorization. The [fixed EA design](ea-execution-boundary.md)
does not change this read-only observer or its evidence.


Scope: a supervised Windows MT5 demo observer with isolated PostgreSQL storage,
health reporting, persistent halts and a bounded 24-hour acceptance run. Trading,
calendar/news qualification and FOREX.com rollover are outside this milestone.
The [architecture plan](architecture-plan.md) remains the full product scope.

## Starting and stopping a run

Complete the [MT5 setup](mt5-observer.md) first. The local CMC binding uses CAD,
hedging mode, EURUSD.a/USDJPY.a, SDK 5.0.6231 and terminal build 6295. Verify those
values for your own account. Never copy another account's login, data path or secrets.

```powershell
$runId = [guid]::NewGuid().ToString()
# Save this ID locally; reuse it and the same status file after a process restart.
.venv\Scripts\fx-talanta --env-file .local/cmc.env --binding .local/cmc.json observe-run --run-id $runId --duration-seconds 86400 --interval-seconds 30 --status-file .local/cmc-soak.json --stop-file .local/cmc-soak.stop
```

The command runs in the foreground. For unattended operation, launch it with your
Windows process supervisor or PowerShell `Start-Process -WindowStyle Hidden`, using
an absolute executable path, the repository as its working directory and private
stdout/stderr files. Keep the computer awake, Docker/PostgreSQL running and the
terminal's saved demo login available. This is a bounded process, not an installed
Windows service; it does not automatically restart after a computer reboot.

```powershell
.venv\Scripts\fx-talanta observe-status --status-file .local/cmc-soak.json
New-Item -ItemType File .local/cmc-soak.stop
```

The stop file is noticed between bounded polls (within one second while sleeping).
Ctrl+C also stops cleanly. Remove the stop file before deliberately resuming the
same run; keep its original status file, binding and plan. A restart retains the
original deadline, so downtime cannot extend the acceptance window. Completed,
failed and halted runs do not silently restart. Do not delete the status file to
clear a halt: PostgreSQL evidence and the account's immutable identity remain.

`observe-status` needs no credentials and exits with code 2 for a stale active
heartbeat. `observe-run` exits with code 2 for HALTED/FAILED. `COMPLETE` means the
time window ended; only `evidence.accepted: true` means the soak criteria passed.

## Recovery and evidence

- An OS file lock prevents concurrent updates to one status file; the existing
  PostgreSQL advisory lock separately fences the account writer.
- SDK calls run in bounded child processes. Each poll initializes only the pinned
  terminal with its remembered identity; it may relaunch a closed terminal. No
  login switching, order submission or order modification method is exposed.
- Database connection failures and statement timeouts close the old session,
  retry with bounded exponential backoff and reacquire the writer lock. The runner
  reconstructs counts from committed records, including after an uncertain commit.
  Twelve consecutive database failures stop the runner; it never claims to have
  recorded broker evidence while storage was unavailable.
- Database statements have a five-second server timeout and connection setup has
  a five-second timeout. Network/OS failures can still stall transport; heartbeat
  staleness exposes an unresponsive runner rather than claiming strict real-time
  scheduling. SDK child timeouts are separate from database transport timeouts.
- Account/build/path/clock-policy mismatches remain persistent halts. Ordinary
  transient failures use the binding's failure budget. The local soak uses ten
  consecutive failures and 30-second polls; tick freshness remains five seconds.
- The atomic status file records health, reasons, gaps, DB errors and acceptance
  metrics, but no credentials, raw quotes or account IDs. PostgreSQL remains the
  authority for snapshots and halts. A stale file is not evidence of a running worker.

Private binding, status files, observation history and logs stay in ignored local
storage. Use the existing explicit-demo archive workflow after stopping the writer;
an active writer blocks export. Archive identity/restore tests remain part of CI.

## Timestamp and DST policy

CMC's observed feed clock was UTC+2 on 2026-11-02, including a nonempty deal-history
query probe. No CMC-published annual DST schedule was established by the research.
Do not substitute another broker's DST rule or apply today's offset to old history.

For this soak, the explicit qualification interval is November 2 00:00 UTC through
November 4 00:00 UTC (exclusive), with offset +7,200 seconds. That covers a 24-hour
run starting November 2. It is an operational assumption bounded by ongoing
future/stale checks, not confirmation of an annual timezone rule. The runner refuses
a plan whose deadline reaches or exceeds the mapping's expiry.

Both forward and backward one-hour changes are tested: future ticks fail immediately;
stale ticks degrade and eventually halt within the existing failure budget. Expired
policies fail closed. There is no silent offset recalibration or automatic extension.
Running beyond the qualified interval needs renewed clock evidence and a new run.
Nonempty order-history/DST-transition data remain unqualified on the connected account.

The operator explicitly authorized collection on an assumption of broker permission.
That assumption is retained locally; it is not described as CMC confirmation. See
the [feasibility review](p0-feasibility.md) for remaining broader provider questions.

## Acceptance report

Predeclared criteria for a 24-hour run:

| Gate | Requirement |
| --- | --- |
| Duration | At least 86,400 seconds; short smoke runs never qualify |
| Observation span | First-to-last sample spans the duration minus at most two poll intervals |
| Coverage | At least 95% of expected polls produce distinct committed observations |
| Fresh health | At least 95% of observations are HEALTHY; degraded samples remain counted |
| Continuity | No initial, intermediate or trailing evidence gap exceeds 180 seconds |
| Final state | HEALTHY, with no persistent halt or exhausted database retries |

The report is updated after each poll and finalized when the runner exits. It does
not assume every market/session is open; a prolonged closure can correctly fail
these strict criteria. Do not weaken them after observing results. Record the
reason and define a separate, explicit session-aware acceptance plan if needed.

Current implementation checks: native regression/integration tests cover restart,
duplicate writers, database-session termination, uncertain commits, retry limits,
health staleness, duration/gap gates and timestamp-policy boundaries. Connected
smoke and 24-hour results are recorded below only after they have actually occurred.

Connected recovery smoke, 2026-11-02: a two-minute run committed 12 observations
(10 healthy, two stale) and ended HEALTHY. During the run, the dedicated observer
database session was terminated once; the runner recorded one database error,
reconnected and continued under the same run ID. The verified empty demo terminal
was closed gracefully; subsequent polling reinitialized it and returned fresh data.
No orders were submitted. This verifies process/database recovery, not a simulated
broker-wide network outage. The maximum evidence gap was approximately 15.1 seconds.

With the writer stopped, all 17 existing connected observation records (including
previous failures and halts) were exported and restored into a fresh validation
database. The records matched exactly. The restore target remains blocked in
RESTORED state; it was not released as a second writer and the original database
remains primary. The native suite passed 194 tests.

**24-hour acceptance: NOT ACCEPTED.** Neither a healthy snapshot nor a short recovery
exercise completes this gate. Full M1 additionally requires calendar/news work.

## Final sustained-run result — November 2, 2026

Run `fe4bba5a-96e8-469b-a46d-b8692011ad42` began at 18:44:31 UTC with an
original deadline of November 3 at 18:44:31 UTC. It halted on `STALE_TICKS` at
22:18:32 UTC on November 2. The worker exited. No restart, deadline extension,
policy relaxation or source/terminal/environment change was made. This report
was prepared in a separate checkout; the original CMC checkout remains unchanged.

Read-only reconstruction from all committed observations matched the final status
counts, reasons, state and acceptance gates. The
[sanitized final evidence](evidence/cmc-final-cadence-20261102.json) records:

| Gate | Requirement | Final value | Outcome |
| --- | --- | --- | --- |
| Duration | At least 86,400 s | 12,840.85 s | Fail |
| Sample span | At least 86,340 s | 12,840.10 s | Fail |
| Elapsed-poll coverage | At least 95% | 93.69% (401 observations) | Fail |
| Healthy fraction | At least 95% | 333/401 (83.04%) | Fail |
| Maximum gap | At most 180 s | 330.01 s | Fail |
| Final health | HEALTHY | HALTED / STALE_TICKS | Fail |

There were 67 STALE_TICKS observations and one MISSING_DATA observation. Coverage
is measured through the halt, not across an invented 24-hour history. The planned
24-hour duration met the minimum plan requirement; the actual run did not.
The original observer's retry policy was unchanged during this run. A later
FOREX-only cadence fix is not retroactively applied to CMC evidence. A connected
snapshot does not prove continuously fresh quotes or identify a broker-wide fault.
The short recovery/archive exercises above retain their limited scope. Trading
stays disabled. No new CMC campaign or terminal diagnostic was performed.
