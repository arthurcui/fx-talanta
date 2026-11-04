# Development and contribution

Use the [offline setup](getting-started.md) in an isolated checkout. Do not develop in
frozen campaign sources, replace their environment, or reuse their evidence namespace.

## Python checks

From the repository root with its virtual environment activated:

```sh
ruff check src tests tools
ruff format --check src tests tools
python -m pytest -q
python -m pytest --integration -q
```

Plain pytest skips PostgreSQL tests. The integration invocation requires the isolated
database configuration and fails if it cannot connect. Tests append uniquely scoped
records; do not delete evidence databases to obtain a clean test run. The existing
required GitHub job name **M0A checks** is retained for branch-protection compatibility.

Direct developer commands live under `tools/dev/`. Qualification commands with package
imports should be invoked from the root as modules, for example
`python -m tools.qualification.connected_capture --help`. Read the command's operating
guide before a capture; `--help` is not permission to connect or start a campaign.

```sh
python tools/dev/codex_setup.py
python tools/dev/codex_run.py test
python tools/dev/codex_run.py offline-demo
```

The setup/runner choose an isolated Docker or native PostgreSQL profile and exclude
inherited credentials. See [M0C details](../history/m0c.md) for archive-transfer semantics.

## Containers

The runtime Dockerfile copies `src/` and packaging dependencies. It does not ship
`tools/`, tests, private `.local/` content or native test programs. The separate
`deploy/Dockerfile.codex-test` deliberately includes test inputs. Both use the same
application package, schema and dependency lock.

`docker compose build app codex-test` and the CI profile-acceptance command verify
these separate deliverables. Never reuse an active campaign's Compose project/volume
for development or run `down -v` against preserved evidence.

## Native MQL5 checks

Runtime sources are in `mql5/`; native test scripts and Tester-only EAs are under
`tests/native/`. For an isolated compilation, copy both trees beneath one temporary
MQL5 Experts project, retaining their relative paths. Compile each `.mq5` at its new
location; includes resolve to the matching runtime libraries. Do not flatten files
into a shared directory, attach test EAs to broker charts, or enable Algo Trading.
Compilation and synthetic Tester results do not prove broker execution acceptance.

Historical evidence refers to its original build layout. Use the path migration map
and hash-addressed archives when auditing it; never regenerate a historical JSON report
just because its sources moved. Current native sources need their own compilation checks.

## Changes and review

- Runtime changes belong in `src/` or native runtime libraries; synthetic fixtures go
  in `research/`, `tools/fixtures/` or `tests/fixtures/` according to how they are consumed.
- Add focused failure/recovery tests for behavioral changes. Do not weaken safety gates
  or turn historical failures into passes to accommodate refactoring.
- Update the relevant operating guide and current status when behavior changes.
- Keep public evidence sanitized. Never commit account IDs, credentials, private
  bindings, raw broker prices or local runtime journals.
- A green code PR does not authorize deployment, new demo orders or LIVE trading.
