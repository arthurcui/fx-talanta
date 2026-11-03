# M1 closure checklist and remediation scope

Prepared 2026-11-03 from existing evidence at main `893e161` (merged PR #15).
No tests, provider fetches, broker probes, database replays or campaigns were run.
This checklist implements the [canonical roadmap](architecture-plan.md); it does
not change acceptance criteria. M0A–M0C remain completed within offline scope.

**Next work: diagnostic evidence and an existing-record report, not another soak.**
Prepare one consolidated remediation PR, reviewing that first slice before adding
provider work. Do not create incremental PRs for every capture/status update.
Implementation was subsequently authorized by the owner's instruction to finish
M1. See [actual remediation progress](m1-remediation-progress.md). The earlier
campaign restriction remains. A later explicit authorization permits the bounded
[read-only EA quote comparison](ea-quote-stream.md) and related verification.
The remediation and its evidence are consolidated in one implementation PR.

## Existing evidence and limitations

| Source | Established result | Remaining limitation |
| --- | --- | --- |
| [Broker conclusion](broker-campaign-conclusion.md) and [verified report](evidence/broker-campaign-final-20261103.json) | CMC: 441 records, 438 complete, 394 fresh, halted INVALID_DATA. FOREX: 1,720 records, 1,718 complete, 1,485 fresh, stopped after about 14h20m; freshness gate already unattainable | Neither passed sustained acceptance. CMC's precise trigger is unknown; do not attribute it to stale ticks or clock failure |
| [Provider conclusion](provider-campaign-conclusion.md) and [verified report](evidence/provider-campaign-final-20261103.json) | Eight feeds stopped at 166/288 slots each; seven had 165 successful polls, BOJ 164 | No full availability pass; seven sources had no prospective item |
| JOLTS in that report | Exact URL first arrived 224.73375 seconds after schedule: ON_TIME. Parsed publication age was 2,588.76575 seconds, exceeding 360 seconds | Both metrics remain. Timestamp discrepancy is unproven; original raw feed bytes were not archived and cannot be recovered by fetching today's feed |
| [Native MCP calendar](native-mcp-calendar.md) | 72 dated instances, ten uncertain times; one checked +7,200-second anchor; restart replay added no duplicates | Shadow adapter only. Catalog counts cannot prove coverage/time stability/revisions. Initial zero-cursor timeout remains failed evidence |
| [Inventory](provider-inventory.json) and [provider acceptance](provider-acceptance.md) | Sixteen requirement groups; manual BLS, direct feed parsing and some calendar discovery implemented | URLs/HTTP success are not normalized calendars, use rights or qualified category delivery; broader news remains uncovered |

Preserve every original ID, deadline, gate, failure, frozen checkout and private
journal/configuration. Do not re-score old runs, change shared environments,
restart collectors or fail over between brokers. Future campaigns use separate
frozen sources and new journals. CMC and FOREX retain independent verdicts.

## M1 exit checklist

Each item needs a linked artifact and a pass/fail/insufficient result. Implemented
code alone cannot close a prospective evidence requirement.

| ID | Requirement / owner | Current state | Closure artifact |
| --- | --- | --- | --- |
| B1 | CMC failure attribution / observer | OPEN: generic INVALID_DATA; failing snapshot/cause lost | Stable diagnostic stage/rule codes and bounded sanitized facts survive failure; historical trigger stays unknown unless retained evidence proves it |
| B2 | FOREX quote quality / evidence reporting | Existing-record report delivered; original freshness gate FAILED, cause unresolved | [Actual report](m1-remediation-progress.md) separates symbol ages/repeated ticks and collection duration; clock uncertainty and commit latency unavailable |
| B3 | Identity, clock, completeness and recovery / observer | Partial evidence | Pinned account/build/symbol/clock policy; durable reads/commits; unchanged halt/freshness semantics; later authorized preflight and bounded recovery evidence |
| B4 | Sustained broker acceptance / runner | Both NOT ACCEPTED | Independent committed-row reconstruction and final receipt for each broker under its predeclared plan; no deadline extension or gate weakening |
| P1 | Calendar normalization / provider integration | PARTIAL | Immutable event/source/version IDs, UTC and original time basis, exact/approximate/date-only flags, horizon completeness, independent mapping and schedule revisions |
| P2 | USD/EUR/JPY category delivery / providers | INSUFFICIENT | Every inventory group and its constituent families accounted for; prospective expected-release matching, omissions and separate receipt/publication latency |
| P3 | Revision/replay/recovery / journal | Partial adapter/fixture evidence | Durable cursor and append-only revisions, dedup without freshening, failures/recovery and point-in-time assessment on selected required routes |
| P4 | Coverage and intended-use rights / source qualification | OPEN | Named sources and retained-field/use scope per family; uncovered categories remain blockers, not silently optional |
| P5 | Provider reliability / campaign | STOPPED/insufficient | Predeclared per-source availability/gap/delivery gates; no prospective item means insufficient; availability cannot promote coverage |
| X1 | Isolation and fail-closed integration / core | Foundation exists; integration open | Wrong binding, required-input failure and uncertain time cannot grant readiness; liveness, quote quality and entry permission stay separate |
| X2 | Final M1 decision / acceptance report | BLOCKED | One matrix with independent broker/provider verdicts, preserved failures, zero orders and no unresolved required gate; M2 separately authorized |

CMC is first, FOREX the independent comparison. Do not declare full M1 complete
after just one passes under the current scope. Excluding a broker/source requires
an explicit scope decision, not a reinterpretation after a failed test.

## All 16 provider groups: concrete remaining work

Candidates below are already recorded in the repository, not newly checked
endpoints. Python provider/calendar integration owns implementation; permission
and source availability are external dependencies. MCP is optional corroboration,
not an automatic substitute for missing categories.

| Inventory ID | Retained candidate | Remaining action |
| --- | --- | --- |
| USD_POLICY | Fed calendar/policy RSS | Map decisions, minutes, press conferences and projections to exact instances and prospectively received notices |
| USD_JOBS_INFLATION | Manual BLS ICS and four RSS feeds; one JOLTS match | Reconcile jobs/CPI/PPI/JOLTS, manual review freshness and revisions; preserve both JOLTS timing metrics |
| USD_GROWTH_PCE | BEA JSON preflight | Normalize metadata/duplicates/revisions; select actual GDP/PCE notice delivery |
| USD_OTHER_ACTIVITY | No complete adapter | Identify/map Census retail, Fed industrial production and Labor claims calendar/delivery paths |
| USD_OFFICIAL_UNSCHEDULED | Fed policy feed only | Complete speeches/fiscal/unscheduled inventory and define omission evidence; quiet time proves no completeness |
| EUR_POLICY | ECB calendar/announcements | Resolve date versus exact release time; map decisions, conferences and accounts, revisions and actual notices |
| EUR_INFLATION | Eurostat calendar/Atom | Normalize and match HICP flash/final instances and prospective receipts |
| EUR_GROWTH_JOBS | Eurostat calendar/Atom | Normalize/match GDP, employment and unemployment separately |
| EUR_OTHER_ACTIVITY | Eurostat calendar/Atom | Normalize/match retail trade and industrial production |
| EUR_OFFICIAL_UNSCHEDULED | ECB announcements | Verify speech/unscheduled scope, omission method and intended use |
| JPY_POLICY | BOJ calendar/updates | Preserve approximate times; map decisions, opinions, minutes and outlook notices |
| JPY_INFLATION | Statistics Bureau schedule discovery | Normalize national/Tokyo CPI and add notice delivery with verified time basis |
| JPY_GROWTH | Cabinet Office schedule discovery | Normalize preliminary/revised GDP, actual notices and revisions |
| JPY_JOBS_WAGES_ACTIVITY | Partial discovery; no complete adapter | Separate Statistics Bureau/MHLW/BOJ/METI paths for labour, wages, Tankan, industrial production and retail sales |
| JPY_OFFICIAL_UNSCHEDULED | BOJ feed; MOF gap | Add a scoped MOF announcement route; BOJ cannot prove intervention coverage |
| FX_BROADER_NEWS | No qualified comprehensive free source | Resolve a feasible provider/rights or request an explicit product-scope decision; more RSS polling alone cannot close this |

Free access remains first. No subscription purchase or external messaging is
authorized. Report source infeasibility directly before spending a campaign on it.

## Exact proposed remediation scope

### First reviewable slice: diagnostics and existing-record report

1. Add a versioned, bounded, allowlisted diagnostic envelope in
   `observer/mt5.py` and `observer/supervisor.py`. Distinguish schema rejection,
   clock policy expiry/mismatch, temporal ordering, duplicate identities and
   history-range validation. Preserve halt classification and thresholds.
2. Inspect `_collect`, `collect`, `assess`, `SDKClock.check` and `history`:
   source inspection shows they can collapse distinct causes into generic
   failures. This does **not** identify the old CMC failing branch. Retain safe
   field/rule IDs, counts and timing deltas even when snapshot validation fails;
   never expose secrets, account identifiers or arbitrary native error strings.
3. Add an offline, read-only report over retained committed exports/records,
   with no terminal connection. Separate per-symbol stale episodes, transport,
   missing commits and uncertain clock mapping. Mark absent historical fields
   unavailable. Keep exact original campaign verdicts and failed evidence.
4. Review that report before changing reader behavior. If retained evidence
   cannot prove a cause, specify the narrow future capture needed; do not guess.

### Provider slice: normalization and explainable delivery

1. Extend existing calendar/provider interfaces, not a parallel architecture.
   Normalize independent expected releases and map immutable source/version IDs;
   retain manual BLS, date-only FRED and uncertain MCP times honestly.
2. For future authorized captures, retain permitted response bytes or sufficient
   original timestamp fields, response metadata/hash, parser version and receipt
   time. Keep publication, schedule, first receipt and availability separate.
   Corrections cannot rewrite earlier delivery metrics or decision evidence.
3. Implement missing adapters only after source/use feasibility is resolved.
   Declare families, horizon, omission behavior, time uncertainty and promotion
   criteria per source. New sources do not inherit eight-feed campaign evidence.

Deliver one consolidated remediation diff with invariant review, proposed test
cases, existing-record report, coverage matrix and a bounded launch manifest.
Exclude threshold changes, trading/M2 code, new subscriptions, calendar EA/service
resurrection, automated browser refresh and shared environment modifications.

## Validation proposal — not started or authorized

1. Local regression verification now passed: 334 tests; 119 PostgreSQL-dependent
   tests were skipped to preserve broker databases. CI uses its isolated fixture database.
2. The owner authorized a five-minute FOREX EA-versus-Python quote comparison.
   Other captures still require a specific authorized scope. Each has a fixed purpose, duration, stop condition and
   evidence list. Short success is readiness evidence, never sustained acceptance.
3. Approve sustained plans only when failures are attributable and the selected
   path can plausibly meet its gates. Existing broker plan: 86,400 seconds, 2,880
   slots at 30 seconds, >=95% coverage/complete/fresh slots, span >=86,340 seconds,
   gaps <=180 seconds and final verification within 30 seconds; actual pinned
   RunnerPlan controls interpretation. Preserve five-second observer and
   two-second entry ceilings. Existing provider plan: 288 slots/source, 300-second
   cadence, 20-second timeout, >=99% success, <=900-second success gap and
   <=360-second sampled delivery. Any different future source policy needs explicit
   pre-run review, never post hoc relaxation or rescoring old records.
4. Align category capture to releases rather than repeating arbitrary one-day
   windows. Saved inventory lists BLS jobs November 6 13:30 UTC, CPI November 10
   13:30 UTC, PPI November 13 13:30 UTC; saved BEA notes list November 25 13:30 UTC.
   These are **historical planning inputs, not freshly verified schedules**.
   Reconfirm official revisions before launch. Other families need dated instances
   or an explicit unscheduled-event evidence method before selecting duration.
5. Rebuild final results from committed evidence once. Report pass, fail and
   insufficient separately; no automatic reruns, extensions, promotion or M2 start.

## Stop conditions and practical timing

Diagnostic preservation/reporting now has local regression coverage; see the
[progress record](m1-remediation-progress.md). If old records lack a
cause, identify the missing evidence and stop guessing. If a required source is
infeasible, present the source/scope decision instead of waiting indefinitely.
No defensible full-M1 completion date exists until those dependencies and release
windows are resolved. One successful day would not close all sixteen groups.
