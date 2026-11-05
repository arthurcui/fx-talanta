# Product roadmap

The [architecture specification](../architecture/specification.md) defines the full
acceptance criteria. This page is the navigation summary, not a replacement for those
gates. [Current status](status.md) distinguishes implemented features from qualification.

| Milestone | Deliverable | Exit boundary / current position |
| --- | --- | --- |
| M0A–M0C | Durable records, offline risk/execution, portable deployment and recovery | Implemented foundation; preserve account isolation and archive evidence |
| M1 | Qualified market, calendar and news inputs | Broker reliability and required USD/EUR/JPY coverage/timeliness must be evidenced; gaps remain |
| M2A | Intent/EA protocol and offline reference | Implemented contracts and reference vectors |
| M2B | Fixed EA | Implemented and native/Tester evidence retained |
| M2C | Deterministic safety and recovery | Implemented checks; connected acceptance still must validate the fault matrix |
| M2D | Connected PAPER execution acceptance | Bounded same-session demo closeout verified without recovery (PR #25); full fault-matrix acceptance remains open |
| M3 | Strategy baseline and replay | Reproducible baseline, point-in-time inputs and costs before AI optimization |
| M4 | Bounded AI and conversational advisor | Model proposals and explanations cite records; deterministic authority remains outside the model |
| M5 | Unattended PAPER and operating UI | All prerequisites plus at least eight weeks AND 100 closed trades under the specification's gates |
| M6 | Capped LIVE | Explicit approval and bounded live risk after PAPER acceptance |
| M7 | Evaluated evolution | Evidence-based lessons, candidate evaluation, promotion and rollback; no self-modified execution authority |

## UI requirements carried forward

The operating dashboard must show quote latency and separate channel status for the
EA, Python MT5 package and MCP. It must distinguish connection health, quote freshness,
clock uncertainty and entry readiness. A healthy connection is not a fresh-market pass.

The short-term repository work improves navigation and maintainability. It does not
advance a milestone, relax the two-second entry ceiling or authorize more trading.
