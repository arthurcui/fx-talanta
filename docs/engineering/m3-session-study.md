# Full-session historical study

This offline study extends the short [historical pilot](m3-historical-data.md) to
complete UTC sessions. It uses the same B01 strategy, risk governor and simulator.
It has no terminal, broker, database-service or desktop dependency. The CLI lowers
only its own worker priority; source data and detailed journals remain private.

## Frozen design

| Partition | UTC interval, start inclusive and end exclusive |
| --- | --- |
| Training | January 21–22, 2025 |
| Validation | January 22–23, 2025 |
| Holdout | January 23–24, 2025 |

Both EUR/USD and USD/JPY use the saved January HistData archives. Earlier ticks
supply indicator warm-up. B01 parameters are unchanged; there is no parameter search
or selection between partitions. These labels represent one chronological split,
not multiple walk-forward folds. Each pair starts each partition with an independent
simulated account. Both pairs must finish all earlier partitions flat, with verified
receipts, before the next partition can run. Never concatenate their equity curves
or reset unresolved positions to manufacture a clean boundary.

All selected ticks are processed in source order. No downsampling, artificial
timestamps or forced boundary liquidation is used. Stops, targets, four-hour holding
limits and the normal 23:45 UTC time exit remain active. If a position cannot close
normally, preserve it in the result and block later partitions.

The registered plan explicitly assumes clear historical calendar/news and complete
history for this counterfactual research scenario. This is **not** provider
qualification. Receipt latency is modeled at 250 ms; the two-second entry rule is
unchanged. Costs are uncalibrated USD assumptions: 4 per lot per side commission,
2 per lot per side adverse slippage and 3 per lot per day financing. Source bid/ask
already includes spread. Do not subtract embedded spread/slippage twice. Generic
instrument limits are not verified specifications for CMC or FOREX.com.

## Reproducible execution

1. Build a private SQLite index for each saved archive. It preserves Decimal quote
   text, UTC milliseconds and original row ordinals; no raw data is redistributed.
2. Write a `Plan` JSON with both experiments, dates, costs and explicit assumptions.
3. Register the plan and indexes before evaluation. Registration pins archive/index
   hashes and relevant engine source hashes.
4. Run both training partitions, then both validation partitions, then both holdouts.
   Run one worker at a time. Existing output directories, including failures, cannot
   be overwritten. A source/index change invalidates the registered execution.
5. Reconstruct each hash chain, final balance, fills, exposure, equity and drawdown
   from the compressed audit streams before treating the result as verified.

```text
python -m fx_talanta.research.session_study index --archive .local/EURUSD.zip --symbol EURUSD --output .local/index-eurusd
python -m fx_talanta.research.session_study index --archive .local/USDJPY.zip --symbol USDJPY --output .local/index-usdjpy
python -m fx_talanta.research.session_study register --plan .local/session-plan.json --index EURUSD=.local/index-eurusd/ticks.sqlite --index USDJPY=.local/index-usdjpy/ticks.sqlite --output .local/session-study
python -m fx_talanta.research.session_study run --study .local/session-study --symbol EURUSD --partition training
```

Use the same `run` command for USDJPY training, then each pair's validation and
holdout. An incomplete/failed/unverified earlier partition blocks advancement.
Registration hashes detect changes; they are not an external attestation against
someone rewriting the registry. Preserve all registered experiments and do not reuse
an examined holdout as untouched evidence.

## Resource and evidence bounds

Each index accepts at most five million source ticks, 20,000 bars, a 32 MiB ZIP and
256 MiB CSV. SQLite has an 8 MiB cache; insertion batches contain 5,000 rows and
replay reads 512 rows at a time. Each partition is at most 24 hours and 300,000 ticks.
Exceeding a bound fails explicitly rather than silently truncating the session.

Equity and hash-chained audit records stream to deterministic gzip JSONL files.
Each stream is bounded to 8 GiB uncompressed and 512 MiB compressed; each record is
bounded to 2 MiB. Only the latest audit record and running drawdown are retained by
the stream writer. Engine position/order history and the bounded bar set remain in
memory. These are resource limits, not strategy qualification thresholds.

## Interpretation

Three consecutive days are a small, correlated sample. Report closed-trade counts,
cost-adjusted return per independent account/session, observed drawdown, gaps and
unresolved exposure. Do not annualize returns, infer economic significance or claim
broker execution quality. Historical gaps do not establish a broker outage, and
modeled receipt latency cannot prove live quote freshness.

The original pilot and its unresolved training position remain unchanged. M1
operational gaps, broader M2 fault acceptance, independent indicator parity,
broker-specific costs and larger multi-fold research remain open. All outputs retain
`execution_enabled=false`, `m1_qualified=false` and `economic_acceptance=false`.
