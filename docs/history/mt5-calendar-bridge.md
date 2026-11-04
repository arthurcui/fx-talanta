# Historical MT5 calendar capture and offline validation

**Retired route:** MT5 calendar collection is no longer deployed or supported.
The service and scheduled importer were stopped on November 3, 2026; see the
[retirement record](automatic-calendar.md). MT5 is reserved for broker
connectivity. This document preserves historical observations and validation
semantics, not instructions to install a calendar script.

The exporter and service source are preserved in Git history at
`b571d57ccc5afcb7128aa019c71c977012a6dd81`. Their binaries, raw captures and private
clock policies remain local evidence. The terminal export/build/install path has
been removed from the current source tree and container acceptance harness.

## Retained offline validation

`fx_talanta.mt5_calendar` validates saved snapshots without a terminal, MT5 Python
package, scheduled task or network request. It checks schema, duplicate JSON
keys/IDs, currency counts, timing, clock/build/bridge identity, time windows and
numeric ranges before appending to a separate provider journal. Failed validation
is retained. Exact-time revisions and uncertain-time records remain distinguishable.
These historical inputs remain unqualified for trading; do not import them as
current coverage or replace their original availability evidence.

## Time and value semantics

MQL5 calendar timestamps use **trade-server time**, not the user's local timezone.
The importer requires a separate calendar clock policy with an independently
checked evidence hash and verification timestamp. It never derives this policy
from the quote adapter, a workstation timezone or the difference between two
unverified clocks. Explicit offset segments are bounded to 31 days. Ambiguous DST
folds, missing spring-forward times, gaps and dates outside the policy are rejected.
The query boundaries must lie inside the qualified intervals too.

`tests/fixtures/configs/mt5-calendar-clock.fixture.json` is deliberately synthetic and cannot
authorize a real import. Historical imports require their original independently
verified policy. The policy pins bridge ID and terminal build. Changing
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

## FOREX.com demo smoke check: November 3, 2026 UTC

[Sanitized capture evidence](../evidence/mt5-calendar-capture-20261103.json) records
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
