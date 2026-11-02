# P0: broker and data feasibility

Research date: **2026-11-02**. Scope: the plan's British Columbia resident,
single-user, EURUSD/USDJPY, MT5-first deployment. The user has no existing broker
account and requested a shortlist. This is an interface-fit assessment, not a
ranking of investment returns or trading costs.

**Status: public-source research complete; P0 exit gate remains OPEN.** No account
has been opened, broker contacted, subscription purchased, terminal connected or
order submitted. Public documentation does not establish this user's acceptance,
account-specific Python permissions, or all required data-retention rights.

## Broker shortlist

| Candidate | Official evidence | Fit and unresolved conditions |
| --- | --- | --- |
| **FOREX.com Canada — first candidate to qualify** | The Canadian MT5 page offers live and demo accounts and describes automated EAs. [MT5](https://www.forex.com/en-ca/trading-platforms/metatrader-5/). CIRO lists GAIN Capital - FOREX.com Canada Ltd. as an investment dealer. [Directory](https://www.ciro.ca/office-investor/dealers-we-regulate?field_registration_category_target_id=All&page=9&sort_bef_combine_regulated_dealers=title_ASC&sort_by=title&sort_order=ASC). Its February 2026 corporate application states registration across Canadian provinces and territories. [Dealer document, page 19](https://www.filesandimages.com/Brand/forex/pdf/FXCA_Corp_Application_EN_20260206.pdf#page=19). | Best documented match in this review for the Canadian MT5-first route. Province-wide registration is supporting evidence, not confirmation of this individual's eligibility; the corporate form is not the user's account agreement. Confirm BC retail onboarding, exact Canadian MT5 demo/live offerings, Python use, history retention and demo expiry. |
| **Friedberg Direct, powered by AvaTrade — alternative to qualify** | Its Canadian site advertises MT5, MQL5 automation and custom EAs, identifying Friedberg Direct as a division of Friedberg Mercantile Group Ltd. [Canadian MT5 page](https://www.avatrade.ca/trading-platforms/metatrader-5). The same CIRO directory lists Friedberg Mercantile Group Ltd. | Plausible MT5 alternative. Confirm BC acceptance and the exact dealer/server, demo availability/expiry, Python access, and permitted data use. This review has not independently resolved provincial retail eligibility from the retrieved official pages. Do not substitute an offshore AvaTrade entity. |
| **OANDA Canada — reserve if changing the interface** | Canadian platform documentation describes MT4; OANDA separately publishes a trading API. [Canadian MT4](https://www.oanda.com/ca-en/platforms/metatrader-4/), [developer portal](https://developer.oanda.com/). | Potential direct-API alternative, not a verified Canadian MT5 route. Canadian API entitlement, province/account eligibility, and practice/live account capabilities need separate qualification. Choosing this route would require an explicit change to the MT5-first plan. |

Recommendation: qualify **FOREX.com Canada's MT5 demo** first, retaining Friedberg
Direct as the alternative. This recommendation is based on the documented
interface/dealer fit above. It does not imply that Python automation is already
approved or that a funded account should be opened now.

FOREX.com also advertises a REST API requiring a standard account and a support
request. Do not assume that this API operates the same MT5 account or provides a
demo endpoint without confirmation. [Canadian API page](https://www.forex.com/en-ca/trading-tools/api-trading/).

## Technical findings affecting M1

MetaQuotes documents Python calls for account/terminal information, symbols,
quotes/bars, positions and order/deal history, alongside execution calls. The
published Python function list does not expose the MQL5 economic-calendar or
terminal-news APIs; a calendar/news route therefore needs separate qualification.
[Python integration reference](https://www.mql5.com/en/docs/python_metatrader5).

The MQL5 calendar is a separate interface and uses **trade-server time**, not the
computer's local timezone. A future calendar bridge must retain original time,
explicitly convert to UTC and test DST and server-offset changes; it cannot assume
that Python quote timestamps establish calendar timezone semantics.
[Calendar reference](https://www.mql5.com/en/docs/calendar).

The reviewed MetaTrader5 5.0.6231 release publishes Windows x86-64 wheels including
CPython 3.14 and 3.11. Keep it in a separate Windows gateway environment; there is
no reason to add it to the portable core image. Wheel availability is not proof
that a particular broker terminal build works: pin and test that combination in
M1. No package or terminal has been installed by this research.
[Published distribution files](https://pypi.org/project/metatrader5/).

## Calendar, news and search candidates

| Role | Candidate and evidence | Qualification needed |
| --- | --- | --- |
| Scheduled events | Trading Economics documents calendar streaming with UTC release time, event IDs, importance and revision-related fields. [Streaming schema](https://docs.tradingeconomics.com/economic_calendar/streaming/). It also advertises point-in-time calendar data. [Calendar API](https://tradingeconomics.com/api/calendar.aspx). | Request a USD/EUR/JPY sample and a quote covering automated use, local retention, replay, revisions and backup. Verify timezone, latency, quotas, outage behavior and whether PIT is included. `previous`/`revised` fields alone do not prove an immutable historical revision feed. Not selected or purchased. |
| Calendar alternative | MT5 MQL5 calendar, via a deliberately designed read-only bridge. [Reference](https://www.mql5.com/en/docs/calendar). | Confirm broker availability and permitted use, qualify timezone handling and restart/change-ID semantics, and verify retention rights. This adds an MQL5 component; it is not a Python API shortcut. |
| USD official announcements | Federal Reserve RSS feeds. [Feed directory](https://www.federalreserve.gov/feeds/feeds.htm). The Board generally permits reuse of its own website information, with attribution and exceptions for third-party material and protected marks. [Policy](https://www.federalreserve.gov/disclaimer.htm). | Start with attributable Board text/metadata; check item-specific exceptions. Measure publication-to-observation delay. This is a policy-announcement source, not complete USD news coverage. |
| EUR official announcements | ECB RSS. [Feed directory](https://www.ecb.europa.eu/home/html/rss.en.html). Reuse has conditions and exceptions, including author-named publications. [Copyright](https://www.ecb.europa.eu/services/using-our-site/disclaimer/html/index.en.html). | Document permitted fields, attribution, transformations and retention for the chosen feed before enabling collection. No blanket full-text scraping permission is assumed. |
| JPY official announcements | BOJ distributes update dates/titles through RSS. [Website services](https://www.boj.or.jp/en/tips.htm). Its copyright policy has commercial-use and other exceptions requiring prior permission. [Policy](https://www.boj.or.jp/en/about/copyright.htm). | Resolve whether the proposed automated trading/research use and storage require permission. Until resolved, do not designate BOJ content as an approved retained feed. |
| Bounded source discovery | Brave Search API is a candidate; its FAQ requires a plan with storage rights for retaining results. [API](https://brave.com/search/api/). | Obtain explicit storage entitlement, current price/quota and allowed use. Search-result access does not establish rights to archive publisher articles. Apply a source allowlist and persist query/observation provenance. No key or paid plan is configured. |

Inference: official central-bank feeds are useful initial evidence sources, but
cannot establish comprehensive unscheduled FX news coverage or a low-latency
service guarantee. Broader licensed news remains an open provider decision. The
broker's advertised in-terminal Reuters news likewise does not establish Python
retrieval or retention rights. Do not mark the required news-health gate satisfied
merely because a calendar or terminal news panel is present.

No subscription budget was supplied, so this review does not select paid tiers or
claim a total monthly cost. Preserve the existing fail-closed data-health policy
while required sources or rights remain unresolved.

## Broker confirmation request — prepared, not sent

Send to the selected Canadian dealer's official support channel after selecting
the candidate. Do not include passwords or identity documents in the repository.

> I am evaluating a personal automated EURUSD/USDJPY system as a British Columbia
> resident. I want to begin with a separate MT5 demo account and read-only
> observation, with no live trading at this stage. Please confirm:
>
> 1. Your Canadian legal entity, BC retail eligibility requirements, and availability
>    of distinct MT5 demo and eventual live accounts under that entity.
> 2. Whether the official MetaTrader5 Python package may connect to your Windows
>    terminal for account, quote/bar and history reads, and later automated orders;
>    any account-specific restrictions, polling limits or separate approval.
> 3. Whether investor/read-only access works for the required observations; demo
>    expiry, renewal, server names and history retention.
> 4. EURUSD/USDJPY symbol identifiers, account currency, netting/hedging mode,
>    minimum volume/step, commissions, margin, execution/filling modes, stop/freeze
>    constraints, session/rollover times and initial stop-loss support.
> 5. Permission to retain quotes, bars, execution history and available news/calendar
>    evidence for private research, replay and encrypted backups across my hosts;
>    restrictions on derived analytics or later model-assisted interpretation.
> 6. Whether any supplied calendar/news feed has an officially supported extraction
>    route and separate licensing, and what limitations apply to demo data/fills.

The answer must be retained privately with date, dealer and applicable terms;
record a redacted evidence reference in the project, not personal account details.
Broker confirmation does not replace observation of actual terminal capabilities.

## P0 exit record

| Gate | Current status | Evidence to close it |
| --- | --- | --- |
| Candidate list and interface route | Researched; FOREX.com Canada proposed | User selection or a better qualified candidate |
| BC eligibility and account-specific MT5/Python permissions | Pending | Applicable Canadian dealer terms/support confirmation and successful demo provisioning |
| Separate PAPER/demo and eventual LIVE identities | Pending | Verified account types and dedicated terminal/server configuration; no live credentials needed now |
| Economic calendar route | Candidate identified, not qualified | Licensed sample, timestamp/revision tests and quota/retention terms |
| USD/EUR/JPY news plus bounded search | Candidate sources identified, rights/coverage incomplete | Source-by-source rights, coverage, allowed retained fields and budget |
| Actual account/build capabilities | Not observed | M1 read-only evidence from the selected demo terminal |

P0 remains open until there is a viable, permitted account/interface and explicit
provider/deployment constraints. Never treat this document as a broker approval
record. The subsequent M1 observations validate the account/build properties that
cannot be established from public documentation. See [M1 handoff](m1-handoff.md).
