# Design migration and milestone acceptance

2026-11-03; subordinate to the [canonical architecture](architecture-plan.md).
This is a documentation migration, not an implementation or qualification result.

## Inspected baseline

Inspected `arthurcui/fx-talanta` main at
`adc864017d29eca0b3dd1769164171a2a26b0fd9`, after authorized squash merges of
PR #13 (`5998a39`) and #14 (`adc8640`). GitHub returned no open PRs at task start.
The external handoff's older `c9b2e435` / draft PR #13 baseline is superseded.
Use this repository's canonical plan, ADR and handoffs without an external page.

Implementation inspected: immutable Pydantic records and account identity;
append-only PostgreSQL roles/migrations/repository; scripted decision and advisor
fixtures; `domain/offline.py`, `risk/governor.py`, `gateway/offline.py`, simulator
and durable store; observer, provider, calendar and campaign documentation/tests.
The governor explicitly uses USD. Current CAD/hedging demo bindings do not prove
CAD sizing parity. FastAPI, React, bounded production AI, a fixed execution EA and
connected order execution remain planned. No service is installed by this design.

### Preserved qualification findings

| Evidence | Actual conclusion | Consequence for redesign |
| --- | --- | --- |
| [CMC and FOREX report](broker-campaign-conclusion.md) | CMC v2 halted INVALID_DATA: 441 records, 438 complete, 394 fresh; exact trigger unproven. FOREX v2 user-stopped: 1,720 records, 1,718 complete, 1,485 fresh; freshness gate already unattainable | Neither passed sustained acceptance. Preserve earlier failures, original IDs/deadlines, DB reconstruction and missing final receipts; no attribution of CMC failure to stale ticks or clock without evidence |
| [Provider report](provider-campaign-conclusion.md) | Eight feeds stopped after 166/288 polls each; full coverage and delivery qualification not passed | Keep original requirements and 16 category gaps; do not treat transport success as coverage |
| JOLTS in provider report | Exact scheduled URL first received 224.73375 seconds after scheduled time: ON_TIME; parsed publication age 2,588.76575 seconds exceeds the 360-second delivery criterion | Preserve both measurements, unproven discrepancy and missing raw feed bytes; do not replace one metric with the other |
| [Native MCP calendar](native-mcp-calendar.md) | Bounded read-only import/time mapping/replay evidence; native IDs/cursor and revisions supported; no prospective full qualification | Optional shadow calendar adapter, not automatically required-source or execution authority |
| Manual BLS / FRED | Manual ICS import and reminder; direct BLS refresh had 403 failures; FRED date-only corroboration | Retain upload path/provenance and unknown-time handling; no resurrected calendar EA/service or automated browser downloader |

The active campaigns were concluded at the owner's request before this redesign.
Keep their frozen source checkouts, private journals/configuration, historical
records and public `docs/evidence` files unchanged. Any future active campaign uses
its own frozen source/environment and original gates; development takes place in
a different checkout. This PR never starts, resumes or extends a campaign.

## Old-to-new migration map

All paths below are repository-relative. “Planned” is deliberately not a claim
that the target implementation exists.

| Existing component/path | Retain | Change in responsibility / planned addition | Evidence or migration requirement |
| --- | --- | --- | --- |
| `domain/models.py`, `storage/repository.py`, `storage/migrations/` | Immutable account-scoped records, links, corrections and existing migrations | Add protocol-versioned EA messages separately; never rewrite historical kinds | M0A identity/append-only/replay tests remain; explicit compatibility mapping for later additive migration |
| `agent/scripted.py`, `clock.py`, `fixtures.py` | Scripted decision source, fake clock and M0A fixtures | Future completed-bar scheduler, B01 candidate registry and bounded provider-neutral model adapter | Fixture evidence remains synthetic; no claim of production AI or strategy profitability |
| `domain/offline.py`, `risk/governor.py` | USD Decimal policy/reference, risk budgets, cash-flow-adjusted baselines | Backend eligibility plus independently enforcing EA; additive CAD contract/rounding/conversion parity | Keep original risk mandate; shared USD/CAD vectors and later actual terminal comparison |
| `gateway/offline.py`, `brokers/simulator.py`, `storage/offline.py` | Simulator-only mutation, checkpoints, lost-response/protection and DB-session fencing | New backend dispatch and separate fixed EA; do not convert simulator gateway into a Python broker writer | Existing M0B tests remain behavioral oracle; DB fencing does not fence real terminal |
| `brokers/protocol.py` | Observation and simulator execution protocols | A separate EA message protocol, not a production Python `mutate()` adapter | No connected mutation can hide behind an enabled generic adapter |
| `observer/mt5.py`, `observer/supervisor.py`, `observer/runner.py`, `observer/acceptance.py` | Read-only snapshots, supervision, quote readiness and campaign evidence | Future EA health corroboration remains distinct from observer and entry freshness | Preserve five-second observation/two-second entry ceilings, failed campaigns and exact clock provenance |
| `news_filter.py`, `provider_pipeline.py`, `provider_campaign.py` | Reusable filtering/journal/validation and timestamp distinctions | Qualify scoped required/optional provider coverage, exact revisions and availability | Existing eight-feed campaign is insufficient; new evidence must meet unchanged predeclared gates |
| `bls_calendar.py`, `fred_calendar.py`, `manual_bls.py` | Manual ICS archive/upload/reminders and date-only corroboration | Official schedule reconciliation with exact/approximate/unknown times | No invented release times or automatic refresh reliability claim |
| `mcp_client.py`, `mcp_calendar.py` | Qualified-tool allowlist, native read-only shadow import and cursor deduplication | External capability isolation and additional bounded prospective qualification | Preserve failed initial global-cursor attempt and subsequent successes; no runtime MCP order/MetaEditor tools |
| `advisor/fixtures.py` | Exact scripted bilingual record fixtures, no execution | Planned typed authenticated reads and administrative command router via backend/EA | Real authentication/UI not implemented; same IDs, negation, ambiguity and wrong-account cases must fail closed |
| `storage/archive.py`, `docs/m0c.md`, `deploy/`, `scripts/` | Native/Docker/task packaging and verified offline export/restore | Future EA journal backup, Windows supervision and host fencing; local/cloud private route | M0C restore does not establish terminal ownership transfer or execution restore |
| Proposed `mql5/`, execution contracts/dispatch, releases and `apps/dashboard/` | No existing production component to replace | Fixed EA, compatible release manifest, FastAPI/Pydantic API, React/TypeScript UI | Stage as new bounded increments; never imply availability from documentation |

The observer/calendar rows describe the actual module inventory; supplemental
operating documents retain their historical commands as reproduction references,
not standing authorization. No root checkout or collector environment is changed.

## Milestone acceptance

Each gate records source/configuration/fixture or dataset hashes, environment,
account provenance (privately), execution timestamps, failures and review result.
CI is engineering evidence only. “Evidenced” is bounded to what was exercised.

| Milestone | Implemented / evidenced | Failed or open | Planned exit criteria and artifacts |
| --- | --- | --- | --- |
| M0A | Immutable typed records, account-bound PostgreSQL, scripted news/chat and decisions; fixture/integration tests | Not real authentication, AI or execution | Preserve append-only and temporal-link/account-isolation suite plus original fixture evidence |
| M0B | USD risk, reservations, simulated orders/fills/protection, unknown recovery and durable loss state | No CAD/native-broker parity; five-second protection timer is fixture-only | Keep restart/concurrency/partial/unknown/loss tests passing; no regression during additive protocol work |
| M0C | Native/container/task parity, isolated roles, archive/blocked restore | No execution EA supervision or host fencing | Preserve existing profile and restore checks; later EA/host transfer has a distinct gate |
| P0 | CMC first, FOREX comparison; demo bindings observed | Dealer/BC permission, data rights, broker costs/capabilities and deployment evidence need account-specific completion | Dated exact dealer/account/interface/use permission and limitations; LIVE separately scoped |
| M1A broker observation | Bound read-only observer, clock preflight, v2 runner, reconstruction | CMC INVALID_DATA cause unknown; FOREX freshness failure; no sustained acceptance | New authorized frozen plan only after defects/preflight; independently reconcile committed observations and final receipt; separate collector health/freshness and preserve unchanged gates |
| M1B calendar/news integration | Manual BLS UI/journal, FRED, direct feeds, optional native MCP import/filter | Broader news, USD/EUR/JPY categories, rights, exact time normalization and revisions/recovery remain open | Source inventory marks required/optional scope, unknown times and age; dedup/revision/cutoff tests and official calendar reconciliation for each required category |
| M1C prospective qualification | Eight-source campaign and exact JOLTS schedule match, bounded MCP evidence | Stopped campaign; failed sampled publication metric; other sources lack prospective items | Predeclared cadence/success/gap/latency and prospective releases, revision/reconnect evidence, category coverage and intended-use rights; no items means insufficient, not pass |
| M2A intent + EA protocol | [Offline M2A contracts, fixtures and source harness delivered](m2a-protocol.md) | Native parity not run; production dispatcher absent | Versioned DecisionIntent, ExecutionRequest, ExecutionAck, ExecutionState, ReconciliationResult; fixture hash/replay/account/expiry tests and reference vectors; no mutation |
| M2B fixed EA execution | [Native implementation and bounded Tester evidence delivered](m2b-fixed-ea.md) | Tester-only; no connected writer, production transport or complete risk engine qualified | Account/quote/volume validation, market order and SL/TP code, OnTradeTransaction, order/deal/position reconciliation, duplicate protection; source/EX5 hashes and actual native evidence; connected execution remains disabled pending M2C/M2D |
| M2C deterministic safety | [Offline USD/CAD safety, 56 native risk parity cases and 52 native control assertions delivered](m2c-deterministic-safety.md); original USD governor preserved | Real snapshot/cost sourcing, authenticated deployed transport, multi-host fencing and end-to-end shadow/protection timing remain unqualified; connected sending disabled | Per-trade/aggregate risk, daily loss, hard drawdown, margin/currency limits, blackouts and stale quote/news/calendar veto; shared USD/CAD native vectors; state precedence, bounded protection, journal/fencing and isolated no-order shadow evidence |
| M2D connected PAPER acceptance | [No-order integration harness and short existing-demo capability captures delivered](m2d-no-order-acceptance.md) | Connected acceptance remains open: P0/M1, M2A–C connected gates and explicit demo-order authorization pending | Actual demo tests: lost response, partial fill, SL rejection, terminal restart, backend/DB loss, stale quote, duplicate intent, wrong account, unexpected position and closed-market exit; actual broker reconciliation and protection timing artifacts |
| M3 B01 replay | Rules documented, simulator reusable | Signal engine/realistic backtest not implemented | Frozen EMA/ATR seeding, bid/ask/session/DST/cutoff conventions; chronological walk-forward and untouched holdout; commissions/slippage/swap/gaps/partials and conservative ambiguous intrabar handling |
| M4 AI/advisor | Typed scripted records only | Production models, auth, typed queries/commands pending | Provider-neutral OpenAI-first implementation, schema/latency/spend/HOLD tests, qualified-memory cutoff, bilingual command safety and evidence-grounded explanations in simulation |
| M5 forward PAPER | Not started | No strategy economic evidence or dashboard | At least 8 weeks AND 100 closed trades; matched AI/no-AI and AI/news/no-news snapshots, separate ledgers, costs/latency, paired uncertainty and preregistered economic thresholds; dashboard/admin/recovery gates also pass |
| M6 capped LIVE | Disabled | Capital, release and actual account qualification absent | Exact compatible evaluated release, explicit capped mandate, fresh binding/capabilities, independent risk/ledger, tested rollback/fencing/restore; operational AND economic gates |
| M7 controlled evolution | Not implemented | No autonomous promotion qualified | Challenger preregistration, counterexamples, failures retained, out-of-sample and prospective evaluation, immutable promotion/rejection record; no risk-authority expansion |

Owner-approved November 3 order: **carry M1 gaps → implement M2A/M2B → resolve
connected-operation gates and prove M2C/M2D → freeze
M3 baseline → add AI in M4 → run unattended PAPER M5 → qualify M6 LIVE**.
M2D now also has [shadow delivery code and bounded native/HTTPS evidence](m2d-shadow-transport.md).
Its PostgreSQL shadow journal and native receipt outbox do not qualify connected
execution, production fencing, native HTTPS or current broker snapshot/clock sourcing.
The [bounded no-order connection work](m2d-connected-no-order.md) adds actual FOREX
inputs, conservative clock intervals and account-authority/paired-restore tests.
Its real observations remain HOLD. Earlier attempts did not complete the receipt
handoff; PR #21 subsequently completed two native HOLD receipts and two signed ACKs,
with independent journal/database verification. The [remediation report](m2d-lifecycle-remediation.md)
preserves the original failures. The [consolidated disabled integration](m2-disabled-integration.md)
adds the composed safety/receipt/recovery route and retained operating artifacts.
Neither increment qualifies broker execution, providers or source timestamp mapping.
No broker execution or sustained campaign is authorized by these changes.
M1A/B/C remain internal observation/provider/qualification workstreams under M1.
M0A–M0C remain completed within their offline scope. The November 3 owner decision permits offline M2A while M1 evidence gaps remain;
it does not turn old failures into passes or authorize connected orders.

M2B develops execution capabilities with broker submission disabled in deployed
environments; it cannot precede safety qualification with real orders. Native
build/Tester and isolated read-only shadow are retained as evidence prerequisites
within M2B/M2C, not renamed milestones. M2D requires M1 and M2A–C gates plus
explicit demo authorization. New code cannot certify old failed runs.

M3 tests B01 before M4 tests AI's incremental value. M5 prospectively compares
**B01 vs B01 + AI filtering vs B01 + AI + news**, using matched observations,
common safety gates and separate ledgers. Eight weeks AND 100 closed trades is
only the sample floor, never sufficient LIVE qualification by itself.

## Boundary test matrix

| Boundary/scenario | Environment | Expected behavior | Required artifact / prerequisite |
| --- | --- | --- | --- |
| Contract/currency/TTL/account/hash errors and replay | Portable fixtures | Reject invalid work; duplicate returns prior status; no double risk | M2A schemas, reason codes, hand-derived USD/CAD vectors, existing M0 suite |
| Independent Python/MQL5 risk parity including min lot, partials, costs and cash flows | Native compiler + fixture Tester | Identical bounds/rejections after specified rounding; disagreement blocks | M2B compiled artifact/build hash plus M2C safety parity outputs; Python-only results insufficient |
| Lost acknowledgment/restart/cancel/close uncertainty | Simulator first, then separately authorized demo | Preserve reservation, no blind retry or reversal; positive evidence reconciles | Submitted journal and broker history/stop evidence; M2D prerequisites |
| Wrong login/server/build, cross-account payload and second writer | Isolated shadow/host test | No orders; deny mismatched route/manifest; replacement blocked until predecessor fenced | Host/terminal fencing evidence, authenticated channel and capability snapshot |
| WebRequest timeout, event burst, network/DB/local-disk loss | Native harness and shadow before demo | Bound protection delay, no entry without durable journal; explicit uncertainty; broker stops distinguished from terminal exits | Predeclared timing budget, measured worst-case results, fault journal; isolated worker if inline transport fails |
| Rejected initial SL, partial fill without SL, stop/freeze limits, market closure | Qualified broker-demo only | Block all entries, bounded repair/controlled exit; never strip SL and retry blindly | Broker-specific measured submission-to-protection and exit/escalation deadlines; actual retcodes/deals/stops |
| Required input outage, stale ticks, date-only calendar, revisions/replayed feed | Fixtures then prospective read-only capture | Required entry scope blocked; collection may continue; no fake refresh/future evidence | Frozen category/source policy and receipt/publication/event/availability evidence; unchanged qualification gates |
| Advisor ambiguity, negation, injection, replay and account view change | Simulated authenticated commands | No unintended mutation; pause/resume respect state; explain unknown accurately | English/Chinese paired cases and deterministic numeric query references |
| Restore, rollover and rollback with open/unknown positions | Offline first; isolated shadow/demo later | Preserve losses/reservations, no dual writer, originating exit rules retained | PostgreSQL plus EA journal restore, fence/hand-off proof; never copied PAPER state into LIVE |
| AI/news value and lessons | Replay + prospective separate PAPER ledgers | Same cutoffs/risk gates; no look-ahead, provenance mixing or duplicate-signal sample inflation | Frozen datasets/models/prompts/providers/lessons, matched arms, paired uncertainty, full costs and preregistered criteria |

Operational correctness, policy compliance and economic outcome are independent.
Label replay, forward simulation, shadow, broker-demo and live records distinctly.
Copying the same signal into multiple arms does not create independent trades.
No acceptable economic sample means remain PAPER; no per-loss automatic risk tuning.

## Design review checklist

* Canonical authority is consistent across architecture, advisor, deployment and
  handoffs: fixed EA mutates connected brokers; Python simulator stays offline.
* Numerical risk and five-/two-second distinctions are unchanged; CAD and native
  parity gaps, unknown outcomes and transport limits remain explicit.
* Historical evidence files and frozen campaigns are unchanged; no runtime source,
  migrations, dependencies, workflow names, terminal or broker state is modified.
* Documentation links/anchors and diff whitespace pass; required **M0A checks**
  are inspected on the design PR. CI does not certify providers or economics.

## UI milestone acceptance: quote latency and channel status

| Milestone | Required deliverable | Acceptance |
| --- | --- | --- |
| M2A | Read-only EA/Python-package/MCP telemetry schema | Scoped source/capability, tick age, local delay and health remain distinct; missing metrics explicit |
| M2B | Channel telemetry producers | EA heartbeat and quotes separate; Python and MCP health identifies actual capability |
| M2C | Failure/freshness scenarios | Healthy heartbeat plus stale quote still blocks entry beyond two seconds; disconnect/recovery cannot erase provenance |
| M4 | Authenticated advisor/read API | Explanations identify source, window and unavailable metrics without execution authority |
| M5 UI | Quote-latency panel and three channel cards | Show active source, quote age, measured median/p95 delay, last heartbeat/read, errors and entry-block reason; calendar-only health never implies healthy quotes |
