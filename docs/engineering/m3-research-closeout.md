# M3 research scope closed

Owner decision, November 5, 2026: close the completed M3 research scope and proceed
to M4 development, keeping qualification gaps and the B01 verdict unchanged.

**Research scope: COMPLETE. Full historical qualification: INCOMPLETE.**
B01 remains **REJECT_FOR_PROMOTION**. A rejected baseline is a completed research
outcome, not a reason to retune until it appears profitable. M4 development does not
authorize promoting B01, connected strategy trading or another campaign.

## Delivered evidence

- [Frozen baseline/replay](m3-baseline.md): deterministic strategy and risk semantics,
  immutable registrations and independently reconstructed journals.
- [Numerical parity](../evidence/m3-numerical-parity-20261105.json): 36 reference cases.
- [Input audit](historical-input-costs.md): all 5.75 million retained January ticks,
  spread distributions and explicit gaps, with source/receipt limitations.
- [Registered study](m3-walkforward.md): three advancing origins and final outcome
  holdout, 16 flat sessions, base/stress assumptions and unchanged rejection.
- [Cost integration](broker-aware-replay-costs.md) and
  [retained calibration assessment](retained-cost-calibration.md): tested accounting
  plus sample-only measurements, without fabricated historical tariffs.

## Qualification gaps retained

| ID | Missing evidence | Closure criterion | Consequence until resolved |
| --- | --- | --- | --- |
| M3-Q1 | Account/channel-specific historical commission terms | Dated terms matched to account plan, instrument, units and effective period | Published-current prices and demo zeros remain scenarios/sample measurements |
| M3-Q2 | Historical signed swap rates, rollover exceptions and conversion | Dated pair/side rates, holiday multipliers and account-currency conversion with receipt/provenance | No historically calibrated financing/currency profile |
| M3-Q3 | Representative execution slippage | Native submission benchmarks joined to fills, declared population and uncertainty for the intended channel | Configured slippage remains an assumption |
| M3-Q4 | Source sessions, missingness, receipt and revision provenance | Verified calendars/gap classifications and actual availability/revision evidence, retaining unresolved gaps | Historical replay is counterfactual; modeled delay is not measured latency |

These are evidence requirements, not unimplemented replay features. Closure requires
reviewable artifacts and an explicit scope/date decision. New evidence may support a
new preregistered study; it must never rewrite old registrations or verdicts. M1
[operational gaps](m1-open-requirements.md) and M2's full connected fault matrix remain
independent requirements before connected strategy PAPER. LIVE remains separately gated.

## M4 authorization boundary

Proceed with offline bounded decision/advisor development. Keep the model outside
risk authority, broker mutation, policy changes and deployment. Start with typed,
account-scoped evidence projection and test its failure behavior. A real model
provider, authenticated API, persistent conversation flow, evaluated memory and
simulated command integration are later M4 acceptance work, not implied by this
research closure. No broker, desktop or active campaign changes are required.
