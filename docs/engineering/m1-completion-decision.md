# M1 completion decision — proposed, not approved

## Finding

M1 cannot be completed under its current acceptance contract using the retained
records and bounded checks authorized so far. This is not a CI failure or a reason
to keep adding small adapters. The previous recommendation to finish it immediately
did not account for its actual exit requirements.

The [canonical matrix](../architecture/design-migration.md#milestone-acceptance)
requires sustained broker acceptance (M1A), complete required-family integration
(M1B), and prospective provider qualification (M1C). The
[closure checklist](m1-closure-checklist.md#m1-exit-checklist) additionally preserves
independent broker verdicts and requires an explicit scope decision for exclusions.
No acceptance requirement is changed by this proposal.

## What cannot be repaired with code or existing evidence

| Requirement | Actual evidence | Why another implementation commit cannot close it |
| --- | --- | --- |
| B4: both brokers' sustained acceptance | CMC halted; FOREX stopped with freshness gate unattainable | Completed elapsed observation and final receipts are absent; original failures cannot be rescored |
| P2: prospective delivery for each required family | One JOLTS schedule match; other families unqualified | Historical data or replay cannot prove a future first receipt or an omitted notice |
| P4: complete source and intended-use scope | Broader news, official unscheduled routes and other families remain uncovered | A source must actually be selected and its use/coverage established; absence is not optionality |
| P5: sustained provider availability/delivery | Eight-source campaign stopped before deadline | A successful fetch is not sustained availability, and no prospective item is insufficient evidence |

The [retained broker result](../evidence/broker-campaign-final-20261103.json),
[provider result](../evidence/provider-campaign-final-20261103.json) and
[BEA import](../evidence/bea-calendar-import-20261105.json) remain unchanged.
The last proves 70 parsed schedule occurrences and duplicate-free offline replay,
not release receipt, complete calendar coverage or source qualification.

## Implementation boundary discovered in review

`news_filter.assess` deliberately forces provider-shadow `calendar_ok` and
`news_ok` false. `provider_pipeline.Journal.inputs` marks transport checks
`complete=False`, and its policy requires separate calendar/news inventory inputs.
Consequently, adding adapters cannot by itself make strategy inputs ready.
This is an explicit safety boundary, not a filter defect to remove to obtain a pass.

Production promotion needs a separate reviewed evidence-to-qualification path,
bound to source/family coverage, time basis, horizon, revisions, delivery and use
scope. It must then feed the deterministic filter, preserving point-in-time
availability and vetoes. This integration is still missing; it must not be
described as merely waiting for a scheduled release. Current adapters remain
useful for development and shadow evaluation.

## Recommended scope decision

Separate **M1 development integration** from **operational data qualification**.
This is a proposed change to the milestone contract, not a declaration that the
existing full-M1 criteria passed.

The development completion boundary would be:

1. Existing observer, manual BLS/FRED, optional MCP, eight news feeds and BEA
   ingestion remain explicitly development/shadow sources with their limits.
2. Storage, replay, time normalization, deduplication, stale/missing-input vetoes
   and broker isolation are covered by regression and retained bounded evidence.
3. Quote freshness is distinct from channel health. The two-second entry ceiling
   remains unchanged; bounded M2 execution evidence does not qualify M1 data.
4. Offline M3 baseline/replay can proceed using provenance-marked datasets.
   Strategy orders, unattended PAPER and LIVE remain disabled.

The complete original B4/P2/P4/P5 gates, missing-family adapters and the reviewed
qualification-to-runtime integration would remain mandatory **before connected
strategy PAPER**, not merely before LIVE. They would be tracked together as an
operational qualification deliverable with explicit source scope and an authorized
observation plan. No gate would be silently dropped, transferred into a passing
result or satisfied by a fixture.

If this scope decision is not accepted, the correct status remains **M1 open**.
The alternative is to retain the full contract, implement all missing routes and
qualification integration, then authorize the necessary future observations.
Neither choice authorizes a campaign, subscription or order by itself.

## PR disposition

PR #26 is work in progress and remains unmerged. Its adapter and evidence summary
are valid partial work, not an M1-completion deliverable. Do not merge or relabel
the milestone as complete based on green CI. This decision must be resolved before
presenting another partial PR as the requested outcome.
