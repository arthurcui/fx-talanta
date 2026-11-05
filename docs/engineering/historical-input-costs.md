# Historical inputs and cost calibration

This work audits retained January 2025 HistData ticks and retained November 2026
demo fills. It does not request new terminal observations, evaluate new strategy
windows, or change legacy replay costs. Trading stays disabled. The existing
two-second entry ceiling and M1/M2 qualification gaps remain unchanged.

## Audit protocol fixed before the scan

Population: every row of the two January 2025 immutable tick indexes, in sequence
order. EUR/USD index SHA-256 is
`2ca8a00c88d05a4bda8da080378544811df783fcbc3df7d555141791481864a9`;
USD/JPY is
`eb6b5c2129112b4177709a95f9371e56165e5650e6063768b66c20bf2a5d7029`.
Original archives and indexes are retained privately and never rewritten.

Check sequential row numbers, monotone timestamps, positive finite uncrossed
bid/ask, source-month boundaries, duplicate rows and timestamp ties. Report exact
nearest-rank tick-weighted spread quantiles, both monthly and by UTC date; pip
sizes are 0.0001 and 0.01 respectively. Tick weighting is not time weighting or
executed cost. Output contains aggregates and gap times, not raw prices.

Report every adjacent gap over 60 seconds. This diagnostic threshold is not an
entry freshness rule. Split each gap into overlap with a January-only Friday
22:00–Sunday 22:00 UTC weekend proxy and remaining unexplained seconds. Retain
leading/trailing archive boundary intervals separately. This proxy is deliberately
not a certified HistData or broker session calendar: holiday closures and other
exceptions remain unknown. Unexplained gaps cannot be dismissed as holidays.

HistData specifies fixed EST (UTC−05) without DST for its tick files, with bid and
ask timestamps. It provides no data warranty. Neither original receipt times nor
revision history is present; the prior 250 ms modeled delay remains an assumption.
See [format specification](https://www.histdata.com/f-a-q/data-files-detailed-specification/)
and [source FAQ](https://www.histdata.com/f-a-q/).

The output is exclusive-create, input SQLite is immutable/read-only, and source
hashes are checked before and after. The worker lowers its own process priority.
No terminal, service or desktop interaction is required.

## Cost provenance and units

Official pages below were checked November 5, 2026. They do not establish the
account tier or fees effective in January 2025. They support **current published
scenarios**, not retroactive calibration of the retained historical study.

The [machine-readable provenance inventory](../evidence/m3-cost-provenance-20261105.json)
keeps published scenarios, observed quantities and missing calibration separate.

| Component | Evidence and treatment | Remaining limitation |
| --- | --- | --- |
| Spread | Actual historical bid/ask distributions, retaining wide tails | HistData prices are not broker-specific executable quotes; quote frequency changes tick weighting |
| FOREX.com RAW commission | USD 7 per USD 100,000 notional per leg | Account tier and historical effective schedule unknown |
| CMC FX Active commission | USD 2.50 per USD 100,000 notional per leg | Account tier and historical effective schedule unknown |
| Retained FOREX demo fees | Aggregate saved trade deals in original CAD account currency | Very small demo sample; not a real-money or 2025 pricing attestation |
| Slippage | No representative submission-quote/fill benchmark established | Keep uncalibrated; a configured allowance is not a measured distribution |
| Financing | FOREX cutoff is 17:00 New York; Wednesday normally three days, holiday exceptions; debit or credit by pair/side | Historical dated rates and pair-specific holiday adjustments missing |
| Conversion | Charge USD notional, then convert to account currency using a dated rate | Research USD account and retained CAD account are not interchangeable |

Sources: [FOREX commission calculator](https://www.forex.com/en-ca/help-and-support/fx-commission-calculator/),
[CMC FX Active](https://www.cmcmarkets.com/en-ca/forex/forex-active-trader),
[FOREX rollover](https://www.forex.com/en-ca/help-and-support/rollover/).
The FOREX financing convention must not be applied to CMC without its own evidence.

For a hypothetical 100,000 EUR leg at USD 1.10/EUR, FOREX RAW commission is
USD 7.70 and CMC FX Active USD 2.75. For 100,000 USD base units in USD/JPY the
corresponding figures are USD 7 and USD 2.50. Compute each leg separately at its
own conversion rate, then account-currency conversion and actual billing rounding.
These examples exclude spread, financing and slippage.

`research.cost_calibration` supplies separately tested arithmetic for these
conventions. It rejects absent FX conversion and absent rollover calendar approval;
missing dated financing rates raise errors. Signed rates preserve credits as well
as debits. Exact-cutoff fills require sequencing evidence. The explicit reviewed
holiday override map is caller-supplied; the helper does not certify that map.
It is not wired into replay or execution. Legacy 4/2/3 per-lot assumptions and
all published historical results remain unchanged.

## Reproduction

```text
python -m tools.qualification.input_cost_audit --eurusd <retained-eur-index> --usdjpy <retained-jpy-index> --retained-broker <saved-final-broker-json> --output <new-report.json>
python -m pytest tests/test_input_cost_audit.py
```

The broker extractor accepts only the retained demo EURUSD. population, excludes
non-trade balance deals, rejects duplicate trade IDs internally, and exports no
account identifiers. Use one snapshot: earlier snapshots overlap the same history.
No submission-price slippage is inferred from decision-time quotes.

## Actual retained-data results

[Sanitized evidence](../evidence/m3-input-cost-audit-20261105.json) checks 2,283,239
EUR/USD and 3,467,097 USD/JPY rows. Both indexes retain their original hashes;
neither has timestamp ties or adjacent duplicate rows. All scanned quotes pass
finite/positive/uncrossed validation and the January source-month boundary.

| Pair | Median spread (pips) | 95th percentile | 99th percentile | Maximum | Gaps over 60 s |
| --- | ---: | ---: | ---: | ---: | ---: |
| EUR/USD | 0.30 | 0.60 | 1.30 | 13.30 | 201 |
| USD/JPY | 0.80 | 1.30 | 2.10 | 35.00 | 193 |

After subtracting only weekend-proxy overlap, these gaps retain 16,626.497 and
19,469.715 unexplained seconds respectively. These totals are not downtime estimates:
no-tick periods can reflect inactivity or missing observations. The longest unexplained
gap is 295.803 seconds for EUR/USD and 494.960 seconds for USD/JPY. Boundary intervals
are reported separately, including the unobserved start of January 1. No holiday
explanation is inferred. Per-day spread distributions and all gap intervals are retained.

One saved demo snapshot contains six EURUSD. trade deals (three entries and three
exits), each 0.01 lot, with recorded commission, swap and fee totals of zero CAD.
Non-trade balance deals are excluded; this is not a complete account-charge audit.
No account tier, representative execution slippage or historical tariff follows from
those zeros. Existing demo evidence is only read, not replayed or modified.

## Remaining calibration boundary

This package can establish input integrity and document observed costs. Full
account-specific historical calibration still needs effective commission terms,
dated conversion/financing rates and representative execution benchmarks. A later
multi-fold study may use explicitly labeled published-cost scenarios and stress
assumptions; it must not label those calibrated, conceal missing availability, or
promote the strategy. New strategy outcomes and the final M3 verdict are outside
this input audit.
