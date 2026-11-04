# M2D lifecycle and no-order remediation

This follow-up preserves the prior review and failed attempts. Trading remains disabled; entry quote age is capped at two seconds and native clock uncertainty at 100 ms. No 24-hour campaign was started.

## Changes and authority

| Component | Change | Remaining boundary |
| --- | --- | --- |
| ConnectedEA | Explicit transient-state and high-resolution-clock reset on initialization; identity/trading checks before backoff; explicit HTTP connection closure | Durable inbox bootstrap/resume rules remain authoritative; no order API exists in this EA |
| QuoteStream | Explicit reset; cooperative 10 ms / 256-record drain; stopped capture refusal; incomplete shutdown marker and counters | Slow OS calls cannot be preempted; MT5 event coalescing remains unmeasured; queued data may be discarded and counted at shutdown |
| Tester gateway | Timer setup failure is fatal; timer reconciles and consumes work without needing a tick; failed reconciliation remains unresolved and retries | Still Tester-only. Production protection state machine, explicit missing-journal recovery and deployment fencing are not wired into this fixture gateway |
| Broker reconciliation | Query/row/time bounds and propagated failure; incomplete history never becomes success | Large histories can remain unresolved under the cooperative budget; there is no resumable history cursor |
| Python comparison | Parent-ingestion receipt boundary for both channels; common warmed-cache start; startup identities excluded; collection duration excludes teardown | Source timestamp mapping is still unqualified; neither cache snapshots nor INITIAL records prove a new terminal tick |
| PostgreSQL session | Opt-in connection reuse with serialized, real transactions; failed connection is closed without automatic reconnect/retry | No clock allowance or lease duration is increased; durable state remains in PostgreSQL |
| Local HTTPS listener | Explicit `Connection: close`; bounded per-connection deadline; sanitized request/response and allowlisted rejection diagnostics | Loopback development listener, not production deployment |

## Verification and interpretation

The current sanitized result is [the remediation evidence](../evidence/m2d-remediation-20261104.json). Original attempt reports are unchanged. Hash-addressed source fixtures preserve the exact old implementation behind historical evidence; those old passes do not certify new source.

The native component harness passed 52 clock assertions and 11 publisher/reset assertions, plus 13 gateway handler fault-injection assertions. These are component checks, including actual QuoteStream and FixedGateway handler code with a stubbed dispatcher; they are not a complete terminal reinitialization, event-overflow, timer-failure or abrupt-process-exit campaign. Five native programs compiled without errors or warnings; the subsequent transport-only ConnectedEA rebuild also compiled cleanly.

Attempt 04 reached bounded clock synchronization but returned no HOLD receipts. Its native log alternated successful SYNC with failed PULL requests (`1003`/`5203`), while the database retained only CLOCK exchanges. Attempt 05 added explicit connection closure and request diagnostics. This comparison supports a transport connection-handling defect; the exact internal MT5/Windows failure mechanism was not captured. It does not establish a broker quote-feed defect.

A successful two-symbol no-order handoff means authenticated observations, durable HOLD receipts, matching database records and native acknowledgements. It does not authorize orders, certify the broker timestamp mapping, qualify providers, reopen M1, or complete connected PAPER execution acceptance. Missing mandate, costs, exposure baseline, session and provider evidence continue to block actionable snapshots.

The final 180-second attempt completed with **two HOLD receipts and two signed ACKs**, independently reconstructed from 376 backend records and the stopped native journal. All 371 audited HTTP responses were 200. Both captured source quotes exceeded the unchanged two-second limit; current native-cache ages were lower, but that did not refresh the older observation. The final read-only terminal check found Algo Trading disabled, zero positions and zero pending orders. This is not a trade-history audit.

The isolated full PostgreSQL regression passed **780 tests, zero skips**. Three public-evidence checks are run separately because they verify the completed report. The earlier regression's single historical-source-pin failure and the verifier/postcheck setup errors are retained privately; corrected checks never replace the original reports.

After the native run, final review corrected reusable-connection handling for a validation rejection: a completed rollback keeps receipt-only recovery available on the same connection, while database/unknown failures still permanently close it. The final PostgreSQL regression includes lease expiry followed by receipt recovery and confirms that renewal remains refused. No native attempt was repeated for this isolated recovery correction; the handoff report keeps its actual source pins.
