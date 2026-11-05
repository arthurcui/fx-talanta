# Operational M1 requirements carried into M3

Status: **OPEN — blocks connected strategy PAPER, unattended PAPER and LIVE**.
The owner approved offline M3 progression under the
[development/operational split](m1-completion-decision.md). No item below is waived.
This register is the durable handoff; memory of the chat is not required.

| IDs | Owner/component | Required closure evidence | Current disposition |
| --- | --- | --- | --- |
| B1-B3 | Broker observation | Diagnostic causes, independently verified clock/binding, completeness and recovery | Diagnostics and bounded comparisons implemented; original CMC trigger remains unknown; do not invent attribution |
| B4 | Broker acceptance | Independent committed-row and final-receipt verification under an authorized frozen plan, separately for CMC and FOREX | Both historical campaigns remain unaccepted; no new run authorized |
| P1 | Calendar integration | All declared USD/EUR/JPY families, exact/date-only/uncertain time, horizon, stable identity or conservative reconciliation, revisions | BLS/FRED/MCP/BEA development routes do not prove complete inventory coverage |
| P2 | Release matching | Prospective expected-release/actual-notice matches, omissions and separate schedule/publication/receipt times for each required family | JOLTS scheduled arrival passed while publication-age metric failed; other family evidence incomplete |
| P3 | Provider journal | Selected-route revision, deduplication, failure/recovery and point-in-time replay evidence | Fixtures and bounded imports exist; full required-route evidence incomplete |
| P4 | Source scope | Named usable sources and intended-use evidence per family, including broader news and unscheduled/intervention announcements | Missing routes and coverage remain blockers; no subscription purchase authorized |
| P5 | Provider reliability | Predeclared availability/gap/delivery qualification; no new item means insufficient | Original eight-feed campaign stopped early; bounded fetches do not replace it |
| X1 | Qualification-to-runtime integration | Reviewed evidence binding to source, family, horizon, versions, expiry and runtime vetoes; positive and negative end-to-end tests | Not implemented; do not remove shadow-only restrictions to obtain readiness |
| X2 | Release acceptance | One independent operational verdict resolving all applicable rows and preserving old evidence | Blocked by the rows above; M2 demo success and M3 replay cannot satisfy it |

The complete family list remains in [provider-inventory.json](../provider-inventory.json).
Existing gates and evidence remain in the [original checklist](m1-closure-checklist.md),
[broker conclusion](../history/broker-campaign-conclusion.md) and
[provider conclusion](../history/provider-campaign-conclusion.md).

## Rules while M3 proceeds

- Research inputs retain source hashes, availability times and qualification labels.
- Synthetic or historical results cannot become prospective qualification evidence.
- Channel health, quote freshness and entry permission remain distinct. The
  two-second entry rule and five-second observer ceiling are unchanged.
- Strategy trading stays disabled. Offline simulated orders are research fixtures,
  not permissions to submit through MT5, Python or MCP.
- No new 24-hour campaign, terminal change, automatic failover or paid service is
  authorized by milestone progression. Any future observation plan is separate.

Before connected strategy PAPER is proposed, review every row and link actual
closure evidence. Updating a document or passing CI cannot close an evidence gate.
