import argparse
import json
from dataclasses import replace
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
from pydantic import ValidationError

from fx_talanta.domain.models import Environment
from fx_talanta.fixtures import run_demo
from fx_talanta.storage.bootstrap import bootstrap
from fx_talanta.storage.config import Settings, fixture_account, init_local
from fx_talanta.storage.offline import WriterBusy
from fx_talanta.storage.repository import Repository


def main() -> None:
    parser = argparse.ArgumentParser(description="FX-Talanta offline records and execution")
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    parser.add_argument("--binding", type=Path, help="explicit local MT5 demo binding JSON")
    parser.add_argument("--namespace", help="dedicated database namespace")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init-local", help="create local database secrets without overwriting")
    sub.add_parser("migrate", help="bootstrap fixture databases and verify migration checksums")
    sub.add_parser("offline-demo", help="run the M0B risk/execution/restart simulator")
    sub.add_parser("observer-demo", help="run synthetic M1A observation and recovery checks")
    observe = sub.add_parser("observe", help="collect one read-only MT5 snapshot or retry outcome")
    observe.add_argument("--run-id", type=UUID, required=True)
    runner = sub.add_parser("observe-run", help="run a bounded read-only observation soak")
    runner.add_argument("--run-id", type=UUID, required=True)
    runner.add_argument("--duration-seconds", type=int, default=86400)
    runner.add_argument("--interval-seconds", type=int, default=30)
    runner.add_argument("--status-file", type=Path, required=True)
    runner.add_argument("--stop-file", type=Path, required=True)
    status = sub.add_parser("observe-status", help="read local health and detect a stale heartbeat")
    status.add_argument("--status-file", type=Path, required=True)
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
        if args.command == "observe-status":
            from fx_talanta.observer.runner import read_status

            status = read_status(args.status_file)
            print(json.dumps(status, indent=2))
            if status["heartbeat_state"] == "STALE":
                parser.exit(2)
            return
        if args.command == "init-local":
            init_local(args.env_file)
            print("Created local database settings; secret values are not displayed.")
            return
        environment = Environment(getattr(args, "environment", "PAPER"))
        binding = None
        if args.binding:
            from fx_talanta.observer.contracts import Binding

            binding = Binding.model_validate_json(args.binding.read_text(encoding="utf-8-sig"))
            if (
                binding.source != "MT5"
                or args.command
                not in {
                    "migrate",
                    "observe",
                    "observe-run",
                    "history",
                    "export",
                    "restore",
                    "verify-restore",
                }
                or environment != Environment.PAPER
            ):
                raise ValueError(
                    "demo binding is only valid for PAPER observation/storage commands"
                )
        if args.command in {"observe", "observe-run"}:
            if binding is None:
                raise ValueError("observe requires an explicit --binding")
            binding.require_permissions()
        administrative = args.command in {"migrate", "export", "restore", "verify-restore"}
        settings = Settings.load(args.env_file, runtime=None if administrative else environment)
        if args.namespace:
            settings = replace(settings, namespace=args.namespace)
        if binding and settings.namespace == "fx":
            raise ValueError("broker demo requires a dedicated --namespace or FX_DB_NAMESPACE")
        paper_account = binding.account if binding else None
        if args.command == "observe-run":
            from fx_talanta.observer.runner import RunnerPlan, run_observer

            status = run_observer(
                settings.runtime_dsn(environment),
                binding,
                args.run_id,
                args.status_file,
                args.stop_file,
                RunnerPlan(
                    duration_seconds=args.duration_seconds, interval_seconds=args.interval_seconds
                ),
            )
            print(json.dumps(status, indent=2))
            if status["phase"] in {"HALTED", "FAILED"}:
                parser.exit(2)
            return
        if args.command == "migrate":
            bootstrap(settings, paper_account=paper_account)
            print("Account databases ready. Both execution bindings remain disabled.")
            return
        if args.command in {"export", "restore", "verify-restore"}:
            from fx_talanta.storage.archive import export_archive, release_restore, restore_archive

            if args.command == "export":
                result = export_archive(settings, args.archive, paper_account=paper_account)
            elif args.command == "restore":
                result = restore_archive(settings, args.archive, paper_account=paper_account)
            else:
                result = release_restore(
                    settings,
                    args.archive,
                    source_retired=args.source_retired,
                    paper_account=paper_account,
                )
            print(json.dumps(result, indent=2))
            return
        if args.command == "observe":
            from fx_talanta.clock import SystemClock
            from fx_talanta.observer.mt5 import MT5Reader
            from fx_talanta.observer.supervisor import Observer

            observer = Observer(
                settings.runtime_dsn(Environment.PAPER), binding, args.run_id, SystemClock()
            )
            try:
                record = observer.poll(MT5Reader())
                print(
                    json.dumps(
                        {
                            "run_id": str(args.run_id),
                            "state": record.body.state,
                            "reason": record.body.reason,
                            "execution_enabled": False,
                        }
                    )
                )
            finally:
                observer.close()
            return
        if args.command == "offline-demo":
            from fx_talanta.offline_fixtures import run_offline_demo

            print(json.dumps(run_offline_demo(settings), indent=2))
            return
        if args.command == "observer-demo":
            from fx_talanta.observer.demo import run_observer_demo

            print(json.dumps(run_observer_demo(settings), indent=2))
            return
        repo = Repository(
            settings.runtime_dsn(environment), paper_account or fixture_account(environment)
        )
        if args.command == "demo":
            print(json.dumps(run_demo(repo, args.run_id or uuid4()), indent=2))
        else:
            print(
                json.dumps(
                    [r.model_dump(mode="json") for r in repo.history(correlation_id=args.run_id)],
                    indent=2,
                )
            )
    except ValidationError:
        parser.exit(1, "Invalid structured input; check the binding schema locally.\n")
    except psycopg.Error as error:
        # Database diagnostics can contain submitted payloads; do not echo them or DSNs.
        parser.exit(1, f"Database operation failed ({type(error).__name__}); check local setup.\n")
    except (ValueError, FileExistsError, WriterBusy) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
