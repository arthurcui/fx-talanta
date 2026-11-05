# Engineering evidence

Evidence is grouped here without changing historical JSON files or their verdicts.
A successful fixture/native check and an actual broker fill are different kinds of proof.
See [current status](../product/status.md) for what the product may claim today.

| Evidence | What it establishes | What it does not establish |
| --- | --- | --- |
| [Broker-aware replay costs](m3-broker-cost-integration-20261105.json) | Synthetic per-fill commission/rollover integration, ledger reconstruction and exact legacy fixture compatibility | Historical broker-cost calibration, CAD ledger support, broker billing equivalence or any new trading authority |
| [Frozen multi-fold result](m3-walkforward-result-20261105.json) | Three advancing origins and a separate final outcome holdout, base/stress costs, flat boundaries and a reproducible rejection screen | Calibrated broker costs, statistical profitability, full M3 qualification or permission to trade |
| [Historical input/cost audit](m3-input-cost-audit-20261105.json) | All 5.75 million January ticks checked, spread distributions, explicit gaps and retained demo fee aggregates | Certified session availability, representative slippage or account-specific historical cost calibration |
| [Full-session historical study](m3-full-session-study-20261105.json) | Six verified offline sessions, all source ticks retained, 14 closed simulated trades and flat boundaries | Economic edge, multi-fold validation, measured latency, M1 qualification or broker execution quality |
| [Bounded demo, November 4](m2-bounded-demo-20261104.json) | Actual demo entry, protection, controlled close and independent read-only recovery | Unattended first-pass success, complete M2 fault acceptance or M1 qualification |
| [Native closeout](m2-native-closeout-20261104.json) | Complete synthetic native close/report/ACK/drain and preserved first assertion failure | Connected first-pass broker acceptance or M1 qualification |
| [Native activation](m2-bounded-activation.json) | Recorded native checks and regression results for the pinned source | A fresh result for source modified after that build |
| [Broker campaign conclusion](broker-campaign-final-20261103.json) | Preserved failed/stopped CMC and FOREX outcomes | A passed sustained qualification |
| [Provider campaign conclusion](provider-campaign-final-20261103.json) | Actual polling/delivery evidence and remaining gaps | Complete USD/EUR/JPY category coverage or broader-news qualification |
| [Manual BLS tool](manual-bls-windows-20261103.json) | Recorded Windows file-chooser/import verification | Automatic timely publication of all future releases |
| [EA quote comparison](forex-ea-quote-comparison-20261103.json) | Short measured channel comparison | Long-term reliability or live-server equivalence |

Full explanations: [demo execution](../engineering/m2-demo-execution.md),
[broker conclusion](../history/broker-campaign-conclusion.md),
[provider conclusion](../history/provider-campaign-conclusion.md),
[provider acceptance](../engineering/provider-acceptance.md).

Other JSON files in this directory preserve earlier intermediate and negative results.
They are chronological artifacts, not competing current-status documents. Raw captures
and credentials remain private under ignored `.local/` directories. Hash-addressed
source snapshots under `tests/fixtures/source-archive/` allow verification after code
changes; original paths are resolved through the [migration map](../architecture/path-migration.json).
