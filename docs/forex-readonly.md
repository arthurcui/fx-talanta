# FOREX.com read-only qualification

FOREX.com Canada is the secondary comparison broker. This qualification uses a
separate terminal, data directory, PAPER/BROKER_DEMO binding, database namespace
and observer process. CMC's running checkout, terminal, binding and run are not
modified. Order submission and automatic account rollover remain disabled.

## Reproduce the observation

Complete the [onboarding](forex-onboarding.md) and [MT5 binding](mt5-observer.md)
checks first. The observed Canadian demo uses CAD, hedging mode, terminal build
6295, SDK 5.0.6231, and exact symbols `EURUSD.` and `USDJPY.`. Independently pin
your own identity and paths; keep credentials and account identifiers outside Git.
The supervised runner is introduced by PR #8. This qualification checkout combines
that runner with merged PR #9 without changing the active CMC installation.

Before starting, save a unique run ID and choose private status and stop files:

```powershell
$runId = [guid]::NewGuid().ToString()
.venv\Scripts\fx-talanta --env-file .local/forex.env --binding .local/forex-readonly.json observe-run --run-id $runId --duration-seconds 86400 --interval-seconds 30 --status-file .local/forex-soak.json --stop-file .local/forex-soak.stop
```

For isolated checkouts, use their source explicitly rather than replacing an
editable installation used by another running observer. Background Windows
processes should use `Start-Process -WindowStyle Hidden`, absolute paths and private
stdout/stderr logs. Keep Windows awake, PostgreSQL running and the saved demo login
available. No automatic reboot restart is installed.

`observe-status --status-file .local/forex-soak.json` reports heartbeat health.
Create the designated stop file to stop between bounded polls. A deliberate resume
must retain the same run ID, binding, plan, status file and original deadline.
Do not restart failed/halted/completed runs or delete their evidence to clear errors.

## Clock qualification and acceptance

An independent fresh FOREX.com probe on November 2, 2026 observed UTC+2. The
qualification interval is November 2 00:00 UTC through November 4 00:00 UTC,
exclusive. This is a bounded operational assumption, not an annual broker DST
rule. The planned run must finish before the policy expires. Future/stale checks
stay enabled; an offset change or expired policy must not be silently corrected.

Use the same predeclared acceptance criteria as CMC:

| Gate | Requirement |
| --- | --- |
| Duration | At least 86,400 seconds |
| Sample span | At least duration minus two poll intervals |
| Coverage | At least 95% of expected polls committed distinctly |
| Fresh health | At least 95% HEALTHY observations |
| Continuity | Initial, intermediate and trailing gaps at most 180 seconds |
| Final state | HEALTHY without persistent halt or exhausted database retries |

Poll every 30 seconds with a five-second tick freshness limit, ten consecutive
observation failures allowed and twelve bounded database retries. Stale samples
remain in the denominator. A daily maintenance period or market closure may fail
these strict gates; record that outcome rather than relaxing criteria afterwards.
COMPLETE only means the time window ended; acceptance requires every gate to pass.

The operator authorized collection on an assumption of broker permission; this
does not constitute broker confirmation. Nonempty order history and an actual DST
transition remain unqualified. No trading or broker-wide outage is simulated.

## Connected evidence

Initial onboarding returned HEALTHY/CURRENT with eight completed bars, no open
positions or pending orders, one deal-history record and no historical orders.

Connected recovery exercise, November 2, 2026: a three-minute run committed 18
observations (15 healthy, three stale) and ended HEALTHY. The dedicated FOREX.com
database connection was terminated once; one database error was recorded and the
same run recovered. The verified empty FOREX.com terminal was closed gracefully
and reinitialized under a new process ID. Maximum evidence gap was approximately
15.1 seconds. CMC's terminal process and original observer continued untouched.
The exercise's 83.3% healthy fraction is below the sustained-run 95% requirement;
neither this short duration nor these results count as 24-hour acceptance.

After the writer stopped, all 19 stored observation records (the onboarding sample
plus recovery exercise) were exported and restored into a fresh validation
database. Record sequences and payloads matched exactly. The target remains
RESTORED and execution-disabled; it was not released as another active writer.

The combined qualification checkout passed 209 native regression/integration tests.
The full 24-hour acceptance report remains pending; short recovery exercises do
not qualify. Private snapshots, logs, account identity and archive files remain
outside Git. The [expiry tracker](demo-account-rollover.md) is administrative and
does not authorize account switching or reset campaign risk.
