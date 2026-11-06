# Run the offline demonstration

These commands create a local development database and synthetic records. They do
not connect to a broker or enable trading. Use a fresh checkout/environment; do
not reuse an active qualification campaign or its database credentials.

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
.venv\Scripts\ruff check src tests tools
.venv\Scripts\ruff format --check src tests tools
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
This CLI demo includes no externally connected broker. For the separate local
read-only UI, see the [dashboard guide](dashboard.md).

For a Linux Codex task with Python/venv and native PostgreSQL 17 available:

```sh
python3 tools/dev/codex_setup.py
python3 tools/dev/codex_run.py test
python3 tools/dev/codex_run.py offline-demo
```

Setup chooses Docker when available and otherwise starts a private native
PostgreSQL cluster. It creates fresh fixture credentials under ignored
`.local/codex`, and the runner excludes inherited credentials. See
[M0C setup, restore and acceptance](../history/m0c.md) for cloud environment installation,
startup, archive transfer, and the offline test harness.

## Repeatable demo and inspection

For an existing M0A/M0B installation, run `fx-talanta migrate` to apply migrations 003–004
without resetting records or replacing the database volume. Then run
`fx-talanta offline-demo` for the M0B loop: reserve risk, lose a simulated send
response, restart the gateway, discover the fill, verify its stop, and close at
the holding cutoff. The JSON summary includes the simulation ID, states, retained
reservation, entry-submission count and realized net P&L. Each invocation creates
a separate synthetic research ledger. See [M0B details](../history/m0b.md).

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
[handoff procedure](../history/m0c.md#export-and-restore) before releasing that guard.


Return to the [documentation index](../README.md).
