"""No-order fault harness or supervised short read-only demo capability capture."""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from fx_talanta.acceptance.probe import capture, write_json
from fx_talanta.observer.mt5 import ObservationFailure


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--binding", type=Path)
    parser.add_argument("--seconds", type=int, default=30)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    folder = args.output.resolve()
    private_root = (root / ".local").resolve()
    if (
        not folder.is_relative_to(private_root)
        or folder == private_root
        or not 10 <= args.seconds <= 120
    ):
        parser.error("use a new directory inside this checkout's .local and 10..120 seconds")
    if args.worker:
        try:
            report = capture(args.binding, folder, args.seconds)
        except Exception as exc:
            # Error payloads may include native account details. Only bounded error codes escape.
            reason = getattr(exc, "reason", "") if isinstance(exc, ObservationFailure) else ""
            report = {
                "status": "BLOCKED",
                "reason": reason
                if isinstance(reason, str) and re.fullmatch("[A-Z_]{1,64}", reason)
                else type(exc).__name__,
                "execution_enabled": False,
                "qualified_for_trading": False,
                "m2d_accepted": False,
            }
        write_json(folder / "report.json", report)
        return 0 if report["status"] == "CAPTURED" else 2
    folder.mkdir(parents=True, exist_ok=False)
    inputs = [
        Path(__file__).resolve(),
        root / "src/fx_talanta/research/faults.py",
        *(root / "src/fx_talanta/acceptance").glob("*.py"),
    ]
    write_json(
        folder / "sources.json",
        {
            p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in inputs
        },
    )
    if args.binding is None:
        from fx_talanta.research.faults import run

        report = run(root, folder)
        write_json(folder / "report.json", report)
        print(
            json.dumps(
                {
                    "status": report["status"],
                    "scenarios": len(report["results"]),
                    "execution_enabled": False,
                    "m2d_accepted": False,
                }
            )
        )
        return 0 if report["status"] == "NO_ORDER_CHECKS_PASSED" else 2
    write_json(
        folder / "plan.json",
        {
            "started_at": datetime.now(UTC).isoformat(),
            "seconds": args.seconds,
            "deadline_seconds": args.seconds + 60,
            "attempts": 1,
            "execution_enabled": False,
            "qualification_campaign": False,
        },
    )
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--worker",
        "--output",
        str(folder),
        "--binding",
        str(args.binding.resolve()),
        "--seconds",
        str(args.seconds),
    ]
    # Kill only this SDK child on timeout, never a terminal or another campaign worker.
    with (
        (folder / "worker.stdout").open("xb") as stdout,
        (folder / "worker.stderr").open("xb") as stderr,
    ):
        try:
            subprocess.run(
                command,
                stdout=stdout,
                stderr=stderr,
                timeout=args.seconds + 60,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                check=False,
                env=os.environ.copy(),
            )
        except subprocess.TimeoutExpired:
            write_json(
                folder / "supervisor-timeout.json",
                {"status": "TIMEOUT", "execution_enabled": False},
            )
            print('{"status":"TIMEOUT","execution_enabled":false,"m2d_accepted":false}')
            return 2
    if not (folder / "report.json").exists():
        print('{"status":"WORKER_FAILED","execution_enabled":false,"m2d_accepted":false}')
        return 2
    report = json.loads((folder / "report.json").read_text(encoding="utf-8"))
    print(json.dumps(report))
    return 0 if report["status"] == "CAPTURED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
