# Historical source pins

These files are exact tracked bytes from commit `2711d4fa88c76244cf465e484a5b9c87a4aa5105`, named by SHA-256. The manifest maps original paths to hashes. They preserve the source behind previously committed broker, native Tester, and connection evidence while implementation changes proceed.

`historical_source` checks the requested digest; it never updates an old report to imply the new source was tested. Current behavior is covered separately by current unit/integration tests and the M2D remediation report. These archives are fixtures, not executable deployment inputs.
