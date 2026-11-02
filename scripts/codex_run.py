"""Run shared application commands/tests with only generated task credentials."""

import subprocess
import sys

from task_environment import ENV_FILE, PYTHON, ROOT, task_environment


def main():
    args = sys.argv[1:]
    if not args:
        raise SystemExit(
            "usage: python3 scripts/codex_run.py test|<fx-talanta command> [arguments]"
        )
    commands = (
        [
            [str(PYTHON), "-m", "ruff", "check", "src", "tests", "scripts"],
            [str(PYTHON), "-m", "ruff", "format", "--check", "src", "tests", "scripts"],
            [str(PYTHON), "-m", "pytest", "--integration", "-q"],
        ]
        if args == ["test"]
        else [[str(PYTHON), "-m", "fx_talanta.cli", "--env-file", str(ENV_FILE), *args]]
    )
    if args[0] == "parity":
        commands = [
            [
                str(PYTHON),
                str(ROOT / "scripts" / "profile_fixture.py"),
                "--env-file",
                str(ENV_FILE),
                *args[1:],
            ]
        ]
    for command in commands:
        result = subprocess.run(command, cwd=ROOT, env=task_environment())
        if result.returncode:
            raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
