import argparse
import json
from pathlib import Path
from uuid import UUID, uuid4

import psycopg

from fx_talanta.domain.models import Environment
from fx_talanta.fixtures import run_demo
from fx_talanta.storage.bootstrap import bootstrap
from fx_talanta.storage.config import Settings, fixture_account, init_local
from fx_talanta.storage.repository import Repository


def main() -> None:
    parser = argparse.ArgumentParser(description="FX-Talanta M0A offline records")
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init-local", help="create local database secrets without overwriting")
    sub.add_parser("migrate", help="bootstrap fixture databases and verify migration checksums")
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
        settings = Settings.load(args.env_file)
        if args.command == "migrate":
            bootstrap(settings)
            print("PAPER/LIVE fixture databases ready. Both execution bindings remain disabled.")
            return
        environment = Environment(getattr(args, "environment", "PAPER"))
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
    except (ValueError, FileExistsError) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
