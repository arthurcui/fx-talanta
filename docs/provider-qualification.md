# Real calendar/news provider qualification

Current continuation: [required FX provider qualification](provider-acceptance.md).
The findings below are historical. PRs #10/#11 are merged, the MT5 calendar route
has been retired, and the accepted manual BLS workflow remains in place.

Assessment date: **2026-11-02**. Budget preference: **free access first; paid only
if necessary**. PR #10 remains unmerged. Neither CMC nor FOREX.com's ongoing
24-hour run, terminal, source checkout, database or acceptance criteria is changed.

## Decision and readiness

Implementation follow-up: [calendar/news integration](calendar-news-integration.md)
connects the adapters, immutable attempt/revision journal and offline entry gate.
Fed, ECB, BOJ and FRED succeeded in its bounded check; direct BLS refresh still
returned 403. No required provider is promoted by that integration check.

Follow-up: [bounded refresh and recovery qualification](provider-refresh-qualification.md)
records three successful FRED reconciliation passes, persisted outage/recovery
semantics, Linux RSS transport checks, and request-dependent BLS results. Linux
probe downloads succeeded, but the unchanged refresh adapter still returned 403.
These findings refine the initial preflight below; no required feed is qualified.

No provider is yet qualified to satisfy the required trading-input gate. This is
an evidence-backed preflight, including actual public endpoint requests, not a
latency/coverage certification. The next no-subscription route is official-source
shadow collection plus a separately qualified MQL5 calendar bridge. Do not attach
that bridge to either terminal during the current soak. Paid API sampling is a
fallback only if the free route cannot meet the declared coverage and retention
requirements. No subscription was purchased, account created or vendor contacted.

| Candidate | Public evidence / actual check | Qualification decision |
| --- | --- | --- |
| Fed monetary-policy RSS | Python HTTPS 200; 15 items, unique IDs and parseable zoned timestamps. Conditional recheck returned 304. | Advance to optional, read-only shadow collection. Not comprehensive USD news or a calendar. |
| ECB announcements RSS | Default Python TLS failed; explicit native-trust Python HTTPS now returns 200 and 15 valid items. | Windows transport fix verified in isolation; Linux/Docker and sustained coverage still pending. |
| BOJ updates RSS | Python HTTPS 200; 47 items, unique IDs and parseable zoned timestamps. | Format preflight passed; automated-use/retention scope and coverage remain open. |
| BLS release calendar | Public ICS endpoint returned HTTP 403 through both Python and Windows HTTPS with the same identified client. | Unavailable from this host; no access-control workaround attempted. USD/BLS scope only. |
| FRED release calendar | Free public pages returned 200; jobs and CPI event-row times matched the published BLS schedule. | Advance as the BLS schedule alternative; API supplies dates only, so precise-time qualification remains necessary. |
| MT5/MQL5 calendar | Documented calendar history and incremental change-ID API, with trade-server time semantics. No terminal probe in this increment. | First no-new-subscription calendar candidate to test after the soaks or on a separate qualified terminal. Availability and rights are not assumed. |
| Trading Economics | Calendar IDs, UTC release times, timing precision, importance and update/revision-related fields; streaming and point-in-time documentation. | Best-documented paid fallback examined; authenticated sample, quota and retention agreement still needed. |
| FMP calendar/forex news | Calendar endpoint documented; forex-news FAQ describes daily updates. Published terms impose storage/use restrictions. | Do not adopt as the required low-latency news feed on present evidence. Reconsider only with suitable written scope and measured delivery. |

The actual requests occurred around 20:52–20:54 UTC. The sanitized
[probe evidence](evidence/provider-preflight-20261102.json) includes response
metadata, hashes, counts and timestamps, not article bodies. Fed's newest item in
the sampled feed was October 28; that can be a legitimate quiet policy-announcement
period. It is neither proof of feed failure nor proof that all current USD news is
covered. An HTTP 304 establishes unchanged content, not complete coverage.

## Free-source constraints and attribution

Follow-up: the [free-calendar alternative assessment](free-calendar-alternative.md)
records successful FRED jobs/CPI checks, the API's date-only limitation, and a
working BEA JSON supplement. These findings do not qualify a full trading feed.

The [Fed feed directory](https://www.federalreserve.gov/feeds/feeds.htm) offers
separate policy, speech and other announcement feeds. The [Board's reuse policy](https://www.federalreserve.gov/disclaimer.htm)
generally permits its own information with attribution; third-party material and
protected marks have exceptions. Start with original source links, timestamps,
hashes and attributable permitted metadata. A monetary-policy feed alone excludes
many statistical releases and unscheduled developments.

The [ECB directory](https://www.ecb.europa.eu/home/html/rss.en.html) separates
announcements from statistical publications. Its [reuse terms](https://www.ecb.europa.eu/services/using-our-site/disclaimer/html/index.en.html)
require accurate attribution and contain exceptions, including named-author works.
The observed Python failure was `SSLCertVerificationError`, issuer code 20; Windows
success indicates a transport/trust-store difference worth diagnosing, not a reason
to turn off TLS verification. A subsequent Python probe using an explicit
`truststore.SSLContext` succeeded: 15 items with unique IDs and valid timezone-aware
timestamps. Hostname verification and `CERT_REQUIRED` remained enabled. The
[truststore API](https://truststore.readthedocs.io/en/latest/) uses native system
certificate validation and supports intermediate-chain retrieval; the exact
missing certificate was not established by this test. No certificates were added
manually and no global SSL monkey-patch was applied. Linux/Docker behavior and
sustained delivery remain unqualified.

[BOJ](https://www.boj.or.jp/en/tips.htm) distributes update titles and dates. Its
[copyright policy](https://www.boj.or.jp/en/about/copyright.htm) lists commercial
copying and certain materials as requiring prior permission, and restricts changes
to content. The qualification remains unresolved for the intended automated
trading/retention use; this report does not claim a legal determination that private
trading is or is not commercial. No full-text archive is authorized by this probe.

The [BLS calendar instructions](https://www.bls.gov/help/hlpiCAL.htm) publish the
ICS URL and describe a tentative weekly schedule update. An upcoming schedule
does not supply actual release values or intraday completeness. The observed 403
is a failed transport preflight, not proof that BLS has no public calendar.
The follow-up Windows HTTPS check also returned 403 using the same honest client
identity. This is distinct from ECB's certificate-chain failure. Leave BLS marked
unavailable; use another separately qualified calendar or seek BLS guidance rather
than disguise the client or bypass the denial. Its public data-series API is not
automatically a replacement for a future-release calendar.

[Eurostat's APIs](https://ec.europa.eu/eurostat/web/user-guides/data-browser/api-data-access/api-introduction)
are free, but the documentation describes latest-version datasets without past
version history and twice-daily updates. Its [catalogue RSS](https://ec.europa.eu/eurostat/web/user-guides/data-browser/api-data-access/api-detailed-guidelines/catalogue-api/rss)
tracks dataset changes; this is not interchangeable with a complete, low-latency
market-news wire. Japan's [Statistics Bureau schedules](https://www.stat.go.jp/english/data/roudou/1543.htm)
are additional release cross-check candidates, not yet transport-tested here.

## Calendar route and paid fallback

The [MQL5 calendar reference](https://www.mql5.com/en/docs/calendar) uses trade-server
time. Never reuse a quote-clock offset as proof of calendar time semantics. A
read-only bridge must independently qualify UTC conversion, DST, coverage horizon
and revisions. [CalendarValueLast](https://www.mql5.com/en/docs/calendar/calendarvaluelast)
documents a zero-change-ID initialization that returns the current cursor without
records, partial-result error 5400, timeout 5401 and million-scaled values with a
missing-value sentinel. Test initial history plus incremental recovery; an empty
initial result is not evidence of an empty calendar. Do not enable Algo Trading,
install an EA or alter either current terminal to perform this work during the soak.

[Trading Economics' schema](https://docs.tradingeconomics.com/economic_calendar/schema/)
documents `CalendarID`, UTC `Date`, `DateSpan` for timing precision, `Importance`,
`LastUpdate`, and actual/forecast/previous/revised fields. Reject unknown timing
precision for a narrow blackout until policy explicitly handles it. Currency labels
also need an explicit normalization map rather than assuming every value is ISO.
[Streaming](https://docs.tradingeconomics.com/economic_calendar/streaming/) and
[point-in-time access](https://docs.tradingeconomics.com/economic_calendar/point-in-time/)
are documented; the latter's actual as-of semantics and entitlement must be shown
with a corrected/rescheduled sample, not inferred from the product name.

Its [limits](https://docs.tradingeconomics.com/get_started/rate-limits/) include
1,000 calendar rows per call and a general two-request/second limit, with plan
limits also applying. Design explicit completeness checks and time/country
partitioning. At one request/minute, 30 continuous days require 43,200 calls for
one feed; three separate country calls would require 129,600 before retries or
news/search. These are planning calculations, not a purchased quota. Streaming
may reduce polling but adds reconnect/backfill qualification. The rendered
[pricing page](https://tradingeconomics.com/api/pricing.aspx) did not provide a
reliable applicable plan quote in this check; it did identify trial limits and
automatic renewal. Do not treat a trial as free or subscribe without authorization.

[FMP's calendar documentation](https://site.financialmodelingprep.com/developer/docs)
provides event and impact fields. Its [forex-news FAQ](https://site.financialmodelingprep.com/faqs?code=data)
describes daily updates, which does not establish the project's freshness target.
Its [published terms](https://site.financialmodelingprep.com/terms-of-service)
include personal-use, copying and termination/deletion restrictions. Persistent
replay/backups and any later model-assisted interpretation require an applicable
agreement resolving those restrictions before adoption.

## Completion gates before required-feed use

1. Freeze the source/event inventory: Fed/FOMC, ECB, BOJ, US inflation/jobs/growth,
   euro-area releases, Japanese releases and a declared unscheduled-news scope.
   Official central banks alone cannot cover this inventory. Source categories
   omitted from the initial product must be explicit; a partial feed stays optional.
2. Resolve retention/backup, attribution, derived analysis and AI-processing scope
   per source. Keep licensed content out of the public repository. Request a sample
   and written rights only if a paid fallback becomes necessary; no message is sent
   by this report.
3. Collect prospectively in a separate read-only environment. Preserve local
   first-observed/available times and immutable revisions. Compare scheduled events
   with official sources across at least one relevant release per selected category;
   quiet hours cannot validate release delivery latency.
4. Measure receipt latency, omissions, revised/rescheduled/cancelled events,
   ambiguous times/DST, pagination limits, throttling, stale/replayed responses,
   silence and restart/backfill. Record p50/p95/max and every miss. Do not invent
   latency from the age of an item found in a one-time feed download.
5. Predeclare source-specific polling, request budgets, maximum coverage age,
   release lateness and recovery criteria. A tentative 60-second collection cycle
   is a client schedule, not a publisher freshness guarantee. Required coverage
   remains unavailable until evidence supports the policy.
6. Verify identical timestamp and evidence semantics on Windows and Linux/Docker,
   including certificate validation, then connect an audited collector to the
   filter. PR #10's fixture input cannot simply be relabelled as qualified live data.

## Reproduce the bounded public preflight

```powershell
.venv\Scripts\python scripts/probe_public_feeds.py --output .local/provider-probe.jsonl
.venv\Scripts\python scripts/probe_public_feeds.py --sources fed --prior .local/provider-probe.jsonl --output .local/provider-conditional.jsonl
```

For Windows native certificate validation, install the pinned optional dependency
in a separate environment, never in either active broker observer's environment:

```powershell
py -3.14 -m venv .local/provider-venv
.local\provider-venv\Scripts\python -m pip install -r requirements-provider-probe.txt
.local\provider-venv\Scripts\python scripts/probe_public_feeds.py --sources ecb --tls-backend native --output .local/ecb-native.jsonl
```

The backend is explicit and a missing dependency fails instead of silently
falling back. The default backend remains Python's default verified context.

Create the output directory first. Each chosen source gets one request, with a
15-second socket timeout and a 2 MiB body bound, no redirects, retries or credentials.
The socket timeout is not a whole-job deadline. XML DTD/entity declarations and
non-feed roots are rejected. The tool writes metadata only, refuses overwrites,
keeps failures as evidence, and always reports `qualified_for_trading: false`.
It is a diagnostic script, not a scheduled collector or a source-health authority.
