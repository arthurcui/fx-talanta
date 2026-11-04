# Development and qualification tools

These commands are excluded from the runtime application image.

| Directory | Purpose | Examples |
| --- | --- | --- |
| [dev](dev/) | Isolated environments and cross-profile verification | `codex_setup.py`, `codex_run.py`, `profile_acceptance.py` |
| [fixtures](fixtures/) | Synthetic input/reference exporters | `demo_execution_fixtures.py`, `shadow_fixtures.py`, `m2a_reference.py` |
| [qualification](qualification/) | Bounded read-only captures, provider probes and evidence checks | `connected_capture.py`, `compare_quote_stream.py`, `probe_required_sources.py` |

Run from the repository root. Prefer `python -m tools.qualification.<module>` for
qualification modules that import other tools. Developer bootstrap commands support
direct script invocation. Consult the [development guide](../docs/guides/development.md)
and [operating guides](../docs/operations/README.md) before running a command.

Do not run tools against frozen campaign checkouts or infer trading authorization
from the presence of a script. [Path migration map](../docs/architecture/path-migration.json).
