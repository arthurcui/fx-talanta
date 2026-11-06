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
| M4 | Bounded AI and conversational advisor | Consolidated offline implementation complete; [engineering acceptance](../engineering/m4-completion.md) records authentication, proposals, risk integration, evidence, memory and simulated commands. No connected or economic qualification implied |
| M5 | Unattended PAPER and operating UI | [Local operating UI and offline evaluation validation](../engineering/m5-offline-acceptance.md) implemented and tested; bounded model, historical broker-journal and comparison UI integration implemented; simulator operator/recovery, background inspection and mutual-TLS access implemented; current demo receipt/quote inspection, HTTPS owner sign-in and durable matched-study receipt workflow implemented; complete broker reconciliation/fault acceptance, broker administration, prospective evaluation and actual remote deployment remain open; full acceptance still requires all prerequisites plus at least eight weeks AND 100 closed trades under the specification's gates |
| M6 | Capped LIVE | Explicit approval and bounded live risk after PAPER acceptance |
| M7 | Evaluated evolution | Evidence-based lessons, candidate evaluation, promotion and rollback; no self-modified execution authority |

## UI requirements carried forward

The read-only dashboard shows recorded quote timing and separate channel status for the
EA, Python MT5 package and MCP. It must distinguish connection health, quote freshness,
clock uncertainty and entry readiness. A healthy connection is not a fresh-market pass.
The offline UI also retains sampled incidents and advisor answers across resume,
accepts explicitly bound telemetry files, and displays manual calendar events and
lesson eligibility. Searchable evidence trails, retained-incident pagination and
bounded report export support operational review. Live collectors and remote deployment remain separate work.

The owner authorized M4 development after closing M3's completed research scope.
This does not relax the two-second entry ceiling or authorize connected trading.
