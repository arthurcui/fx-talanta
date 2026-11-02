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
The sustained run's final non-acceptance result is below; short recovery exercises do
not qualify. Private snapshots, logs, account identity and archive files remain
outside Git. The [expiry tracker](demo-account-rollover.md) is administrative and
does not authorize account switching or reset campaign risk.

## Sustained qualification result: NOT ACCEPTED

Original run `b36e03b5-db3d-4489-9c08-3c7523e355e9` began November 2, 2026 at
19:32:57 UTC with a fixed deadline of November 3 at 19:32:57 UTC. It halted on
November 2 at 21:34:27 UTC with `STALE_TICKS`, approximately 2 hours 1 minute
into the planned 24 hours. The worker exited; the terminal remained running.
No restart, deadline extension, clock-policy adjustment or threshold relaxation
was performed. Trading remained disabled.

The final result was independently rebuilt from committed PostgreSQL observations
using the original private binding and runtime credentials. The
[sanitized evidence](evidence/forex-final-20261102.json) agrees with the status
file. It contains no credentials, account identifiers or raw prices.

| Gate | Original requirement | Observed final result | Outcome |
| --- | --- | --- | --- |
| Duration | 86,400 seconds | 7,290.83 seconds | Fail |
| Sample span | At least 86,340 seconds | 7,290.02 seconds | Fail |
| Coverage | At least 95% | 218 observations; 89.70% through halt | Fail |
| Healthy fraction | At least 95% | 168/218, 77.06% | Fail |
| Maximum gap | At most 180 seconds | 329.98 seconds | Fail |
| Final health | HEALTHY | HALTED / STALE_TICKS | Fail |

There were 50 stale observations and zero recorded database errors. Coverage is
the runner's expected-poll fraction over elapsed time through the halt, not a claim
of 89.70% coverage over 24 hours. The planned duration satisfies the minimum
24-hour policy, but the elapsed-duration gate does not. None of these results can
be promoted to sustained acceptance. Earlier smoke recovery and exact archive
restoration demonstrate their narrower exercises only.

The halt reason establishes stale tick evidence. The diagnosis below explains the
329.98-second gap through the observer's retry policy, but the upstream cause of
quote staleness remains unproven. Preserve the original logs and history
for diagnosis; do not claim a broker-wide outage or reset evidence to clear it.

### Independent CMC comparison at November 2, 21:53 UTC

Both brokers used the same gates above. CMC's original run was still RUNNING with
a CURRENT heartbeat, 378 observations, 326 healthy (86.24%), 100% elapsed-poll
coverage and a 30.48-second maximum gap. These are interim status-file values,
not CMC's final database-verified acceptance result. Its latest observation was
DEGRADED/STALE_TICKS, and its full duration was still pending. FOREX.com's final
failure does not establish CMC acceptance or an execution-quality ranking.
CMC's source checkout, terminal, binding, environment and database were untouched.

### Pull-request dependencies

This consolidated qualification branch combines the supervised runner from draft
PR #8 with the lifecycle/onboarding work already merged as PR #9. A PR against
main therefore still contains the unmerged PR #8 runner changes; it must not be
merged independently ahead of PR #8. After PR #8 is reviewed and merged, update
this branch against main and verify the resulting diff and CI before any merge.
PR #10's calendar/provider work is separate and remains unmerged. This report
records a failed qualification, not approval to trade or to create a new run.

## Halt diagnosis — November 2, 2026

Read-only replay of the 218 committed snapshots against the original binding and
recorded assessment times reproduced **all 218 reasons**. Recomputing the failure
streak produced zero counter mismatches. No terminal was initialized, restarted,
reconfigured or polled for this diagnosis. The original run remains halted.
[Sanitized diagnostic evidence](evidence/forex-halt-diagnosis-20261102.json)
contains timestamps, ages and retry intervals, never prices or account identity.

### Direct halt trigger

The final ten collected observations failed the five-second tick-age rule between
21:17:28 and 21:34:27 UTC, spanning approximately 17 minutes rather than ten
consecutive 30-second polls. EURUSD was stale in eight of those checks and USDJPY
in seven; at least one symbol was stale at every check. In the final snapshot,
EURUSD's latest tick was 5.671 seconds old and USDJPY's was 3.121 seconds old.
That was the tenth consecutive failure, triggering the configured halt.

All 218 snapshots reported connected. Both symbols' tick timestamps advanced at
every check in the final streak, so this was not a single frozen tick persisting
for 17 minutes. No stored observation reported TIMEOUT, DISCONNECTED, identity
mismatch or a clock-policy error. These facts do not prove that the feed was
continuously connected between samples or establish whether sparse updates,
delivery delay or terminal caching caused the observed ages.

### Why the five-minute evidence gap occurred

`Observer._poll` assigns exponential `next_retry_at` delays to every non-current
observation, including STALE_TICKS: `min(300, 2 * 2**(failures - 1))` seconds.
Before that deadline it returns the previous record without a new SDK collection.
The runner still wakes every 30 seconds, but its evidence accumulator correctly
deduplicates the returned record. A current process heartbeat therefore does not
mean a fresh committed observation.

| Prior failure count | Retry delay | Observed next-record gap |
| --- | --- | --- |
| 5 | 32 seconds | About 60 seconds |
| 6 | 64 seconds | 90.07 seconds |
| 7 | 128 seconds | 149.96 seconds |
| 8 | 256 seconds | 270.06 seconds |
| 9 | 300 seconds | 329.98 seconds |

The final retry deadline was 21:33:57.888711 UTC. The next actual collection was
21:34:27.867393 UTC, approximately one runner interval later. The deadline is
based on completed-assessment time while polling is paced from loop start, so a
boundary-aligned wake can precede the deadline and defer collection another poll.
The source logic and recorded retry deadlines explain all six gaps over 45 seconds
in the run. There is no need to infer a five-minute hung collection to explain them.

Persisted timestamps bound every poll's collection-plus-assessment duration by
1.457 seconds: `history_to` is the poll-start time rounded down to whole seconds.
The maximum lag from completed snapshot to assessment was 0.109 seconds. The
System log query found no matching sleep/wake/restart events from 21:10–21:36 UTC.
The terminal journal had no categorized connection/startup/error entry during
that interval; its latest such entry preceded this sustained run. Those log checks
provide supporting negative evidence, not proof that every host/network component
was continuously healthy.

### Engineering conclusion and proposed follow-up

The halt correctly enforced the original freshness/failure policy. Separately,
applying long retry backoff to stale-but-successful reads conflicts with a 30-second
observation plan and a 180-second maximum-gap gate. Skipping collection also means
the run cannot establish whether quote freshness recovered between retries.

The isolated correction below separates observation cadence from transport recovery:
continue recording stale-but-valid snapshots at the declared cadence, preserve
entry blocking and consecutive-failure halts, and reserve bounded retry backoff
for genuine transport/SDK failures. Add deterministic tests for stale streaks,
recovery between polls and deadline-boundary scheduling. Do not retrospectively
relax the five-second/95%/180-second gates, change this run's outcome or promise
that a cadence fix will make the broker pass. Diagnosing upstream quote behavior
would require a separately authorized future data-collection exercise.

The diagnosis initially changed documentation/evidence only. The subsequent
authorized code correction is described below; CMC and the original FOREX run
evidence remain untouched, and PRs #10 and #11 remain unmerged.

## Isolated cadence correction (not deployed to either broker run)

Observer version `observer/3` now sets the retry eligibility of DEGRADED reads
to the assessment time itself. STALE_TICKS and MISSING_DATA therefore remain
collectible at the runner's next scheduled poll, without the exponential wait.
The runner still controls the 30-second cadence. BACKOFF reasons TIMEOUT,
READER_FAILED and DISCONNECTED retain exponential transport retry delays.

The existing record schema still requires a retry timestamp for nonterminal
failures, so immediate eligibility preserves wire/storage compatibility. Existing
records and their deadlines are not rewritten. Persistent halts remain terminal
when an observer is opened; this change does not permit restarting the failed run.
The five-second freshness rule, ten-failure run binding, entry restrictions and
all original acceptance gates remain unchanged. Ten consecutive stale reads now
reach the same halt threshold sooner because samples are no longer skipped.

Regression tests use fake time with the real observer, runner and separate fixture
PostgreSQL storage. They verify 30-second cadence through ten stale observations,
halt persistence, recovery after eight stale/incomplete observations, collection
completion after the cadence origin, and transport suppression just before versus
eligibility exactly at the retry deadline. These tests are synthetic; no new
FOREX.com observation campaign was started and no CMC code/environment was changed.
