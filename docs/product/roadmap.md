# Product roadmap

The [architecture specification](../architecture/specification.md) defines the full
acceptance criteria. This page is the navigation summary, not a replacement for those
gates. [Current status](status.md) distinguishes implemented features from qualification.

| Milestone | Deliverable | Exit boundary / current position |
| --- | --- | --- |
| M0A–M0C | Durable records, offline risk/execution, portable deployment and recovery | Implemented foundation; preserve account isolation and archive evidence |
| M1 | Development inputs and operational qualification | Development scope accepted for offline M3; [operational requirements](../engineering/m1-open-requirements.md) remain mandatory before connected strategy PAPER |
| M2A | Intent/EA protocol and offline reference | Implemented contracts and reference vectors |
| M2B | Fixed EA | Implemented and native/Tester evidence retained |
| M2C | Deterministic safety and recovery | Implemented checks; connected acceptance still must validate the fault matrix |
| M2D | Connected PAPER execution acceptance | Bounded same-session demo closeout verified without recovery (PR #25); full fault-matrix acceptance remains open |
| M3 | Strategy baseline and replay | [Research scope closed](../engineering/m3-research-closeout.md); B01 remains REJECT_FOR_PROMOTION. M3-Q1–Q4 cost/availability qualification gaps remain open |
| M4 | Bounded AI and conversational advisor | In development: [evidence projection/durable receipts](../engineering/m4-advisor.md) and [bounded API evidence selection](../engineering/m4-provider.md); production spend/decision integration, authenticated API and simulated commands remain acceptance work |
| M5 | Unattended PAPER and operating UI | All prerequisites plus at least eight weeks AND 100 closed trades under the specification's gates |
| M6 | Capped LIVE | Explicit approval and bounded live risk after PAPER acceptance |
| M7 | Evaluated evolution | Evidence-based lessons, candidate evaluation, promotion and rollback; no self-modified execution authority |

## UI requirements carried forward

The operating dashboard must show quote latency and separate channel status for the
EA, Python MT5 package and MCP. It must distinguish connection health, quote freshness,
clock uncertainty and entry readiness. A healthy connection is not a fresh-market pass.

The owner authorized M4 development after closing M3's completed research scope.
This does not relax the two-second entry ceiling or authorize connected trading.
