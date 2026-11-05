# M1 input readiness: implemented remediation and remaining restrictions

**Work in progress, not an M1 completion PR.** The
[completion decision](m1-completion-decision.md) records the unresolved milestone
contract and missing qualification-to-runtime integration. No scope change has
been approved.

PR #25 is merged. Bounded M2 demo closeout is verified, with all M1 failures
preserved separately. This work uses an isolated checkout and new SQLite journals;
no terminal, broker database, shared Python environment or stopped campaign changes.

## BEA GDP/PCE calendar

The existing provider pipeline now accepts `--sources bea` using the
[official keyless schedule](https://apps.bea.gov/API/signup/release_dates.json).
It normalizes only Gross Domestic Product and Personal Income and Outlays;
unrelated releases cannot accidentally establish either family's coverage.

```
python -m fx_talanta.provider_pipeline --journal .local/bea-new.sqlite --collect --sources bea --tls native
```

Use the separate provider Python environment for native TLS. This is one fetch,
not a service or campaign. The existing manual BLS workflow remains available.

Offset-aware timestamps become UTC while original strings and source metadata
remain in immutable receipt outcomes. Date-only values keep unknown time; they
never acquire an invented release hour. Naive timestamps, malformed/missing
families and conflicting JSON keys reject the whole response.

Normalized equivalent timestamps deduplicate. Repeated receipts do not create
new revisions or freshen the original event availability. BEA's schedule lacks
stable release-instance IDs, so identity includes family and normalized time.
A moved or omitted occurrence therefore does **not** cancel an earlier blackout.
Both times remain until independent reconciliation is implemented. Date-only
updates likewise cannot erase an exact occurrence. This conservative behavior is
not a claim of complete schedule reconciliation.

The [actual November 5 import](../evidence/bea-calendar-import-20261105.json)
retrieved 70 exact GDP/PCE occurrences. Replaying the stored response into a new
development journal left exactly 70 revisions. This was offline replay of one
real receipt, not a second prospective fetch or provider-recovery observation.
Synthetic tests additionally cover failure/recovery, changed times, date-only
updates, restart and point-in-time reads. No execution readiness was granted.

No article text is retained. The schedule hash and original time metadata support
audit, but do not establish intended-use qualification, notice delivery,
publisher reliability or completeness across the USD/EUR/JPY inventory.

## One executable M1 evidence summary

```
python -m fx_talanta.input_readiness --repository . --output .local/m1-readiness.json
```

This command reads committed sanitized reports only. It opens no terminal,
network connection or database. It reports broker collector acceptance separately
from quote readiness, lists all sixteen provider groups and their constituent
families, retains both JOLTS timing results and distinguishes M2 closeout from M1.
The source file hashes make each result reproducible. Output creation is exclusive.
Exit zero means the report was generated, **not** that M1 passed.

The [committed summary](../evidence/m1-input-readiness-20261105.json) contains the
actual remaining gaps. It is a historical evidence view, not a live health check
or a new authority-granting API. Runtime `JournalGate` still blocks missing,
stale or unqualified required input. Two-second entry and five-second observer
ceilings are unchanged; a healthy channel cannot substitute for a fresh quote.

## Fixed closure boundary

The four areas in the [M1 checklist](m1-closure-checklist.md#november-5-remediation-boundary)
are quote readiness, calendar coverage, news delivery and failure restrictions.
The original sixteen provider groups remain the declared scope. The BEA adapter
closes one implementation deficiency, not the delivery or rights requirements.
Remaining calendar families, broader news/unscheduled coverage and prospective
reliability still need evidence. Full M1 is **not qualified** by this PR.

No fresh 24-hour campaign is started or proposed as an automatic next action.
No repeated test can repair the old campaign verdicts, recover lost historical
timestamps or establish that an unobserved future release arrived on time.
