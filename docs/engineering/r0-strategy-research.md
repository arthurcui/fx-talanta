# R0 and Strategy + Research implementation register

Delivery scope: canonical R0-R6 documentation plus the first persistent owner-facing
strategy workspace. Trading stays disabled. No broker/model/provider calls or campaigns.
PR #63 was reviewed, corrected and merged first; its dispatch interface is reused.

## Component inventory and priority

| Component | Implemented foundation | Current gap / priority |
| --- | --- | --- |
| Persistence / risk / EA | M0-M2 records, isolation, reservations, fixed EA and bounded demo evidence | Preserve; applicable M2 fault matrix before R3 acceptance |
| Input validation | Observer, EA/Python/MCP telemetry, calendar/news filters | M1 qualification and runtime binding remain open; declare exact candidate needs in R1 |
| Strategy creation | New immutable descriptive revision/freeze/export workspace | **Next R1:** bounded AI generation with provenance and reviewed executable-rule mapping |
| Research | M3 baseline/replay/cost studies; M5 matched evaluation/runner | **Next R2:** bind candidate, registered dataset, cost profile, windows and criteria; integrate run/results UI |
| Model dispatch | M4 provider abstractions; PR #63 durable reservation/uncertainty recovery | Reuse contracts; authenticated research transport needs explicit configuration and bounded validation |
| Advisor / UI | Evidence chat, journal, inspection, operator simulation and new lifecycle overview | Link strategy/experiment evidence into advisor; do not invent citations from unbound reports |
| Operational qualification | Historical reports retained | M1, M2 fault matrix, M3-Q1-Q4 and unattended PAPER remain open; B01 rejected |

## This implementation's exact boundary

- Overview reports R0-R6 implementation states and unresolved gates, not current broker health.
- Strategy form records hypothesis, input/calendar policy, entry/exit/HOLD rules,
  portfolio/USD exposure policy, proposed percentage limits, evaluation plan and declared provenance.
- Save creates an immutable revision; same-request retry is idempotent. A stale parent
  or conflicting request is rejected. New versions retain their predecessor hash.
- Freeze records the exact latest revision for research. It does not validate executable
  semantics or grant PAPER/LIVE eligibility. Revision after freeze creates a new draft.
- Saved versions survive restart and export as JSON. The UI shows the latest 100
  revisions; older records remain in the local journal. Full-history browsing is future work.
- AI_IMPORTED is a user declaration, not verified model provenance. No fake AI generator.
- Backtest control remains disabled with explicit missing integrations. Existing uploaded
  studies are not attributed to a new strategy automatically.

Storage uses the existing account/snapshot-bound inspection SQLite journal. Research
writes are isolated from broker/strategy execution. Existing authentication, origin,
session and CSRF checks protect both read and write routes; payloads are bounded.
No new database service or environment dependency is introduced. Restore remains
inspection/research-only and does not restore execution or model-call authority.

Per the owner's November 14 clarification, legacy database migration and backward
compatibility are outside pre-production scope. Development schema changes may start
with a fresh disposable store; old qualification reports and retained experiments
remain evidence. The persistence tests here verify current-version restart and
immutable records, not cross-version migration support. No existing data is deleted.

## Acceptance and owner walkthrough

Use the [dashboard guide](../guides/dashboard.md) with a separate local state folder.
The application is not launched or attached to a broker by this documentation change.

1. Open Overview: confirm offline research, no active strategy and R0-R6 blockers.
2. In Strategies & research, fill a hypothesis and all required policies, percentages
   and provenance. Save and inspect the exact version and SHA-256.
3. Freeze it. Verify it says FROZEN_FOR_RESEARCH, not executable or qualified.
4. Change a rule and save a revision. The original frozen version remains selectable.
5. Reload/restart the same workspace; inspect and export the retained version.
6. Confirm candidate backtesting is unavailable with explicit reasons; no trade controls
   or AI-generation success claims have been introduced.

Automated checks must cover persistence, retry conflict, stale parent, immutable freeze,
revision after freeze, unsupported pairs/risk/authority, session protection and the
actual headless browser form/reload/export/error path. R0 completion is limited to this
inventory and usable overview; full R1/R2 acceptance is not claimed.

Validation on November 14: **262 backend checks and 12 headless browser scenarios
passed**, zero skipped/flaky cases. The new browser workflow exercised save, freeze,
revision, reload, JSON export, rejected invalid risk and mobile layout. The
[source-hashed report](../evidence/r0-strategy-workspace-20261114.json) records the
tested scope and its explicit R1/R2 limitations. No broker or external model was called.

## Next consolidated Strategy + Research scope

Complete one route from bounded AI hypothesis generation to reviewed executable
candidate, registered point-in-time dataset/costs/windows, replay execution, charts,
trade inspection and a retained reject/revise/eligible-for-paper assessment. Include
advisor evidence links, cancellation/failure/restart behavior and owner walkthrough.
AI call provenance must be verified; arbitrary generated code must not execute through
the UI. Use the existing engines instead of a second parallel research framework.
No new broker, live controls, deployment expansion or cosmetic-only PR is part of it.

Historical evaluation eligibility never clears input/execution qualification. Preserve
negative experiments and do not silently reuse exposed holdouts as independent evidence.
