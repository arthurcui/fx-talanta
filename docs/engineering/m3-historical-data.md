# Historical input and first replay pilot

The background-only historical path now accepts HistData Generic ASCII tick ZIPs.
It does not use MT5, launch an application, connect to a broker, or place orders.
Raw downloads and full replay journals stay under ignored `.local/` directories.
Only source hashes, aggregate quality observations and sanitized results are public.

## Source and interpretation

The [HistData specification](https://www.histdata.com/f-a-q/data-files-detailed-specification/)
defines tick rows as timestamp, bid, ask and volume. Its timestamps use fixed
UTC−05:00 throughout the year. The importer converts this to UTC without applying
summer daylight-saving changes. Decimal quotes must be finite, positive and uncrossed;
out-of-order timestamps fail rather than being silently sorted. ZIP membership,
compressed/uncompressed sizes, row counts and selected event counts are bounded.
No files are extracted from the ZIP.

The January 2025 archives were obtained through the free public download forms for
[EUR/USD](https://www.histdata.com/download-free-forex-historical-data/?/ascii/tick-data-quotes/eurusd/2025/1)
and [USD/JPY](https://www.histdata.com/download-free-forex-historical-data/?/ascii/tick-data-quotes/usdjpy/2025/1).
No paid FTP service, account or subscription was used. Earlier bounded probes of the
Dukascopy public tick endpoint returned HTTP 429 for both pairs; no retry loop was
started. Raw data is not included in this repository or licensed for redistribution
by this implementation.

Tick data does **not** supply FX-Talanta receipt times, historical revisions or
calendar/news qualification. The importer records these limitations. The optional
250 ms receipt latency is a model assumption, not a measured delivery result.
Revision 1 identifies this imported snapshot, not proof of an unrevised source.
Observed BID ticks form M15/H1 bars; partial edge bars are excluded and empty periods
are not filled with invented prices. Large gaps are reported, including possible
weekends; they are not automatically classified as source failures or closed sessions.

The source row ordinal preserves equal-timestamp ticks. The replay processes all
such events in their original order, without deduplicating distinct prices or adding
fictional microseconds. Unsequenced or reversed equal-time events remain invalid.
The actual two January archives contained no timestamp ties; tie handling was tested
with purpose-built fixtures. The original B01 synthetic result hashes still reproduce.

## Run locally

Download a Generic ASCII **tick** ZIP from the source's free download page, keep it
private, and run from the repository with the package installed:

```text
python -m fx_talanta.research.historical --archive .local/HISTDATA_COM_ASCII_EURUSD_T_202501.zip --symbol EURUSD --start 2025-01-16T12:00:00+00:00 --end 2025-01-16T15:00:00+00:00 --output .local/history-eurusd
```

The default produces `dataset.json` and `quality.json` with completeness and required
calendar/news inputs **unqualified**. A failed import retains `failed.json`; output
directories cannot be overwritten. This bounded pilot importer rejects more than
50,000 selected ticks or a dataset exceeding 32 MiB rather than downsampling silently.

`--assume-research-inputs` is an explicit counterfactual experiment: it assumes archive
completeness and clear calendar/news inputs for offline research only. Preserve that
choice in the experiment plan. It cannot qualify providers, grant broker authority
or change `HISTORICAL_UNQUALIFIED` provenance. The quality report retains the missing
attestations. Register the resulting dataset and experiment before replay as described
in [M3 replay](m3-baseline.md). Cost assumptions and instrument limits must be reviewed
before any larger study: the defaults here are generic research inputs, not verified
FOREX.com or CMC specifications.

## Actual fixed-window result

[Sanitized evidence](../evidence/m3-historical-pilot-20261105.json) contains source and
dataset hashes, manifests, result/journal receipts and independently reconstructed
balance/exposure checks. Both original strict imports and the separate assumption-enabled
research variant are retained. No B01 parameters were selected from these results.

| Pair | January rows checked | Selected ticks, 12:00–15:00 UTC January 16 | Result |
| --- | ---: | ---: | --- |
| EUR/USD | 2,283,239 | 22,743 | One simulated training entry, still open at that window's end; no entries in the other windows |
| USD/JPY | 3,467,097 | 30,081 | No entries in any window |

The three **independent cold-start** windows were fixed as training 12:00–13:00,
validation 13:00–14:00 and holdout 14:00–15:00 UTC. The engine's partition labels
exercise registration/receipt ordering, not a completed walk-forward study. The open
EUR/USD position is not carried into the independent validation account, force-closed,
or counted as a winning trade. Do not concatenate these windows into an equity curve.
The training position's marked change was +0.0162% of starting capital, with no closed
trade; that excludes future closing costs and is **not a realized strategy return**.

The same historical inputs under the default strict controls produced zero entries
for both pairs and remained `DEGRADED_PROTECT`. Hypothetical fills in the separate
research variant do not change those controls or the M1 qualification verdict.

**Decision: insufficient evidence to keep, reject or tune B01.** There were zero
closed trades across six one-hour scenarios. This establishes historical ingestion
and replay mechanics, not profitability, reliability or full M3 acceptance.

## Larger study boundary

The separate [full-session study](m3-session-study.md) provides bounded-memory tick
replay, compressed audit streams and verified-flat partition boundaries. Its new
registered sessions do not extend or replace this pilot's recorded windows.

Broader economic acceptance still needs multiple walk-forward folds, additional
newly frozen untouched holdouts and uncertainty-aware results. The now-examined
pilot window cannot become an untouched holdout again.
Do not extend these recorded windows, hide the unresolved position, tune parameters
to this example, or weaken freshness gates to manufacture a result. Broker-specific
financing, session reconciliation, indicator parity and the existing M1/M2 gaps remain
open. Trading stays disabled; no new campaign or broker order was started.
