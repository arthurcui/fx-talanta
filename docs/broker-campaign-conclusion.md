# Broker campaign conclusions — November 3, 2026

Both campaigns are concluded. Original plans, deadlines, bindings, databases and
failed evidence are preserved. No run was restarted; trading remains disabled.

| Broker | Outcome | Committed observations | Complete reads | Fresh slots |
| --- | --- | --- | --- | --- |
| CMC | HALTED at 08:31:04 UTC, INVALID_DATA | 441 | 438 | 394 |
| FOREX.com | User-requested STOPPED at 18:55:15 UTC | 1720 | 1718 | 1485 |

[Independent database verification](evidence/broker-campaign-final-20261103.json)
reconstructed the saved evidence exactly. FOREX ran about 14 hours 20 minutes;
CMC ran about 3 hours 40 minutes. Neither passed the original 24-hour collector
or quote-readiness acceptance. No final completion receipt or final-verification
attempt exists. Partial-window fractions must not be presented as full-day passes.
The five-second observation and two-second entry ceilings remain unchanged.

FOREX's maximum attempt gap was 59.096 seconds and complete-read gap 89.610 seconds.
CMC's corresponding gaps were 59.291 and 89.829 seconds. These bounded continuity
observations do not establish sustained acceptance. FOREX's quote gate had already
become mathematically unattainable before the user stopped collection.

CMC's exact INVALID_DATA trigger remains unproven because the failing snapshot
and specific validation cause were not retained. It is not attributed to stale
quotes or clock failure. Old CMC 401-row and FOREX 218/17-row histories and original
file hashes were verified unchanged. The CMC halted evidence remains frozen.

Both active collector process trees exited through their stop-file paths. MT5
terminals were left running. The hourly qualification monitor was deleted.
Further diagnosis or campaigns are separate work; no new campaign is authorized
by this conclusion. These reports do not qualify full M1 or authorize orders.
