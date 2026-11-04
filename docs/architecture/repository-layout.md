# Repository layout and migration

| Location | Purpose | Deployment boundary |
| --- | --- | --- |
| `src/fx_talanta/` | Python contracts, ingestion, journals, deterministic risk and execution coordination | Packaged application; current capability is bounded by status/activation gates |
| `src/fx_talanta/research/` | Synthetic record, advisor and observation demos | Bundled for explicit offline/demo commands; not a production strategy |
| `mql5/` | Fixed EAs and shared native runtime libraries | Reviewed native sources; never automatically attached or activated |
| `tools/dev/` | Isolated developer environments, image/profile checks | Development/CI only |
| `tools/fixtures/` | Deterministic fixture exporters | No broker credentials or submission authority |
| `tools/qualification/` | Read-only captures, probes and evidence verifiers | Explicit bounded operating procedures; not background runtime |
| `tests/` | Python contract and integration tests | Development/CI only |
| `tests/native/` | Native scripts and Strategy Tester programs | Test builds only, separate from runtime EAs |
| `tests/fixtures/` | Fixture configurations, replay data and hash-addressed historical source snapshots | Preserve exact fixture bytes |
| `configs/` | Operational example configurations | Never private bindings or secrets |
| `deploy/`, root Docker/Compose files | Runtime and isolated test-container profiles | Runtime image copies only package inputs |
| `docs/` | Product status, architecture, operating guides, evidence and history | Start at the documentation index |
| `.local/` | Ignored credentials, captures, journals and isolated worktrees | Private and excluded from Git/container context |

## Old-to-new map

| Previous layout | New location |
| --- | --- |
| Flat `scripts/` | `tools/dev/`, `tools/fixtures/`, `tools/qualification/` by responsibility |
| Native tests mixed into `mql5/` | `tests/native/<component>/` |
| Scattered Python fixture modules | `src/fx_talanta/research/` |
| Flat milestone-heavy `docs/` | `architecture/`, `operations/`, `engineering/`, `history/` |
| Long engineering README | Product README plus `docs/guides/getting-started.md` |

The [complete path map](path-migration.json) records every move from merged PR #23.
CLI command names and database schemas are unchanged. Internal fixture-module imports
and developer script paths have changed; update local development commands using the map.
Do not apply these moves to an active/frozen campaign checkout.

Evidence JSON and existing fixture/source-archive bytes are unchanged. Historical
reports deliberately retain paths and hashes from their original build. Evidence tests
resolve moved paths and verify the original hash-addressed source when current source
has changed. That proves the old report's provenance, not new native execution.

Native includes now point from the separate test tree to runtime libraries. Preserve
both trees when compiling tests (see the [development guide](../guides/development.md)).
No migration, terminal deployment, broker action or campaign is triggered by this layout.
