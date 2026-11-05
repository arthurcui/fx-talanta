# Broker cost calibration from retained evidence

The available-evidence assessment is complete. It measures the retained demo sample;
it does **not** establish a broker-calibrated January 2025 replay profile. B01 remains
`REJECT_FOR_PROMOTION`, and the original studies and cost assumptions are unchanged.
No terminal, desktop, order, new campaign or strategy replay was used.

## Measured result

The [reproducible assessment](../evidence/m3-retained-cost-calibration-20261105.json)
uses one saved FOREX.com MT5 history snapshot, avoiding overlapping histories.
Six EURUSD trade deals reconcile to three closed 0.01-lot positions. Both legs
together represent 0.06 filled lots. Recorded commission, fees and swap total zero
CAD; observed commission plus fees per filled lot are therefore zero **in this
sample only**. One non-trade deal is excluded, so this is not an account-wide charge
audit. The extractor does not export prices, tickets or account identifiers.

Native timestamp differences are 24.690, 29.235 and 30.404 seconds. These are not
independently verified UTC holding intervals or proof of rollover exposure. Zero
swap on these deals cannot identify a financing rate. Three deliberately bounded
demo positions cannot establish representative execution costs or live tariffs.

## Calibration decisions

| Cost | Usable evidence | Decision |
| --- | --- | --- |
| Spread | Existing January HistData bid/ask audit | Keep source spreads; no additional spread deduction or broker-equivalence claim |
| Commission and fee | Zero CAD recorded on six demo fills | Retain sample measurement; do not set the historical replay tariff to zero |
| Account plan | No dated plan attestation in this assessment | Standard/RAW cannot be inferred from demo charges |
| Financing | No dated pair/side rates and multiplier schedule | No calibrated swap profile; missing rates remain missing |
| Slippage | No validated native submission benchmark joined to these fills | No fitted distribution; decision-time quotes are not a substitute |
| Conversion | CAD sample versus USD-only replay | No transfer into USD costs without dated conversion evidence |

Official sources reviewed November 5, 2026 reinforce these scope limits:

- [CMC holding costs](https://www.cmcmarkets.com/en-ca/cfd-trading/holding-costs-explained)
  describes historical annual rates inside the platform's product overview. The
  public explanation does not establish this account's historical MT5 rates.
- [FOREX rollover figures](https://www.forex.com/en-ca/about-us/financial-transparency/rollover-rates/)
  are estimates for a 10K position. They do not establish the January 2025 rate series
  needed by the existing study.
- [FOREX trading costs](https://www.forex.com/en-ca/about-us/financial-transparency/trading-costs/)
  excludes MetaTrader from its published execution statistics. Those statistics
  cannot calibrate this MT5 execution channel.

This does not establish that historical evidence is unavailable everywhere; it
records what the reviewed sources and retained sample can support.

## Completion boundary

The evidence assessment and sample measurement are finished. Full historical
broker calibration remains unsupported by the available evidence. Another replay
with invented rates would not resolve that limitation, so no new profile or study
was produced. The broker-aware engine retains its synthetic/unqualified profile
statuses and the two-second entry rule. M1 gaps remain separate and open.

To qualify a future profile, require effective account/channel commission terms,
dated signed pair/side financing rates with units and holiday multipliers, dated
currency conversions, and matched native submission/fill records representative
of the intended execution conditions. Preserve receipt times, revisions and source
hashes. Calibrate on a declared earlier population and evaluate on a newly registered
later period; do not retrospectively relabel the existing B01 result. Missing source
availability/session evidence is still a separate M3 limitation.

## Reproduce without terminal access

```text
python -m tools.qualification.retained_cost_calibration --source <saved-demo-snapshot.json> --output <new-report.json>
python -m pytest tests/test_retained_cost_calibration.py tests/test_broker_costs.py tests/test_input_cost_audit.py
```

The tool checks demo/CAD/EURUSD scope, unique deals, complete opposing entry/exit
pairs, finite charges, 0.01-lot volumes and native timestamp ordering. Partial or
reversal histories are rejected rather than guessed. Outputs are exclusive-create,
input bytes are checked unchanged, and source/assessor hashes are recorded. It has
no terminal client or execution authority. The 30 targeted tests passed locally;
initial temporary-directory setup errors were resolved using a fresh workspace
temporary directory without changing dependencies or test assertions.
