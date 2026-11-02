# FX-Talanta

M0A implements the portable Python record foundation from the
[architecture plan](https://chatgpt.com/space/page_33b155951df08191a6bd0d477c965002).
It records scripted decisions, news revisions, conversations, execution observations,
experience, lessons, artifacts, and promotion evidence in PostgreSQL.

**Current scope: M0A only.** Both account bindings have execution disabled. The demo
uses synthetic PAPER/SIMULATOR evidence, performs zero broker mutations, and needs
no broker or LLM credentials. LIVE is a separate, disabled database namespace for
account-isolation tests; its fixture identity is not a real trading account.

## Quick start on Windows

Requirements: Python 3.11+ and Docker Desktop with Linux containers, or an isolated
native PostgreSQL 17 instance. Run these commands from the repository directory:

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -e '.[dev]'
.venv\Scripts\fx-talanta init-local
docker compose up -d --wait postgres
.venv\Scripts\fx-talanta migrate
.venv\Scripts\fx-talanta demo
.venv\Scripts\python -m pytest --integration -q
.venv\Scripts\ruff check src tests
.venv\Scripts\ruff format --check src tests
```

`init-local` generates three different local database passwords in ignored `.env`
and refuses to overwrite an existing file. The fixture container listens only on
`127.0.0.1:55432`, uses the Compose project `fx-talanta-m0a`, and stores data in its
own named volume. It does not use another project's database.

If a restricted host prevents `venv` from installing pip, use the host pip to target
the environment: `python -m pip --python .venv install -e '.[dev]'`. Installing
dependencies and accessing Docker/PostgreSQL may require host network permissions.

## Native setup and Unix shells

The application itself runs natively; Compose supplies only PostgreSQL. On Linux/macOS:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/fx-talanta init-local
docker compose up -d --wait postgres
.venv/bin/fx-talanta migrate
.venv/bin/fx-talanta demo
.venv/bin/python -m pytest --integration -q
```

For native PostgreSQL, skip `docker compose`, use an isolated local PostgreSQL 17
cluster, and set `FX_DB_HOST`, `FX_DB_PORT`, `FX_DB_ADMIN_USER`, and
`FX_DB_ADMIN_PASSWORD` in `.env` to match it. Preserve the independently generated
`FX_PAPER_PASSWORD` and `FX_LIVE_PASSWORD`. Then run `migrate`. Administrative setup
requires permission to create databases and roles; runtime repositories use the
limited writer credentials. Bootstrap accepts loopback hosts only and creates the
reserved `fx_paper` and `fx_live` databases. It never substitutes SQLite.

The supported contract targets Python 3.11+; this increment was exercised on
Windows with Python 3.14 and PostgreSQL 17. Cross-profile deployment acceptance,
an application image, and checked Codex-cloud setup belong to M0C.

## Repeatable demo and inspection

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
not change passwords in an existing PostgreSQL cluster. Export/restore automation
and migration between hosts are M0C work.

## Implementation map

| Path | Responsibility |
| --- | --- |
| `src/fx_talanta/domain/models.py` | Immutable, validated contracts and separate outcome axes |
| `src/fx_talanta/storage/` | Account-bound repository, privileged bootstrap and SQL migrations |
| `src/fx_talanta/agent/scripted.py` | DecisionSource, scripted responses and durable attempts |
| `src/fx_talanta/brokers/protocol.py` | BrokerAdapter observation interface and fixture playback |
| `src/fx_talanta/advisor/fixtures.py` | Exact scripted chat interpretation and command records |
| `src/fx_talanta/clock.py` | Injected clock interface and deterministic fake clock |
| `src/fx_talanta/fixtures.py` | End-to-end M0A recording demonstration |
| `tests/` | Contract and actual PostgreSQL acceptance tests |
| `docs/m0a.md` | Storage guarantees, trust boundaries and next-increment interfaces |
| `docs/architecture-plan.md` | Source specification snapshot |

The portable core does not import MetaTrader5. Actual risk sizing, reservations,
order-state transitions and recovery logic are M0B; real news ingestion, model
access, authentication, UI and live activation remain later work.
