# M0C: deployment parity and durable transfer

## Scope under the fixed EA design

This remains the implemented **offline** profile/archive procedure. The future
[EA deployment/runbook](ea-execution-boundary.md#deployment-release-and-restore-runbook-design)
adds an independently durable EA journal, compatible release hashes and actual
host/terminal fencing. Existing PostgreSQL restore/session locks alone do not
establish those properties. A future restore must reconcile both journals and
broker state while preserving losses/unknowns; no connected host is deployed here.


M0C completes the offline foundation. It packages the same Python contracts,
PostgreSQL schema, risk governor and simulator for native execution, an application
container and a Linux task workspace. It does not introduce MT5, model calls,
market feeds, a UI, real credentials or live activation.

## Profiles

| Profile | Application | Database/state | Credentials and connectivity |
| --- | --- | --- | --- |
| Native | Installed `fx-talanta` package | Local PostgreSQL 17 | Separate admin, PAPER and disabled LIVE roles |
| Docker `app` | `fx-talanta:0.3.0`, Python 3.14, nonroot/read-only | Existing PostgreSQL named volume | PAPER password only; internal network |
| Docker `tools` / `admin` | Same application image and CLI | Same persistent databases; explicit artifact mount | Administrative fixture credentials for migration/transfer |
| Codex task | Same package, constraints and tests | Private native PostgreSQL or isolated Compose project | Fresh task passwords, private home, filtered subprocess environment |
| Docker `codex` / `codex-test` | Linux acceptance harness, Python 3.11 | Native PostgreSQL 17 inside a disposable test container | No Docker socket, no external network, no inherited secrets |

The runtime image copies only the package inputs, installs a wheel, and runs as
UID 10001. Build context allowlisting excludes `.env`, `.local`, `.git`, host
environments and backups. Runtime state never goes into an image. Shared pinned
Python dependency constraints live in `requirements.lock`; base image tags still
receive upstream patch updates. This is not a bit-for-bit image reproducibility claim.

The Compose project name remains `fx-talanta-m0a` to retain existing volumes.
PostgreSQL publishes only to host loopback, with an additional internal network
for app/admin access. Existing native commands still work. The administrative
profile is deliberately separate from the PAPER-only application service.

```sh
docker compose build app
docker compose up -d --wait postgres
docker compose run --rm admin migrate
docker compose run --rm app demo
docker compose run --rm app offline-demo
```

On a persistent Docker host, use these same images and persistent volumes with
host-specific secrets and backup storage. M0C does not provision a cloud host,
managed database, continuous trading service or production gateway fencing.

## Checked Codex setup

Provision Linux, Python 3.11+ with `venv`, and PostgreSQL 17 server tools (`initdb`,
`pg_ctl`), or an available Docker daemon. PostgreSQL tools can be on `PATH` or in
`/usr/lib/postgresql/<version>/bin`. When setup runs as root, a `postgres` OS user
and `runuser` must exist; the repository path must be traversable by that user.
The checked harness supplies these prerequisites.

Use `python3 scripts/codex_setup.py` for installation. On task startup/resume use
`python3 scripts/codex_setup.py --skip-install`, then
`python3 scripts/codex_run.py test`. The current Codex environment workflow supports
an Install script and a Start skill; save these commands in the corresponding
environment setup and startup instructions, test, then publish the environment.
See the [official Cloud environments documentation](https://learn.chatgpt.com/docs/environments/cloud-environments).

Setup checks the Docker daemon and falls back to native PostgreSQL if unavailable.
`--backend native` forces that path. Native data is in `.local/codex/pgdata`, and
generated settings are in `.local/codex/.env`; Docker uses a task-specific Compose
project. Both use loopback port 55434 by default (`--port` selects another port on
initial setup). Repeated setup preserves the backend, data and passwords. It
fails on missing prerequisites or conflicting configuration instead of substituting
SQLite, resetting a cluster, or using the development `.env` credentials.

The runner passes only generated fixture DB credentials and a small environment
allowlist, with a private HOME. Do not provide broker credentials or configure
live execution endpoints for this environment. Restrict task network access to
the development dependencies/services needed; the application has only fixture
adapters. The acceptance harness additionally disables all external networking.

```sh
python3 scripts/codex_run.py migrate
python3 scripts/codex_run.py demo
python3 scripts/codex_run.py offline-demo
python3 scripts/codex_run.py history --environment LIVE
python3 scripts/codex_run.py export .local/codex/results.fxbackup
```

Copy required archives and reports to durable storage before discarding a task.
A saved workspace is not the experience database's backup policy. These scripts
support task-scoped development; they do not establish an always-on trading host.
No hosted Codex environment is created or published by this repository change.

## Export and restore

Migration 004 adds append-only restore provenance and a database-enforced guard.
Use `fx-talanta migrate` before exporting an older installation. The archive is a
versioned ZIP container with JSONL tables and a JSON manifest, not executable SQL.
It contains both account bindings, migration checksums, exact record sequence
values, evidence links, all simulator/gateway journal revisions and previous
restore provenance. All record kinds travel together: conversations, intentions,
incidents, lessons, artifacts and promotion evidence are retained alongside losses,
reservations, open positions and unresolved operations.

Migration 007 adds the no-order shadow journal. Archive version 2 includes its
account-bound hash chains and blocks restored shadow writers until release.
Version 1 archives remain readable with their original schema; restore continues
to require matching application/schema checksums. Preserve old archives instead
of editing their manifests. The native shadow inbox is a separate artifact:
database export alone does not establish a coordinated EA/peer restore.

Export takes account writer fences and table locks, and refuses an active gateway
or an incomplete restore. Checksums and counts cover each data file; publication
is atomic and refuses an existing filename. The destination filesystem must
support hard links. No role passwords, environment files, SQL functions or
application binaries are exported. Unix archive files are created with mode 0600;
protect their Windows directory with the appropriate user ACL.

1. Stop entry-producing processes and close source gateway writers. For a host
   move, disable their restart mechanism too. Keep the source stopped afterward.
2. Export both accounts to a new file: `fx-talanta export .local/history.fxbackup`.
3. Provision a destination PostgreSQL service with fresh local credentials. Use
   an empty pair of databases. `FX_DB_NAMESPACE=fx_restored` can select a separate
   pair on a local test server; its roles are independent of the source namespace.
4. Run `fx-talanta --env-file .env.restore migrate`, then
   `fx-talanta --env-file .env.restore restore .local/history.fxbackup`.
5. Verify the source writer is retired and that this is the intended complete
   archive, then run `fx-talanta --env-file .env.restore verify-restore
   .local/history.fxbackup --source-retired` (one command).
6. Reopen the **existing run ID and persisted policy** through the Gateway API.
   Startup enters `STARTUP_RECONCILE`; uncertain outcomes, protection checks and
   preserved loss limits still decide whether new exposure is allowed.

Configure `.env.restore` deliberately for the destination; `init-local` creates
fresh secrets but does not rotate an existing server's admin password. When using
another namespace on the same fixture server, use that server's admin credentials
and fresh namespace-specific writer passwords. Never overwrite the source `.env`.
Do not use `offline-demo` to resume a restored run: that command creates an
independent synthetic research ledger.

Container equivalents use the same commands through `admin`, with the archive
under `/artifacts`. Create `.local/artifacts` on the host before use. On Unix, run
archive commands with `--user "$(id -u):$(id -g)"` so the bind-mounted outputs belong
to the host user; Windows Docker Desktop uses its host mount permissions.

```sh
mkdir -p .local/artifacts
docker compose run --rm --user "$(id -u):$(id -g)" admin export /artifacts/history.fxbackup
# On the independently configured destination:
docker compose run --rm admin migrate
docker compose run --rm --user "$(id -u):$(id -g)" admin restore /artifacts/history.fxbackup
docker compose run --rm --user "$(id -u):$(id -g)" admin verify-restore /artifacts/history.fxbackup --source-retired
```

Restore rejects nonempty destinations, mismatched schemas/account identities,
corrupt data, unexpected archive members and LIVE simulator state. It keeps all
validation and append-only triggers enabled. Evidence links are re-derived by the
database and checked against the archive. Destination sequence gaps from rejected
writes are allowed, but sequence values cannot move backwards.

Cross-database import is deliberately **complete or blocked**, not falsely atomic:
both accounts are durably staged before importing data; each account import is
transactional. A crash between them leaves runtime writes blocked. Repeating the
same `restore` verifies completed imports and resumes the missing one. A different
archive cannot replace staged or existing history. Previous restore audit rows
are retained inside the new STAGED marker's `source_history`.

`verify-restore` checks both accounts before releasing their guards. If release
is interrupted between accounts, retrying uses the already released account's
durable verification marker and verifies the account that is still blocked;
legitimate new history in the released account is retained. The
`--source-retired` flag is an administrator's explicit attestation, not a mechanism
that can shut down a remote host. The M0B lock fences only a local simulated
account. Real broker identity revocation, cross-host writer leases and an external
gateway emergency journal remain broker-integration work; M0C cannot enable LIVE.

Archives are integrity-checked, not signed or encrypted. Keep trusted copies and
independent durable backups. This implementation supports fixture snapshots up to
256 MiB uncompressed and reads their tables into memory. It rejects unrecognized
state tables instead of silently excluding them. Future external market/evidence
files and gateway emergency journals require extending this archive contract when
those stores are introduced.

## Acceptance

Run the complete native suite, build both images, and exercise the task fallback
and cross-profile transfer:

```sh
python -m pytest --integration -q
docker compose build app codex-test
docker compose run --rm --no-deps codex-test
python scripts/profile_acceptance.py
```

On Windows, use `.venv\Scripts\python` and, if Docker is not on PATH, pass
`--docker "C:\Users\<user>\AppData\Local\Programs\DockerDesktop\resources\bin\docker.exe"`
to the acceptance script. PostgreSQL must already be running and migrated.

Acceptance exports a lost-response entry with a retained reservation, a separate
hard-loss-halted ledger, and both account histories. It restores from native to
the installed application wheel, back to native, and into the separate task
PostgreSQL server. It compares typed state, proves the restore guard, reconciles
the original request exactly once, and retains the loss halt. The app image smoke
check verifies nonroot execution, a read-only filesystem, PAPER-only credentials,
no MT5 import and blocked external networking.

The tests also cover corrupted archives, wrong accounts/schema, existing-history
protection, derived-link validation, active-writer refusal, interrupted imports,
runtime privilege boundaries, and preservation of restore provenance. Acceptance
creates uniquely named test databases and `.local/parity/<run>` fixture artifacts;
it does not delete history or remove persistent volumes. CI retains the required
`M0A checks` job name and runs these expanded checks before merge.
