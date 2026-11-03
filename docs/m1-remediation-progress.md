# M1 remediation: implemented changes and existing-record findings

2026-11-03, isolated development branch. Initial remediation used existing records
only. The owner subsequently authorized a bounded read-only EA quote comparison
and its verification. Local regression passed: 334 tests, 119 PostgreSQL-dependent
tests skipped. The diagnostic/provider changes are not deployed into collectors;
only the separate read-only quote publisher is installed on FOREX for that bounded
comparison. No new campaign or M1 acceptance is promoted.

## Delivered

* Additive `ObservationDiagnostic` carries bounded stage/rule/count information
  across the worker pipe and into immutable observation records. Specific codes
  distinguish clock-policy expiry/mismatch, schema/payload rejection, history
  range, time ordering, future ticks/account items, incomplete bars and duplicate
  tickets. No raw input, account ID or arbitrary exception text is included.
* Existing INVALID_DATA classifications and halt behavior remain; invalid full
  snapshots still cannot enter account-bound observation storage. Absent diagnostics
  are omitted from serialization to preserve historical payload hashes. Existing
  generic reader failures remain generic rather than becoming new integrity halts.
* `observer/report.py` describes committed records without importing the SDK or
  granting acceptance. It reports per-symbol ages/repeated timestamps, UTC-hour
  bins, reasons and collection-to-record timing, with missing evidence explicit.
* Future provider attempt outcomes retain original publication timestamp fields,
  normalized UTC, parser version, receipt time and response body hash/size, including
  partial timestamp evidence on parsing failure. Receipt evidence is separate from
  item identity/revision hashes: a repeated poll does not manufacture a revision.
  Raw bodies/headlines are not archived; source-rights qualification is unchanged.

## Actual existing-record analysis

The [sanitized report](evidence/broker-existing-record-analysis-20261103.json) was
generated from existing PostgreSQL rows in repeatable-read, read-only transactions.
Both record hashes exactly matched earlier terminal verification. The sandboxed
first connection was unavailable; host read-only access succeeded. No terminal
connection, observer invocation, data collection or database write occurred.

| Broker / symbol | Available age samples | Age <=2s | Age >2s to 5s | Age >5s | Age p95 |
| --- | --- | --- | --- | --- | --- |
| CMC EURUSD | 439 | 287 | 112 | 40 | 8.802s |
| CMC USDJPY | 439 | 373 | 53 | 13 | 3.828s |
| FOREX EURUSD | 1,719 | 1,247 | 342 | 130 | 6.456s |
| FOREX USDJPY | 1,719 | 1,233 | 348 | 138 | 6.477s |

These are observed-age distributions, including available quotes from an incomplete
read, not full-campaign freshness fractions or trade opportunities. Missing samples
are not filled in. A <=2-second quote alone does not satisfy all entry conditions.

FOREX had zero identical timestamps on adjacent available 30-second reads for
either pair, and a longest observed stale streak of three samples. This argues
against a continuously frozen feed across those adjacent reads; it does not prove
which broker/network/local-clock factor caused the sampled ages. CMC had one
adjacent repeated EURUSD timestamp. Its generic INVALID_DATA cause remains unknown.

Collection-to-record p95 was 1.064 seconds for CMC and 1.156 seconds for FOREX.
The maximum was about 30.12 seconds, consistent with a recorded timeout but not
an attribution of all stale quotes to timeouts. These durations include child
startup/collection/assessment, exclude database commit time, and cannot be subtracted
from quote age. Legacy records lack per-call SDK timings and independently measured
per-sample clock uncertainty. UTC-hour bins are not inferred session classifications.

## Remaining closure dependencies

The [closure checklist](m1-closure-checklist.md) remains authoritative. B1 has
implementation and regression coverage, but no new native CMC failure-capture evidence. B2 now has an
actual retained-record report, but no proven cause or fresh qualification. Both
broker campaigns retain their failed/stopped verdicts. Provider timestamp retention
addresses future explainability, not the old JOLTS discrepancy or sixteen category
coverage gaps. No broad-news source has been qualified by these edits.

The separately authorized [EA quote-stream comparison](ea-quote-stream.md) measures
transport and common-time quote age without changing entry policy. Its short result
cannot replace sustained qualification, identify the old CMC failure, or close
provider coverage. The owner subsequently authorized offline M2 progression; no new 24-hour run or connected execution is authorized. No code merge
or new account balance can satisfy missing evidence.
