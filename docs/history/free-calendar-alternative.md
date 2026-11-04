# Free alternative to the blocked BLS calendar

**2026-11-02 decision: advance the St. Louis Fed's FRED release calendar as the
free BLS-schedule alternative for further qualification.** Public calendar pages
worked from this host without an account or key. This is a successful two-event
preflight, not approval to enable automated entries. PR #10 remains unmerged and
both broker observation runs remain untouched.

## What was actually verified

Two bounded Python HTTPS requests using the isolated native-trust context returned
HTTP 200. Event rows were checked inside the calendar results table, rather than
mistaking release names in the page's selection dropdown for scheduled events.

| Event | FRED release ID | Calendar display | UTC |
| --- | --- | --- | --- |
| Employment Situation | 50 | November 6, 2026, 07:30 US Central | November 6, 13:30 |
| Consumer Price Index | 10 | November 10, 2026, 07:30 US Central | November 10, 13:30 |

Both correspond to 08:30 Eastern in the published
[BLS November schedule](https://www.bls.gov/schedule/2026/home.htm), inspected
through the research browser. Direct BLS ICS access remains blocked; this is a
cross-check of published schedules, not a successful BLS collector test.
The [FRED calendar](https://fred.stlouisfed.org/releases/calendar) explicitly uses
US Central Time and distinguishes release dates from when FRED makes data available.
Use `America/Chicago` with date-specific DST conversion, not a permanent UTC offset.

The [sanitized probe evidence](../evidence/free-calendar-alternative-20261102.json)
records the two event IDs/times and response hashes. Original HTML stays outside
Git. No FRED account was created, API key obtained or paid service selected.

## API advantage and important limitation

FRED offers API access through a [free account](https://fred.stlouisfed.org/help/account/fred-account-features/register).
[Each application needs its own registered key](https://fred.stlouisfed.org/docs/api/api_key.html).
The documented [release-dates endpoint](https://fred.stlouisfed.org/docs/api/fred/release_dates.html)
supports release IDs and pagination. Set `include_release_dates_with_no_data=true`
to include upcoming releases; the default excludes future dates without data.

**The documented response contains dates, not intraday release times.** Therefore
this API alone cannot drive a precise 30-minute blackout. A production adapter
needs separately verified time evidence, with provenance and validity, or must
block conservatively when time is unknown. Do not invent 08:30 Eastern for every
BLS event. Public HTML offers times but is less stable than a documented API;
schema-change detection and independent schedule reconciliation are prerequisites.

For an initial bounded source inventory, use FRED to cross-check BLS dates and
retain verified time evidence for each release instance. Validate reschedules,
missing/N/A times, pagination, revisions, completeness and refresh behavior before
making the source required. FRED is not a guaranteed low-latency news wire, and a
calendar source does not supply a complete current-news health signal.

[FRED's API terms](https://fred.stlouisfed.org/docs/api/terms_of_use.html) preserve
underlying data owners' restrictions; do not treat all FRED content as one blanket
public-domain licence. The proposed initial scope is BLS schedule facts, with
attribution to FRED and BLS, rather than redistribution of unrelated series.

## Other free options checked

- **BEA:** its [official calendar page](https://www.bea.gov/news/schedule/icalendar)
  links to ICS and [machine-readable JSON](https://apps.bea.gov/API/signup/release_dates.json).
  The JSON endpoint returned HTTP 200 without a key and included GDP and Personal
  Income and Outlays categories. Useful supplementation for GDP/PCE; it does not
  replace BLS jobs/CPI coverage. Detailed timestamp normalization is still untested.
- **PipAtlas:** its [API documentation](https://pipatlas.com/api-docs) offers free,
  keyless calendar JSON but explicitly advises against automated or signal-trading
  integration. Do not adopt it for FX-Talanta's trading gate.
- **Finance Calendar:** its [current free plan](https://www.financecalendar.com/api/)
  requires a verified account/key and lists 50 requests/day and 500/month for new
  accounts. It could support low-frequency schedule checks, but not the planned
  minute-by-minute monitoring without a different budget/policy. No account or
  endpoint trial was performed. It is a secondary candidate, not a substitute for
  the successful official-source preflight above.

The [isolated FRED adapter](fred-calendar-adapter.md) now retrieves this bounded
release inventory with authenticated API access and explicit unknown-time vetoes.
The user's key stays in local secret storage, never in chat or Git. Successful
date retrieval does not complete intraday-time or broader calendar qualification.
