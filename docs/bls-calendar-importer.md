# BLS ICS importer and refresh investigation

The read-only `fx_talanta.bls_calendar` module imports the official BLS calendar
and reconciles the jobs, CPI, PPI and JOLTS schedule with a FRED snapshot. It does
not connect to brokers, databases, the live observers or execution. PR #10 stays
unmerged.

## Verified on November 2, 2026

The user downloaded the [official ICS](https://www.bls.gov/schedule/news_release/bls.ics)
through their browser. The 80,672-byte file has 313 total events and a latest event
date of December 30, 2026. The importer retains the four selected release types;
the full downloaded file remains private local evidence, outside Git.

A fresh authenticated FRED snapshot and the BLS file agreed on all five dates in
the November 2–December 2 window:

| Release | Date | BLS Eastern time | UTC |
| --- | --- | --- | --- |
| JOLTS | November 3 | 10:00 | 15:00 |
| Employment Situation | November 6 | 08:30 | 13:30 |
| CPI | November 10 | 08:30 | 13:30 |
| PPI | November 13 | 08:30 | 13:30 |
| JOLTS | December 1 | 10:00 | 15:00 |

[Sanitized evidence](evidence/bls-import-20261102.json) retains the file hash,
matched events, snapshot references and actual assessment. BLS supplies the exact
times; FRED independently corroborates dates, **not times**. This does not mint
the FRED adapter's separate two-source exact-time evidence contract.

## Automatic refresh result

The implemented one-shot HTTPS refresh and a separate Windows HTTPS request both
returned HTTP 403. Normal certificate/hostname verification remained enabled.
The requests used the official URL and an identified application User-Agent;
there were no cookies, browser impersonation, redirect bypasses or retries.
The browser download demonstrates user access, not working unattended access.
The cause of the different responses is not established by these probes.

Consequently **automatic refresh remains unverified**. No periodic downloader was
installed. A manual file has `provenance=MANUAL_FILE` and `fetched_at=null`; its
import time or filesystem modification time is never treated as source freshness.
Re-importing it cannot clear `BLS_MANUAL_REFRESH_UNVERIFIED`. Refresh failures
produce a blocked assessment and never reuse old evidence as a fresh success.

The next qualification gate is successful direct HTTPS retrieval followed by
repeated refresh, schedule-change and freshness evidence. A single HTTP 200 would
still not prove reliable refresh or complete calendar coverage. Until then, manual
imports are useful for offline schedule checks only. BLS API registration is not
assumed to grant access to this separate ICS URL.

## Commands

From the isolated checkout, set `PYTHONPATH` to its `src` directory and use the
project Python environment. Create a fresh FRED snapshot using the
[FRED adapter](fred-calendar-adapter.md), then:

```powershell
python -m fx_talanta.bls_calendar --ics C:/SideProjects/fx-talanta/.local/bls.ics --fred .local/fred-snapshot-001.json --output .local/bls-import-001.json
python -m fx_talanta.bls_calendar --refresh --fred .local/fred-snapshot-001.json --output .local/bls-refresh-001.json
```

Each output is exclusive-create JSON containing the snapshot and assessment.
`--previous .local/bls-import-001.json` links to the previous snapshot hash and
checks event UID/SEQUENCE history. Keep the earlier files. Sequence regression or
changed content at the same sequence is rejected, not silently overwritten.
An increased sequence preserves the new revision; moved or missing dates must
still reconcile with FRED. Disappearance is not inferred to be a cancellation.
Explicit cancelled/tentative events block rather than count as confirmed matches.

Exit 0 means import succeeded, not permission to trade. Check the assessment.
The live manual-import assessment matches all five dates but still blocks entries.

## Fail-closed scope

This deliberately supports the observed nonrecurring BLS ICS format, not every
iCalendar extension. It unfolds content lines, checks component balance,
UIDs, sequences and statuses, accepts explicit UTC or Eastern zoned timestamps,
and verifies the known embedded US-Eastern DST rules before mapping to IANA
`America/New_York`. Unknown timezone definitions, floating/all-day times,
ambiguous/nonexistent civil times, recurrence, duplicate properties/UIDs, malformed
or oversized files are rejected. The file/response bound is 2 MiB; the network
timeout is 15 seconds per socket operation, not a whole-job deadline.

Reconciliation compares both directions within the FRED window: absent dates,
extra BLS dates, multiple matching events or incomplete release inventory block.
Freshness defaults to 120 seconds for both sources; future/unavailable evidence
and insufficient date windows block. Verified events veto entries inclusively
for 30 minutes before/after release. Four USD release types never establish full
calendar/news coverage, and every result keeps execution disabled.

Tests cover unfolding, DST, UTC timestamps, blackout boundaries, stale/future
snapshots, revisions, cancellation/rescheduling, malformed files, immutable
output and mocked refresh success/403/429/500 failures. Real refresh failure is
reported separately from mocked success. Neither broker's 24-hour run was changed.
