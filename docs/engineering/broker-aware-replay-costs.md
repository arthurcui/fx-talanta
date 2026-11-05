# Broker-aware replay costs, version 1

Replay now accepts either the original fixed per-lot `Costs` object or an explicit
`broker-costs/1` profile. Legacy experiment serialization and arithmetic are unchanged.
The January studies and B01's `REJECT_FOR_PROMOTION` verdict are preserved; this PR
does not rerun or reinterpret those experiments.

## Supported contract

The existing replay ledger and governor are **USD-only**. A new profile explicitly
binds USD, one pair (EUR/USD or USD/JPY), broker/plan labels, source evidence, an
effective interval and an availability timestamp. CAD and other account currencies
are rejected, not silently treated as USD. Extending the underlying ledger to another
currency is separate work.

Commission is specified in USD per USD 100,000 notional **per leg**. EUR/USD uses
the actual adverse simulated fill price to convert EUR base units to USD notional;
USD/JPY already has USD base units. Partial fills charge only filled volume. Rejected
orders create no fill charges. Each exit uses its own fill price and commission,
not the entry's notional or a fixed generic per-lot fee.

Slippage remains an explicit nonnegative USD-per-lot scenario applied adversely
to each fill. Spread is already represented by the source bid/ask. Attribution must
not be subtracted from PnL a second time. Decimal charges are unrounded: this version
does not claim to reproduce a broker's minimum-ticket fee or billing-rounding policy.

## Financing and time ordering

The supported calendar convention is weekday **17:00 America/New_York**, with DST.
Every cutoff in the profile window requires a dated row with separate signed BUY/SELL
USD-per-lot rates, an explicitly supplied multiplier, availability time and evidence.
Wednesday/triple-day and holiday exceptions are supplied explicitly; there is no
default multiplier or inference from missing rows. This convention is not a universal
CMC/AvaTrade/FOREX tariff attestation. The caller must provide the relevant schedule.

The replay timeline inserts each cutoff even when no quote arrives at that time.
Existing exposure pays or receives financing before same-time closes or new entries.
An entry exactly at the cutoff therefore participates from the next cutoff. This is
an explicit simulation ordering convention, not evidence of broker sequencing.

Financing is applied once to the volume still open at the cutoff and posted as a
separate hash-chained journal item and broker balance change. It changes position
PnL, equity and loss controls immediately; it is not an external deposit/withdrawal
and is not deferred until close. Credits remain credits. Equity receives a tagged
financing sample using the latest observed quote, whose timestamp is retained. This
mark is not a claim that the quote was fresh or executable. The two-second entry
restriction remains unchanged.

Independent reconstruction adds these signed postings to the fill ledger exactly
once. Stream verification checks postings against the journal and reconciles both
tick samples and extra financing samples, including when exposure remains open
after the final quote. Missing/late rates, incomplete coverage, duplicate cutoffs,
wrong pair/currency or a changed registered engine stop the experiment.

## Risk and evidence boundaries

Before running, the caller declares per-lot commission and financing reserves.
Commission is checked against its reserve at each observed quote/fill; a breach
fails the offline experiment rather than silently under-budgeting. The financing
reserve must cover the full profile-window debit exposure for either side; credits
do not reduce the entry reserve. This deliberately conservative reserve can affect
position size. It is a declared bound, not an empirically calibrated estimate.

Profiles can be `SYNTHETIC` or `UNQUALIFIED_SCENARIO`. Filling in provenance fields
does not create a qualification pass. Results retain `economic_acceptance=false`,
`m1_qualified=false` and `execution_enabled=false`. Source hashes now include the
new model and arithmetic helper; old registered studies require their original
engine revision and cannot be silently replayed with new costs.

The adapter accepts only an ephemeral PAPER/SIMULATOR replay store and a fresh
execution ledger. It does not implement restart recovery or later settlement of
an acknowledged/partial-entry remainder. Immediate partial fills, owned partial
closes and rejections are covered. It has no terminal/network client or deployment
path. No production broker, risk governor or USD ledger schema is changed.

## Reproduce the short synthetic acceptance

The [recorded acceptance](../evidence/m3-broker-cost-integration-20261105.json)
registered and ran the constructed Wednesday fixture through the replay CLI. It
closed its one simulated position, posted one USD 1.35 debit exactly at the cutoff
inside a quote gap, and independently reconstructed the USD 9,996.104737 ending
balance. This is fixture evidence only. A separate run of the original legacy
fixture matched both result and complete journal hashes from pre-integration
commit `4df6b0e` exactly; that compatibility check is retained as a regression test.

```text
python -m tools.fixtures.broker_cost_replay --output .local/new-cost-fixture
python -m fx_talanta.research.replay register --experiment .local/new-cost-fixture/experiment.json --dataset .local/new-cost-fixture/dataset.json --directory .local/new-cost-run
python -m fx_talanta.research.replay run --dataset .local/new-cost-fixture/dataset.json --directory .local/new-cost-run --partition training
python -m pytest tests/test_broker_costs.py
```

Use new directories: failed or completed registrations are never overwritten.
The fixture is constructed, not downloaded market evidence or a broker campaign.
Actual broker tariffs, historical side-specific swap/FX inputs, representative
slippage and session/availability evidence remain required for full M3 calibration.
