import argparse
import json
from pathlib import Path
from uuid import UUID, uuid4

import psycopg

from fx_talanta.domain.models import Environment
from fx_talanta.fixtures import run_demo
from fx_talanta.storage.bootstrap import bootstrap
from fx_talanta.storage.config import Settings, fixture_account, init_local
from fx_talanta.storage.offline import WriterBusy
from fx_talanta.storage.repository import Repository


def main() -> None:
    parser = argparse.ArgumentParser(description="FX-Talanta offline records and execution")
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init-local", help="create local database secrets without overwriting")
    sub.add_parser("migrate", help="bootstrap fixture databases and verify migration checksums")
    sub.add_parser("offline-demo", help="run the M0B risk/execution/restart simulator")
    sub.add_parser("observer-demo", help="run synthetic M1A observation and recovery checks")
    export = sub.add_parser("export", help="export both stopped fixture accounts to a new archive")
    export.add_argument("archive", type=Path)
    restore = sub.add_parser(
        "restore", help="restore into empty migrated accounts, initially blocked"
    )
    restore.add_argument("archive", type=Path)
    verify = sub.add_parser(
        "verify-restore", help="verify both restored accounts before reconciliation"
    )
    verify.add_argument("archive", type=Path)
    verify.add_argument(
        "--source-retired",
        action="store_true",
        help="attest that the source writer is stopped and will not resume",
    )
    demo = sub.add_parser("demo", help="record the scripted PAPER scenarios")
    demo.add_argument("--run-id", type=UUID, default=None)
    history = sub.add_parser("history", help="print account-scoped fixture records")
    history.add_argument("--environment", choices=[e.value for e in Environment], default="PAPER")
    history.add_argument("--run-id", type=UUID, default=None)
    args = parser.parse_args()
    try:
        if args.command == "init-local":
            init_local(args.env_file)
            print("Created local database settings; secret values are not displayed.")
            return
        environment = Environment(getattr(args, "environment", "PAPER"))
        administrative = args.command in {"migrate", "export", "restore", "verify-restore"}
        settings = Settings.load(args.env_file, runtime=None if administrative else environment)
        if args.command == "migrate":
            bootstrap(settings)
            print("PAPER/LIVE fixture databases ready. Both execution bindings remain disabled.")
            return
        if args.command in {"export", "restore", "verify-restore"}:
            from fx_talanta.storage.archive import export_archive, release_restore, restore_archive

            if args.command == "export":
                result = export_archive(settings, args.archive)
            elif args.command == "restore":
                result = restore_archive(settings, args.archive)
            else:
                result = release_restore(settings, args.archive, source_retired=args.source_retired)
            print(json.dumps(result, indent=2))
            return
        if args.command == "offline-demo":
            from fx_talanta.offline_fixtures import run_offline_demo

            print(json.dumps(run_offline_demo(settings), indent=2))
            return
        if args.command == "observer-demo":
            from fx_talanta.observer.demo import run_observer_demo

            print(json.dumps(run_observer_demo(settings), indent=2))
            return
        repo = Repository(settings.runtime_dsn(environment), fixture_account(environment))
        if args.command == "demo":
            print(json.dumps(run_demo(repo, args.run_id or uuid4()), indent=2))
        else:
            print(
                json.dumps(
                    [r.model_dump(mode="json") for r in repo.history(correlation_id=args.run_id)],
                    indent=2,
                )
            )
    except psycopg.Error as error:
        # Database diagnostics can contain submitted payloads; do not echo them or DSNs.
        parser.exit(1, f"Database operation failed ({type(error).__name__}); check local setup.\n")
    except (ValueError, FileExistsError, WriterBusy) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
