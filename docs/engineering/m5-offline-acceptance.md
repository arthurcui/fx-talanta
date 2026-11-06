# M5 offline engineering acceptance and remaining gates

This is the current engineering acceptance index. The sections below retain the
chronological implementation evidence; their original limitations describe those
individual deliveries. This matrix supersedes their old "not implemented" wording.
**Full M5 remains OPEN.** Trading is disabled; software tests do not supply candidate
qualification or elapsed PAPER evidence. No new campaign is authorized.

## Capability and evidence matrix

| Requirement | Implemented and tested | Remaining boundary |
| --- | --- | --- |
| Owner workspace access | HTTPS owner sign-in, salted password verifier, HttpOnly cookie, CSRF, logout/restart revocation, request-idle and absolute expiry; legacy private local launch | Single owner only; actual remote deployment, credential lifecycle/SSO and operating acceptance are not qualified |
| Quote latency and channels | EA/Python/MCP health dimensions, exact-bound current demo read receipts, native-calendar timestamp mapping and host clock proof, aging/invalid/expired receipts | Recorded sampling, not execution readiness or sustained broker qualification; two-second entry rule unchanged |
| Decisions, risk and outcomes | Searchable evidence projections, explicit-reference trails, original rationale, hashes and cutoff | Historical evidence alone never reconciles present broker exposure |
| Broker state | Separate current demo inspection receipts for balances, positions, orders and protection; missing/stale/invalid receipts fail closed | UI does not attach MT5; complete connected fault matrix and unattended recovery remain unqualified |
| Advisor and learning | English/Chinese cited evidence reader, optional bounded M4 model selection, durable call reservations/results and qualified-memory filtering | No unrestricted model commands, automatic strategy promotion or profitability claim |
| Calendar/news | Manual BLS import/reminder, events/cancellations, news and health evidence | USD/EUR/JPY coverage/timeliness/reliability gaps retained |
| Administration | Separate simulator capability, preview/confirmation, pause/resume/owned-close/flatten-halt, uncertainty reconciliation | No broker commands or strategy activation through this dashboard |
| Monitoring/recovery | Background inspection, local spool/acknowledgment, [optional bounded HTTPS receiver delivery](m5-alert-delivery.md), durable uncertainty/reconciliation and stopped backup/restore | Receiver acceptance is not human acknowledgement; real destination delivery and deployment remain unqualified |
| Deployment boundary | Explicit HTTPS and mutual-TLS remote access, exact Host/Origin, bounded requests, [pinned inspection launch and recovery preflight](m5-deployment-readiness.md), source-backed tests | Actual remote deployment and full operational acceptance remain open |
| Matched comparisons | [Incremental simulation runner](m5-paper-runner.md), offline study upload/validation plus [frozen registration and durable receipt workflow](m5-matched-workflow.md), corrections, restart/idempotency and read-only dashboard projection | No qualified prospective source/model adapters, eligible candidate, qualified costs or economic promotion verdict |
| Reproducibility | One source-hashed backend/headless-browser acceptance command; all earlier evidence retained | Software PASS never closes unattended PAPER gates |

The [source-hashed Windows local acceptance report](../evidence/m5-local-offline-acceptance-20261106.json) records **48 backend tests and two browser
tests passed, zero skipped**. CI reproduces the same entry point after installing
pinned browser tooling and also runs the complete integration/container/profile
suite. Its artifact is `m5-offline-engineering-acceptance`; browser screenshots remain
in `m5-dashboard-browser-evidence`. Required branch-protection check names are unchanged.

## Reproduce without brokers or desktop control

```powershell
$env:PYTHONPATH = "src;."
# Once, from tools/dashboard-tests: npm ci; npx playwright install chromium --only-shell
python -m tools.qualification.m5_acceptance --output .local/m5-acceptance-new.json
python -m fx_talanta.evaluation.matched --input tests/fixtures/m5/matched-study.json --output .local/m5-comparison-new.json
```

The acceptance command starts only isolated loopback HTTP servers and headless test
browsers. It uses synthetic data, no broker credentials or external model calls.
Existing output paths are refused. Missing browser tools, test failures or skips
produce an incomplete/failed verdict, never an acceptance pass.

The [committed comparison result](../evidence/m5-synthetic-comparison-20261106.json)
and its input fixture are explicitly SYNTHETIC. Its three outcomes and
costs demonstrate arithmetic and validation, not measured trading performance.
`NO_AI` has no model/prompt/news content; `AI_NO_NEWS` and `AI_NEWS` share the same
policy/model/prompt family, differing in news content. Safety is common across all
arms, including calendar blackouts, required-feed checks and risk policy. Hashes are
supplied metadata and are not independently verified by this evaluator. Separate
ledger names are logical simulation identities, not additional broker accounts.

The input freezes candidate/dataset/criteria/features/lessons/news interpretation
and an as-of cutoff. There is one decision per snapshot per arm and each decision
ID is unique. All decisions in a matched group must precede its earliest known
outcome. Missing arms, costs and outcomes (including outcomes after the cutoff)
remain excluded counts, never zero returns. Differences use gross P&L minus supplied
all-in cost, in USD only. Mean/range are descriptive; no confidence interval is
manufactured for dependent/sparse samples. The evaluator does not send orders,
collect evidence, count broker closed trades or establish elapsed observation time.

## Exact remaining M5 scope

1. **Connected operations qualification:** read-only current demo capture and quote
   display are implemented. Complete connected recovery/failure acceptance and
   independently qualified inputs remain open; historical receipts do not prove
   present reconciliation. Broker administrative integration remains unavailable.
2. **Deployment/operations:** owner sign-in and mutual-TLS access are implemented.
   Optional bounded receiver delivery is implemented; actual remote deployment,
   real-recipient delivery acceptance and broker-scoped safe
   administration/protection still require dedicated implementation and acceptance.
3. **Evaluation:** matched offline validation, durable registered receipt workflow
   and bounded model inspection are implemented. The incremental simulation runner and typed local input integration are implemented.
   Qualified prospective source/model integration, an eligible frozen candidate, qualified
   cost/latency evidence and predeclared uncertainty/economic review remain open.
4. **Unattended PAPER:** applicable M1–M3 prerequisites and explicit strategy
   authorization must precede at least **eight weeks AND 100 closed trades per
   candidate**, with the specification's operational/economic gates. No campaign,
   threshold reduction or promotion is authorized here. M6 remains blocked.

These are substantive remaining gates, not pending CI checks. The owner-access
change closes a UI access gap; it does not rename the whole milestone "complete".

B01 stays REJECT_FOR_PROMOTION. Failed/stopped qualification records are preserved.
The dashboard's readiness matrix lists these requirements instead of treating a
passing software suite as operational qualification.

## Consolidated read-only integration

The dashboard now connects optional bounded M4 model selection, immutable local
call reservations, offline study upload/results, sampled incident alerts, optional
loopback TLS, and an explicitly bound PostgreSQL observation reader. See the
[operator setup](../guides/dashboard.md#optional-read-only-integrations).

The model adapter persists reservations and results in the isolated inspection
SQLite journal, reusing M4 request/response validation. It does not expose the
M4 execution gateway. A request ID binds its input and evidence; retries reuse
results, pending/uncertain calls remain spent across restart, and a changed budget
cannot silently reset that journal. Model calls run outside the journal lock.
A provider failure returns HOLD. Free-form model prose is not shown: the model
selects allowed citations and the server renders the original evidence.

The PostgreSQL reader verifies the configured demo account, disabled source binding,
run and terminal binding hash on each request. It opens a read-only transaction with
connection/query timeouts. The separate panel displays captured balances/protection
and original timestamps, never current reconciliation or entry readiness. It neither
starts collectors nor connects to terminals. Historical broker data is not supplied
to model chat or mixed into the simulator snapshot. Missing/latest failed evidence
is not replaced with an older successful record.

Local alerts are in-page sampled changes only; they do not prove background or
external notification delivery. TLS is optional and loopback-only, using explicitly
supplied certificate files without installing trust or enabling remote access.
These integrations do not close the four operational requirements above.


Consolidated local evidence: [65 backend checks and four headless browser flows](../evidence/m5-readonly-integration-20261106.json).
These tests use synthetic model responses and broker projections, plus actual
loopback HTTP/TLS. No external model or broker call occurs in this harness.
`tests/test_m5_broker_postgres.py` separately verifies PostgreSQL read-only enforcement
and unchanged committed records against a disposable CI database. It is part of the
full Engineering checks job, not the local offline report.


## Simulator operator and recovery integration

The operator panel integrates M4's actual offline Gateway/Simulator with a distinct
capability, exact account/run, server-created preview, explicit confirmation, original
market freshness and state-version checks. Request-start and result receipts survive
restart in the inspection journal; uncertain confirmations never redispatch. Viewer
chat, model responses, broker-view identity and inspection tokens grant no authority.
There is no entry/proposal route. Reconciliation and protective management are
simulator-only. Tests verify confirmed simulated close, no duplicate close, resume
restrictions, expiry/staleness, changed-state rejection, interruption/restart, HTTP
authorization, cross-origin denial and session revocation.

Stopped-state backup/restore verifies SQLite integrity and per-file digests. The
restore marker permanently restricts the restored launch to inspection: no model-call
budget duplication or copied simulator authority. Active-workspace backup, overwrite,
path traversal, corrupt archives and incomplete restores fail closed. These tests
qualify local engineering recovery, not remote deployment, broker recovery, continuous
notification delivery or unattended PAPER. Existing failed evidence and B01 remain.


[Local operator/recovery acceptance evidence](../evidence/m5-operator-recovery-20261106.json)
records 74 backend checks and five headless browser flows, all passed with no skips.
These use synthetic markets and the real offline simulator, not broker accounts.
`tests/test_m5_operator_postgres.py` additionally runs in CI against a disposable
PostgreSQL database to verify confirmed simulated closure and no redispatch after
reopening the durable gateway and inspection journal. No existing campaign or
broker terminal is involved.


## Inspection service and access integration

The service worker samples configured inputs independently of browser requests and
persists heartbeat/incident evidence. The durable local notification queue verifies
immutable spool files, preserves conflicts, survives restart and retains explicit
acknowledgments. No external message transport is claimed. Backup/restore retains
these files and receipts while preserving the inspection-only restore boundary.

Optional remote inspection requires client-certificate mutual TLS, the viewer bearer
capability and exact origin validation. Remote operator configuration is rejected;
there is no remote broker/strategy authority. TLS handshakes are bounded and isolated
from the accept loop. Tests use loopback only and verify missing/untrusted client
certificates, invalid bearer, wrong origin/Host, expired session and a stalled TLS
client. The certificate fixture includes proper CA key usage; verification is not
weakened to make tests pass.

Remaining deployment acceptance includes the actual target host/ingress, certificate
issuance/revocation, supervision, resource limits, external alert delivery if required,
and current broker collector/protection integration. The local service's recent
heartbeat is not sustained acceptance and does not close M1–M3 gaps or M5's eight-week
AND 100-closed-trade gate. No campaign or remote deployment follows from this PR.


[Committed service/access evidence](../evidence/m5-service-access-20261106.json)
records 90 backend checks and six headless browser flows passing with zero skips.
It covers no-browser sampling, delivery/restart idempotence, failed/conflicting
local files, multi-page backlog, persisted acknowledgment, backup/restore, worker
failure/shutdown, mutual TLS and separation of remote inspection from local operator
configuration. Certificates are ephemeral test files; no certificate or remote
listener was installed on the owner's host.

## Operating acceptance checkpoint — November 6

The [local acceptance report](../evidence/m5-operating-local-20261106.json)
contains 94 passing backend checks and six passing headless browser flows, with
zero skips. It includes independent broker-health dimensions and a no-browser
journal outage/recovery test with durable notifications and restart idempotence.
These are fixture-driven integration results, not observations of a running broker.

The [actual saved-binding preflight](../evidence/m5-operating-preflight-20261106.json)
rejected FOREX.com's expired clock policy. The policy ended November 4 at 00:00 UTC;
the check ran November 6. The original binding remained byte-for-byte unchanged.
The SDK was not initialized, no account was sampled, and no order was submitted.
No clock-policy extension, desktop interaction or new campaign was performed.

| Acceptance item | Result |
| --- | --- |
| Browser-independent inspection and local notifications | Local integration passed |
| Separate journal transport, clock policy and quote freshness | Local integration passed |
| Journal outage/recovery without promoting quote readiness | Local integration passed |
| Current FOREX account and quote observation | Not performed: expired clock evidence |
| Independent current broker timestamp mapping | Still required |
| Remote host deployment and external notification delivery | Not performed |
| Sustained unattended PAPER / full M5 | Not qualified |

To close current-broker operating acceptance, independently establish a new bounded
timestamp mapping, then capture through an isolated read-only observer and verify
the dashboard against those committed records, including loss and recovery of that
input. Preserve the original failed campaigns and expired configuration. Merely
changing the policy's expiry or receiving a recent file cannot satisfy this check.
The two-second entry ceiling, M1–M3 gaps, B01 rejection and eight-week/100-trade M5
requirements remain unchanged. This checkpoint adds no broker execution authority.

## Current demo inspection integration — November 6

[Actual FOREX inspection evidence](../evidence/m5-current-demo-inspection-20261106.json)
records five fresh read-only receipts consumed through the authenticated loopback
dashboard API. An earlier separate five-sample capture checked the reader; both
private directories are retained. Exact demo identity/build and disabled Algo
Trading were checked around SDK reads. No credentials, account IDs or raw prices
are included in the public report.

With no browser open, the worker delivered local notifications. Removing only the
isolated latest-receipt file produced HTTP 503; restoring its unchanged bytes made
it readable again. After collection stopped, real elapsed time made it stale.
The listener and worker were stopped after verification. No desktop application
was focused, no terminal setting changed and no order was sent.

This closes the bounded current-account **inspection plumbing** check, not full
current-broker or quote acceptance. Native ticks were counted, not normalized.
The saved FOREX MCP configuration was initially flagged as pointing to CMC and
rejected before transmission. A subsequent live process-owner check identified
the existing endpoint as FOREX. The generic saved export failed initialization;
the distinct FOREX export then returned HTTP 401. The
[sanitized MCP preflight](../evidence/m5-current-mcp-preflight-20261106.json)
retains these findings; neither attempt reached calendar or time tools. Refreshing
the FOREX export in a new private file is required for this verification route.
No independent current FOREX timestamp mapping was established. Quote latency
remains unknown, and real broker disconnect
recovery, current reconciliation, full M1 and sustained M5 remain unqualified.
Existing expired clock policies and failed campaign evidence were not changed.

## Verified quote-age UI acceptance — November 6

The refreshed private FOREX MCP export authenticated successfully. Fresh verification
matched the saved BLS Employment Situation schedule (13:30 UTC) to both native
employment series (15:30 server time), corroborating +7,200 seconds independently
of quote arrival. Current terminal time agreed, and the independent host-clock
probe returned a 41.82 ms error bound in the final check. A new five-minute private binding was used;
the original expired configuration was preserved. Unauthenticated NTP corroboration
is a bounded host observation, not a permanent clock guarantee.

[Actual quote-age acceptance](../evidence/m5-verified-quotes-actual-20261106.json)
records six captures and twelve quotes through the authenticated loopback dashboard.
Five quotes met the unchanged two-second ceiling with host uncertainty included;
reported ages ranged from 1.564 to 3.897 seconds. The check observed real elapsed
staleness, HTTP 503 for isolated feed-file loss, rejection of a changed clock hash,
and fresh actual quotes after the file fault. It preserved the pre-loss receipt
and delivered all local notifications without a browser. No broker disconnection
was injected, no terminal setting changed and no order was submitted.

[Final-review UI acceptance](../evidence/m5-verified-quotes-review-20261106.json) records
116 passing backend checks and seven passing headless browser flows with no skips,
including the two-second boundary with
uncertainty, future timestamps, missing/invalid quotes, clock expiry/jump/host loss,
receipt provenance, recovery and browser freshness expiry. The real broker check
uses HTTP; fixture-driven headless browser tests verify rendering and interaction.
These are separate evidence scopes, not a claim of a live browser trading session.
The final review also prevents a future-dated-at-receipt quote from becoming fresh
merely as time passes. All twelve saved actual quotes were independently checked
against their receipt times and were not future-dated. The
[preceding local report](../evidence/m5-verified-quotes-local-20261106.json) remains retained.
The [earlier development check](../evidence/m5-verified-quotes-preliminary-20261106.json)
is retained separately; the final actual check followed the UTC/monotonic sampling
alignment fix. Neither short check substitutes for sustained qualification.

Reproduce the bounded actual check with `tools.qualification.verified_quote_acceptance`
using `--binding`, `--clock`, a new `--output` directory and a new `--report` file.
It performs six reads, injects faults only into its own receipt pointer and stops
its own loopback listener and worker. The source terminal remains running and
Algo Trading must remain off. Evidence issuance and capture are separate explicit
commands; expired evidence is never refreshed by the UI.

This completes reported quote-age display with independently corroborated mapping
for the bounded session. It does not measure transport latency or independently
bound the broker's internal clock error. M1 provider/market-data gaps, broker
disconnect recovery, current reconciliation, B01's rejection and M5's eight-week
AND 100-closed-trade requirements remain open. No execution authority follows.

## Owner access acceptance

The consolidated owner-access change replaces manual browser token entry with
normal single-owner sign-in when configured, and cookie exchange for development
launches. Tests cover actual TLS, bearer-bypass rejection, CSRF/Origin rejection,
logout, restart/expiry/certificate binding, throttling, browser reload and absence
of operator authority. Setup and limitations are in the
[owner guide](../guides/dashboard.md#owner-sign-in). No password, broker credential,
trust-store installation, strategy campaign or remote deployment is part of this change.

The [source-hashed owner-access report](../evidence/m5-owner-access-20261106.json)
records **119 backend checks and eight headless browser scenarios passed**, with
zero skipped or flaky checks. These include an ephemeral-CA HTTPS browser sign-in
and the existing dashboard/model/simulator/quote-age flows. All broker and external
model call counts are zero. The report explicitly leaves full M5 incomplete.

## Registered matched-study receipts

The [receipt workflow](m5-matched-workflow.md) adds frozen artifact registration,
transactional observation/decision/outcome admission, immutable corrections and
close, same-ID retry/restart recovery, existing-format study export and an exact-bound
read-only dashboard view. Failure clears the view; a durable sequence/hash checkpoint
rejects rollback. It is not a strategy runner or a prospective campaign. All evidence
from earlier M5 deliveries is retained.

## Optional receiver delivery engineering

The [alert delivery guide](m5-alert-delivery.md) specifies explicit activation, the
receiver contract, cumulative/deadline limits, crash uncertainty and bounded receipt
lookup. This closes the local-spool-only implementation gap, not remote operating
qualification. No real destination or credentials were provisioned during acceptance.

## Inspection deployment lifecycle

The [deployment guide](m5-deployment-readiness.md) adds private artifact/package
pinning, socket-free TLS preflight, explicit NEW/RESUME modes and a foreground
inspection-only launch. Isolated acceptance exercises HTTPS owner sign-in, denied
operator access, running-workspace backup refusal, stop, verified backup/restore
and resumed inspection. This is deployment engineering, not target-host or full M5
qualification. Existing preview, broker terminals and all earlier evidence remain
untouched.

## Incremental PAPER runner, simulation only

The [runner guide](m5-paper-runner.md) connects B01 research observations, three
separate comparison arms, scripted selection, the existing deterministic governor
and costed simulator, durable transitions, later outcomes and dashboard receipt
export. Restart verifies prior transitions without broker resends. No new campaign
or production model call is part of this acceptance; B01 remains rejected and
prospective input/model/operating qualification remains open.

## Runner operating integration

The [operating guide](m5-runner-operations.md) documents the immutable source queue,
commit/acknowledgement recovery, source sealing and direct read-only runner view.
Synthetic and headless acceptance preserve original quote timestamps, pending evidence
and terminal checkpoints. No campaign or connected execution is part of this scope.

## Source inspection and paired archive recovery

The [runner recovery guide](m5-runner-recovery.md) covers queue visibility, source
rollback detection and portable stopped-journal verification. The simulation exercise
preserves pending and unacknowledged evidence; restored bundles grant no authority.

## Typed simulation input integration

The [input admission guide](m5-input-admission.md) specifies source identity, retained
original evidence, shared calendar/news safety, immutable retry and admission-time
expiry. This completes the local normalized-input-to-simulator connection; external
collectors, qualified provenance and production model integration remain open.

## Recorded selector simulation integration

[Recorded model replies](m5-recorded-selectors.md) now pass through frozen request
binding, strict selection validation, common risk and the durable simulator. Model
latency/usage/cost remain reported evidence, with unknown costs explicitly retained.
Actual provider transport and prospective model qualification remain open.
