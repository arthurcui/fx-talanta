# FX-Talanta

M0A–M0C implement the portable Python offline foundation from the
[architecture plan](docs/architecture-plan.md).
It records scripted decisions, news revisions, conversations, execution observations,
experience, lessons, artifacts, and promotion evidence in PostgreSQL. M0B adds
deterministic risk sizing, reservations, a durable simulated broker, protective
management and restart reconciliation. M0C adds the application image, isolated
task setup, and verified two-account export/restore.

**Current implementation:** M0A–M0C offline foundation, read-only CMC/FOREX
observers, manual BLS calendar upload/reminders, provider journal/filtering and
bounded native MCP calendar import. Broker execution and LIVE remain disabled.
The `demo` and `offline-demo` commands use fixtures/SIMULATOR only.

**Qualification concluded without a pass:** CMC halted; FOREX and the provider
campaign were stopped at the owner's request. See the
[broker conclusions](docs/broker-campaign-conclusion.md) and
[provider conclusion](docs/provider-campaign-conclusion.md). No campaign is
restarted by this plan; historical evidence remains unchanged.

**Design direction:** Python proposes, deterministic backend risk reserves an
allowance, and one fixed reviewed EA per account would independently authorize,
execute, protect and reconcile connected orders. The EA is not implemented or
deployed. The existing Python gateway stays simulator-only. See the
[migration and milestone gates](docs/design-migration.md),
[decision trace and EA boundary](docs/ea-execution-boundary.md) and
[ADR-001](docs/adr/001-fixed-ea-execution.md).

**Next: finish M1 qualification**, preserving completed M0A–M0C and all failed
or stopped evidence. New qualification work still needs its own plan/authorization.
Then follow M2A protocol → M2B fixed EA → M2C deterministic safety → M2D connected
PAPER acceptance, followed by M3 baseline/replay, M4 AI/advisor, M5 unattended
PAPER, M6 capped LIVE and M7 evaluated evolution.

The first proposed M2 PR is [M2A intent/EA protocol](docs/m2-handoff.md): additive
contracts, reference vectors and a fixture-only harness, with broker submission
absent. Native/Tester and read-only shadow remain evidence gates within M2B/M2C;
they are not separate milestone names. M2B cannot enable connected orders before
M2C safety and M1 prerequisites pass. This design starts no implementation,
diagnostics, services or campaigns.

CMC remains first and FOREX.com the independent comparison, with no automatic
failover. [P0 feasibility](docs/p0-feasibility.md), [M1 handoff](docs/m1-handoff.md)
and [demo rollover](docs/demo-account-rollover.md) retain unresolved permissions,
source qualification and operational prerequisites.

## Quick start on Windows

Requirements: Python 3.11+ and Docker Desktop with Linux containers, or an isolated
native PostgreSQL 17 instance. Run these commands from the repository directory:

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -c requirements.lock -e '.[dev]'
.venv\Scripts\fx-talanta init-local
docker compose up -d --wait postgres
.venv\Scripts\fx-talanta migrate
.venv\Scripts\fx-talanta demo
.venv\Scripts\fx-talanta offline-demo
.venv\Scripts\fx-talanta observer-demo
.venv\Scripts\python -m pytest --integration -q
.venv\Scripts\ruff check src tests scripts
.venv\Scripts\ruff format --check src tests scripts
```

`init-local` generates three different local database passwords in ignored `.env`
and refuses to overwrite an existing file. The fixture container listens only on
`127.0.0.1:55432`, uses the Compose project `fx-talanta-m0a`, and stores data in its
own named volume. It does not use another project's database.

If a restricted host prevents `venv` from installing pip, use the host pip to target
the environment: `python -m pip --python .venv install -c requirements.lock -e '.[dev]'`. Installing
dependencies and accessing Docker/PostgreSQL may require host network permissions.

## Native setup and Unix shells

For native application execution, Compose can supply PostgreSQL. On Linux/macOS:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -c requirements.lock -e '.[dev]'
.venv/bin/fx-talanta init-local
docker compose up -d --wait postgres
.venv/bin/fx-talanta migrate
.venv/bin/fx-talanta demo
.venv/bin/fx-talanta offline-demo
.venv/bin/python -m pytest --integration -q
```

For native PostgreSQL, skip `docker compose`, use an isolated local PostgreSQL 17
cluster, and set `FX_DB_HOST`, `FX_DB_PORT`, `FX_DB_ADMIN_USER`, and
`FX_DB_ADMIN_PASSWORD` in `.env` to match it. Preserve the independently generated
`FX_PAPER_PASSWORD` and `FX_LIVE_PASSWORD`. Then run `migrate`. Administrative setup
requires permission to create databases and roles; runtime repositories use the
limited writer credentials. Bootstrap accepts loopback hosts (plus the `postgres`
service in the explicit Docker profile). It creates `fx_paper` and `fx_live` by
default; `FX_DB_NAMESPACE` selects an isolated pair with matching separate roles.
It never substitutes SQLite.

The package supports Python 3.11+. The acceptance profiles use Windows/Python 3.14,
the Python 3.14 application image, and Linux/Python 3.11 with native PostgreSQL 17.
All profiles use `requirements.lock`, the same package, commands, migrations and tests.

## Application container and task profile

After `init-local`, run the package inside its image:

```sh
docker compose build app
docker compose up -d --wait postgres
docker compose run --rm admin migrate
docker compose run --rm app offline-demo
```

`app` has only the PAPER database password, runs as a nonroot user on a read-only
filesystem, and uses an internal network. `admin` is the separate migration and
archive tool with both fixture database credentials. Images contain code and
dependencies; the existing `fx-talanta-m0a_postgres_data` volume retains history.
No UI or externally connected broker is included.

For a Linux Codex task with Python/venv and native PostgreSQL 17 available:

```sh
python3 scripts/codex_setup.py
python3 scripts/codex_run.py test
python3 scripts/codex_run.py offline-demo
```

Setup chooses Docker when available and otherwise starts a private native
PostgreSQL cluster. It creates fresh fixture credentials under ignored
`.local/codex`, and the runner excludes inherited credentials. See
[M0C setup, restore and acceptance](docs/m0c.md) for cloud environment installation,
startup, archive transfer, and the offline test harness.

## Repeatable demo and inspection

For an existing M0A/M0B installation, run `fx-talanta migrate` to apply migrations 003–004
without resetting records or replacing the database volume. Then run
`fx-talanta offline-demo` for the M0B loop: reserve risk, lose a simulated send
response, restart the gateway, discover the fill, verify its stop, and close at
the holding cutoff. The JSON summary includes the simulation ID, states, retained
reservation, entry-submission count and realized net P&L. Each invocation creates
a separate synthetic research ledger. See [M0B details](docs/m0b.md).

```powershell
.venv\Scripts\fx-talanta demo --run-id 6fc5695e-880f-4be9-af32-fdbb16409c20
.venv\Scripts\fx-talanta history --run-id 6fc5695e-880f-4be9-af32-fdbb16409c20
.venv\Scripts\fx-talanta history --environment LIVE
```

The demo records **31 records**, including VALID, HOLD, MALFORMED, EXPIRED and
REJECTED decisions; a scripted risk evaluation and execution rejection; an
unknown execution followed by a recorded reconciliation observation; original,
late-observed and corrected news; and English/Chinese chat fixtures. Two exact
pause messages produce INTERPRETED command records. No command is executed.

Run the same ID again to exercise idempotent delivery. Omitting `--run-id` creates
a new run. Every record contains its account, provenance, timestamps, versions,
correlation ID, costs and exact evidence references. All fixture times are fixed
at and after 2026-01-05 12:00 UTC; they are not current market observations.

`history` returns the original records and all superseding corrections. The
unknown-to-reconciled fixture discovers an open synthetic fill, so its economic
outcome remains UNKNOWN rather than inventing realized P&L.

## Tests and persistence

`pytest --integration` runs the complete suite against the configured local
PostgreSQL cluster and fails if it is unavailable. Plain `pytest` runs contract
tests and explicitly skips PostgreSQL tests. Tests append uniquely scoped fixture
records and do not delete history. Re-running migrations preserves data and
verifies applied SQL checksums.

The suite checks fresh-process durability, account/database isolation, append-only
privileges, corrections, concurrent duplicate delivery, atomic rollback, exact
news versions and historical availability, and safe conversation recording.
To verify a database-service restart manually:

```powershell
docker compose restart postgres
docker compose up -d --wait postgres
.venv\Scripts\fx-talanta history --run-id 6fc5695e-880f-4be9-af32-fdbb16409c20
```

`docker compose stop postgres` stops the local service while retaining its volume.
Keep `.env` with the corresponding local volume; generating new passwords does
not change passwords in an existing PostgreSQL cluster. `export`, `restore`, and
`verify-restore` transfer both histories into an empty destination without copying
credentials. Restore initially blocks runtime writes and execution. Follow the
[handoff procedure](docs/m0c.md#export-and-restore) before releasing that guard.

## Implementation map

| Path | Responsibility |
| --- | --- |
| `src/fx_talanta/domain/models.py` | Immutable, validated contracts and separate outcome axes |
| `src/fx_talanta/storage/` | Account-bound repository, privileged bootstrap and SQL migrations |
| `src/fx_talanta/agent/scripted.py` | DecisionSource, scripted responses and durable attempts |
| `src/fx_talanta/brokers/protocol.py` | BrokerAdapter observation interface and fixture playback |
| `src/fx_talanta/brokers/simulator.py` | Durable simulated orders, fills, positions and costs |
| `src/fx_talanta/gateway/offline.py` | Sole offline mutation path, protection and reconciliation |
| `src/fx_talanta/risk/governor.py` | Decimal-safe sizing, exposure, cash-flow and loss accounting |
| `src/fx_talanta/storage/offline.py` | Session-fenced append-only simulator/gateway checkpoints |
| `src/fx_talanta/storage/archive.py` | Checksummed two-account snapshots and blocked, resumable restore |
| `Dockerfile`, `compose.yaml` | Application image, private runtime network and persistent PostgreSQL |
| `scripts/codex_setup.py`, `scripts/codex_run.py` | Isolated task service setup and shared commands |
| `scripts/profile_acceptance.py` | Native/container/task archive-transfer acceptance |
| `src/fx_talanta/advisor/fixtures.py` | Exact scripted chat interpretation and command records |
| `src/fx_talanta/clock.py` | Injected clock interface and deterministic fake clock |
| `src/fx_talanta/fixtures.py` | End-to-end M0A recording demonstration |
| `tests/` | Contract and actual PostgreSQL acceptance tests |
| `docs/m0a.md` | Storage guarantees, trust boundaries and next-increment interfaces |
| `docs/architecture-plan.md` | Architecture and implementation plan |

The portable core does not import MetaTrader5. Provider ingestion is implemented
with qualification gaps; production model access, owner authentication, the
trading dashboard and live activation remain later work. The manual BLS tool
already has a local desktop file chooser. GitHub's required `M0A checks` job name
is retained for branch-protection compatibility and now runs the entire suite.

## Documentation

Project specifications, implementation notes and operating instructions are maintained
in this repository and reviewed alongside code changes. No private page or chat is
required to understand or run the project. External links provide public vendor
references; project requirements and procedures are recorded here.

| Document | Purpose |
| --- | --- |
| [Architecture and implementation plan](docs/architecture-plan.md) | Full planning baseline, system design, milestones and acceptance criteria |
| [Fixed EA decision](docs/adr/001-fixed-ea-execution.md) | Dated authority decision and alternatives |
| [EA boundary and operating design](docs/ea-execution-boundary.md) | Worked decision, protocol, lost acknowledgment, state/actions and deployment/restore |
| [Design migration](docs/design-migration.md) | Actual baseline, old-to-new map, milestone gates and boundary test matrix |
| [First M2 implementation slice](docs/m2-handoff.md) | Exact offline-only scope; no deployment or broker execution |
| [FOREX.com onboarding](docs/forex-onboarding.md) | Secondary demo preparation, expiry tracking and durable alerts |
| [Provider qualification](docs/provider-qualification.md) | Free-first calendar/news preflight, measured endpoint checks and remaining gates |
| [Required provider acceptance](docs/provider-acceptance.md) | USD/EUR/JPY coverage inventory, expanded official feeds and prospective delivery checks |
| [Calendar/news filtering](docs/calendar-news-filter.md) | Fixture-based blackouts, coverage gates and point-in-time evidence |
| [Calendar/news integration](docs/calendar-news-integration.md) | Broker-independent collection, durable journal and qualification gaps |
| [Native MCP calendar](docs/native-mcp-calendar.md) | Optional Python ingestion, atomic cursor replay and actual CMC shadow evidence |
| [Manual BLS upload](docs/manual-bls-upload.md) | File chooser, preserved calendars and on-demand review reminders |
| [M0A](docs/m0a.md) | Records, storage and account contracts |
| [M0B](docs/m0b.md) | Offline execution, risk and reconciliation |
| [M0C](docs/m0c.md) | Portable deployment profiles and archive transfer |
| [Broker and data feasibility](docs/p0-feasibility.md) | Broker selection, evidence and outstanding qualification |
| [M1 handoff](docs/m1-handoff.md) | Read-only observation scope and acceptance gates |
| [Observer foundation](docs/observer-foundation.md) | Synthetic observer behavior and recovery checks |
| [MT5 observer](docs/mt5-observer.md) | Windows setup, account binding, permissions and observation commands |
| [CMC read-only milestone](docs/cmc-readonly.md) | Supervised run, recovery, clock policy and 24-hour acceptance |
| [Demo account rollover](docs/demo-account-rollover.md) | FOREX.com expiry and replacement-account requirements |
