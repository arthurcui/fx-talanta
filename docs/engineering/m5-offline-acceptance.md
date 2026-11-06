# M5 offline engineering acceptance and remaining gates

This consolidates the local operating workspace and offline comparison-validation
scope. It does **not** close full M5 or claim that every feature possible with
trading disabled has been implemented. In particular, connected read adapters,
remote deployment, open-ended advisor chat and administrative UI integration remain
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
   no command route is exposed by the current dashboard.
3. **Model and evaluation:** UI model integration with existing bounds, a qualified
   frozen candidate, prospective matched AI/no-AI and news/no-news ledgers, verified
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
