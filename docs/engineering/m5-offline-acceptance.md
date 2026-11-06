# M5 offline engineering acceptance and remaining gates

This consolidates the local operating workspace and offline comparison-validation
scope. It does **not** close full M5 or claim that every feature possible with
trading disabled has been implemented. In particular, connected read adapters,
remote deployment, open-ended advisor chat and broker administrative UI integration remain
separate engineering work; sustained candidate qualification cannot be replaced by
an offline suite. Trading remains disabled, and no new campaign is authorized.

## Capability and evidence matrix

| Requirement | Current implementation / decisive check | Boundary |
| --- | --- | --- |
| Local operating workspace | Loopback-only bearer session, Host/Origin checks, expiry, restart binding, state lock; backend and browser tests | No remote authentication/TLS deployment or PAPER/LIVE account selector |
| Quote latency and channel status | Separate EA/Python/MCP connection, observation age, original quote age, transport delay and clock bound; file sequence/hash validation | Offline explicit file input, no attached broker collector; two-second entry rule unchanged |
| Decisions, risk and outcomes | Searchable projections, explicit-reference trails, unresolved evidence, original rationale, hashes and cutoff | Historical evidence does not reconcile current positions or balances |
| Operating summaries | Decision results, operational/compliance/economic record labels, corrections, distinct model traces and conflicting request detection | Record-version counts are not trade counts; fixture traces are not invoices; equity/net P&L/drawdown/exposure remain unknown |
| Advisor and learning | Authenticated English/Chinese M4 evidence reader, durable answers, exact-cutoff lesson eligibility, no executable model prose | No open-ended model chat in UI or automatic promotion |
| Calendar/news | Isolated manual BLS import, reminder, upcoming event/cancellation display and retained news/health evidence | USD/EUR/JPY coverage remains unqualified; no terminal calendar script or automatic provider qualification |
| Incidents and recovery | Durable sampled transitions, missing/stale/invalid input, literal retained-history search and stable cursors | On-demand observations, not continuous notification delivery or campaign reliability |
| Export | Authenticated bounded inspection report with reproducible payload digest and source hashes | Not a full archive, signed attestation or account-performance report |
| Matched comparisons | `evaluation/matched.py` validates three separated offline ledgers, common safety, frozen AI policy/model/prompt, pre-outcome decisions, costs and paired exclusions | Descriptive input validation only; no runner, independently verified prospective delivery, uncertainty estimate or promotion verdict |
| Reproducibility | `tools.qualification.m5_acceptance` runs the backend and headless-browser suites and records source hashes | PASS applies only to the named local inspection/evaluation scope |

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

1. **Connected input/UI integration:** explicitly authorized read adapters with exact
   account binding, independently verified timestamp mapping, current positions,
   balances/risk/protection and end-to-end failure acceptance. Existing file import
   and historic execution records do not satisfy this requirement.
2. **Administration and deployment:** authenticated account-scoped pause/close/halt UI,
   controlled resume, model-independent protection, notification delivery, remote
   TLS/access and deployment/recovery tests. M4 simulator commands are implemented;
   the dashboard now exposes separately authenticated simulator-only controls.
   Broker commands and remote owner authorization remain unavailable.
3. **Evaluation:** bounded M4 model selection and offline study upload are integrated
   in the UI. Still required: a qualified frozen candidate, prospective matched AI/no-AI and news/no-news ledgers, verified
   costs/latency, predeclared uncertainty/economic criteria and promotion review.
   This PR implements validation and descriptive comparison only, not that runner.
4. **Unattended PAPER:** resolve applicable M1–M3 gates and obtain the required
   authorization before connected strategy operation; collect at least **eight weeks
   AND 100 closed trades per candidate**, with the specification's operational and
   economic gates. No threshold reduction, retrospective relabeling or new campaign
   follows from this PR. M6 remains blocked.

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
