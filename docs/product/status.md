# Current product status

Baseline: merged PR #23 (`5034085`, November 4, 2026). Repository reorganization does
not change execution authority or qualify another campaign.

## Implemented

M0A–M0C provide the Python/PostgreSQL foundation, separate PAPER/LIVE credentials,
append-only records, deterministic offline simulation, risk reservations, protective
management, restart reconciliation and portable archive/restore profiles.

The repository also contains read-only MT5 observation, EA quote streaming,
calendar/news filtering and journaling, manual BLS upload with reminders, optional
native MCP calendar import, and a fixed EA with deterministic execution controls.
The manual file chooser is a utility; a trading dashboard is not implemented.

## What the demo proved

[PR #23 evidence](../evidence/m2-bounded-demo-20261104.json) records one actual
FOREX.com demo EURUSD entry, confirmed protection and a controlled exit. Independent
broker history confirms closure and flatness. A separate hard-disabled build recovered
the final `CLOSED` report after an empty-position fingerprint defect. This is
**EXECUTION_ONLY_VERIFIED_WITH_READ_ONLY_RECOVERY**, not unattended first-pass success.

The approved percentage limits remained intact. Both authorized entry reservations
were consumed, including a definite pre-submission rejection; a rejected attempt does
not refund authorization. Original authority is retired. Test EAs/listeners were stopped
and Algo Trading disabled at verification. This document is not a live terminal monitor.

## Remaining gates

- **M1:** broker data and required USD/EUR/JPY calendar/news coverage, timeliness and
  reliability remain unqualified. Failed and owner-stopped campaigns retain their verdicts.
- **M2D:** final connected execution acceptance and the complete fault matrix remain
  open. The bounded execution gate keeps M1 gaps separate; it does not clear them.
- **Later milestones:** strategy baseline/replay, production model integration,
  conversational advisor, dashboard, unattended PAPER and capped LIVE remain gated.

The next M2 acceptance must account for the separate closure recovery and reconcile
existing evidence for lost replies, restart while exposed, partial fills, rejected
protection, backend/database loss and closed-market exits. A new broker-order attempt
requires fresh bounded authorization; no further order or 24-hour run is started by
this documentation or repository cleanup.

See [demo execution details](../engineering/m2-demo-execution.md),
[broker conclusions](../history/broker-campaign-conclusion.md) and
[provider conclusions](../history/provider-campaign-conclusion.md).
