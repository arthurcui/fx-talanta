# Retired MT5 calendar deployment

The terminal-based calendar route was retired on November 3, 2026 at the user's
request. Calendar/news collection belongs in the Python application with direct
HTTP providers; MT5 is reserved for broker connectivity. The runtime dependency
on a terminal service, file handoff and Windows importer is no longer supported.

## Verified shutdown

At 00:42:03 UTC, the FOREX calendar scheduled importer was disabled and stopped.
Persistent STOP markers were written for the service and importer. Exclusive
access to the service lock confirmed the service had released it. The task is
retained disabled for audit; it was not deleted. STOP markers prevent the retained
private runtime from resuming collection on a later launch. Neither terminal was
stopped or restarted, CMC was untouched, and trading remained disabled.

The private deployment retains its SQLite journal, raw archives, clock evidence,
configuration, runtime and prior status reports. A retirement folder preserves
the scheduled-task XML, source copies, terminal-process baseline and SHA-256
manifests covering 115 deployment files and 17 inbox files at shutdown. These
counts include supporting files, not just captures. No original evidence was
rewritten or deleted. Private paths, account identifiers and credentials are not
published. The [sanitized retirement record](evidence/calendar-retirement-20261103.json)
records the shutdown independently of the earlier successful smoke result.

The MQL5 exporter/service, compiler helper, installer, task-registration helper
and scheduled file collector have been removed from the current source tree.
Their last implementation remains in Git history at
`b571d57ccc5afcb7128aa019c71c977012a6dd81` and in private retirement copies.
There are no supported MT5 calendar installation or renewal instructions.

## Preserved historical results

The [automatic smoke evidence](evidence/automatic-calendar-20261103.json) records
successful capture/import and a calendar-service stop/restart recovery check.
Three snapshots at its evidence cutoff produced 19 event revisions. This did not
qualify complete coverage, release latency or whole-terminal startup recovery.
Its earlier FRESH status is historical, not the current operating state.

The [manual capture report](mt5-calendar-bridge.md), build hashes and raw evidence
remain preserved. The Python validators and journal normalization remain usable
for offline replay without installing or connecting to MT5. The retained entry
filter still rejects unqualified provider evidence.

See [calendar/news integration](calendar-news-integration.md) for the supported
broker-independent direction and remaining provider-qualification gaps.
