"""Exercise native -> app container -> native and native -> task PostgreSQL.

Requires built Compose app/codex-test images and the configured local fixture DB.
Creates uniquely named databases and ignored artifacts; never resets history.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]


def run(command):
    subprocess.run(command, cwd=ROOT, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--docker", default=shutil.which("docker") or "docker")
    args = parser.parse_args()
    token = uuid4().hex[:10]
    artifacts = ROOT / ".local" / "parity" / token
    artifacts.mkdir(parents=True)
    fixture = ROOT / "scripts" / "profile_fixture.py"
    run(
        [
            sys.executable,
            str(fixture),
            "--namespace",
            f"fx_parity_src_{token}",
            "prepare",
            str(artifacts / "native"),
        ]
    )
    user = ["--user", f"{os.getuid()}:{os.getgid()}"] if hasattr(os, "getuid") else []
    compose = [args.docker, "compose", "run", "--rm", "--no-deps"]
    run(
        [
            *compose,
            "--entrypoint",
            "python",
            "-v",
            f"{ROOT / 'scripts'}:/checks:ro",
            "app",
            "/checks/image_smoke.py",
        ]
    )
    run([*compose, "app", "offline-demo"])
    run(
        [
            *compose,
            *user,
            "--entrypoint",
            "python",
            "-v",
            f"{ROOT / 'scripts'}:/checks:ro",
            "-v",
            f"{artifacts}:/transfer",
            "admin",
            "/checks/profile_fixture.py",
            "--namespace",
            f"fx_parity_docker_{token}",
            "restore",
            "/transfer/native",
            "--output",
            "/transfer/docker",
        ]
    )
    run(
        [
            sys.executable,
            str(fixture),
            "--namespace",
            f"fx_parity_return_{token}",
            "restore",
            str(artifacts / "docker"),
        ]
    )
    # A separate PostgreSQL 17 server with no network/Docker socket; input mounted read-only.
    run(
        [
            *compose,
            "-v",
            f"{artifacts}:/transfer:ro",
            "codex-test",
            "python3 scripts/codex_setup.py --skip-install && "
            "python3 scripts/codex_run.py parity --namespace fx "
            "restore /transfer/native",
        ]
    )
    print(
        json.dumps(
            {
                "native_to_container_to_native": "passed",
                "native_to_task_postgres": "passed",
                "artifacts": str(artifacts),
            }
        )
    )


if __name__ == "__main__":
    main()
