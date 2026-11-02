"""Install the shared package and start a task-only PostgreSQL service on Linux.

Use native PostgreSQL when Docker is unavailable. No broker/LLM credentials are
read, copied or required. Existing task data and passwords are never reset.
"""

import argparse
import hashlib
import os
import secrets
import shutil
import subprocess
import sys
from pathlib import Path

from task_environment import ENV_FILE, PYTHON, ROOT, STATE, clean_environment, task_environment


def run(command, **kwargs):
    return subprocess.run(command, cwd=ROOT, env=clean_environment(), check=True, **kwargs)


def pg_binary(name):
    found = shutil.which(name)
    candidates = list(Path("/usr/lib/postgresql").glob(f"*/bin/{name}"))
    if found:
        return found
    if candidates:
        return str(max(candidates, key=lambda p: int(p.parent.parent.name)))
    raise ValueError("native PostgreSQL tools missing: install PostgreSQL 17 before setup")


def native(port):
    import pwd

    data, log = STATE / "pgdata", STATE / "postgres.log"
    prefix = []
    uid, gid = os.getuid(), os.getgid()
    if uid == 0:
        user = pwd.getpwnam("postgres")
        uid, gid = user.pw_uid, user.pw_gid
        prefix = ["runuser", "-u", "postgres", "--"]
    data.mkdir(mode=0o700, exist_ok=True)
    os.chown(data, uid, gid)
    log.touch(mode=0o600, exist_ok=True)
    os.chown(log, uid, gid)
    if not (data / "PG_VERSION").exists():
        password_file = data / "initial-password"
        descriptor = os.open(password_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(descriptor, "w") as stream:
                stream.write(task_environment()["FX_DB_ADMIN_PASSWORD"])
            os.chown(password_file, uid, gid)
            # initdb requires an empty data directory; keep its input outside it.
            password_file.rename(STATE / "initial-password")
            password_file = STATE / "initial-password"
            run(
                prefix
                + [
                    pg_binary("initdb"),
                    "-D",
                    str(data),
                    "-U",
                    "postgres",
                    "--auth-host=scram-sha-256",
                    "--auth-local=scram-sha-256",
                    "--pwfile",
                    str(password_file),
                ],
                stdout=subprocess.DEVNULL,
            )
        finally:
            password_file.unlink(missing_ok=True)
    status = subprocess.run(
        prefix + [pg_binary("pg_ctl"), "-D", str(data), "status"],
        env=clean_environment(),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if status.returncode:
        run(
            prefix
            + [
                pg_binary("pg_ctl"),
                "-D",
                str(data),
                "-l",
                str(log),
                "-w",
                "-t",
                "30",
                "start",
                "-o",
                f"-h 127.0.0.1 -p {port} -k {data} -c unix_socket_permissions=0700",
            ]
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", choices=["auto", "native", "docker"], default="auto")
    parser.add_argument("--port", type=int, default=55434)
    parser.add_argument("--skip-install", action="store_true")
    args = parser.parse_args()
    if sys.platform != "linux":
        parser.error(
            "Codex task setup targets Linux; use the README native/Compose setup on Windows"
        )
    if not 1024 <= args.port <= 65535:
        parser.error("choose an unprivileged PostgreSQL port")
    STATE.mkdir(parents=True, exist_ok=True, mode=0o755)
    if not ENV_FILE.exists():
        values = {
            "FX_DB_HOST": "127.0.0.1",
            "FX_DB_PORT": str(args.port),
            "FX_DB_ADMIN_USER": "postgres",
            "FX_DB_NAMESPACE": "fx",
            "FX_PROFILE": "codex",
        }
        values |= {
            key: secrets.token_urlsafe(32)
            for key in ("FX_DB_ADMIN_PASSWORD", "FX_PAPER_PASSWORD", "FX_LIVE_PASSWORD")
        }
        descriptor = os.open(ENV_FILE, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w") as stream:
            stream.write("".join(f"{key}={value}\n" for key, value in values.items()))
    if task_environment()["FX_DB_PORT"] != str(args.port):
        parser.error("existing task uses another port; preserve it when restarting")
    if not args.skip_install:
        if not PYTHON.exists():
            run([sys.executable, "-m", "venv", str(ROOT / ".venv")])
        run([str(PYTHON), "-m", "pip", "install", "-c", "requirements.lock", "-e", ".[dev]"])
    backend_file = STATE / "backend"
    backend = backend_file.read_text().strip() if backend_file.exists() else args.backend
    if args.backend != "auto" and backend != args.backend:
        parser.error("task service already uses another backend; it will not be reset or replaced")
    if backend == "auto":
        docker = shutil.which("docker")
        try:
            available = (
                docker
                and subprocess.run(
                    [docker, "info"],
                    env=clean_environment(),
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=15,
                ).returncode
                == 0
            )
        except (OSError, subprocess.TimeoutExpired):
            available = False
        backend = "docker" if available else "native"
    if backend not in {"native", "docker"}:
        parser.error("invalid saved task backend")
    if not backend_file.exists():
        backend_file.write_text(backend)
    if backend == "native":
        native(args.port)
    else:
        project = "fx-talanta-codex-" + hashlib.sha256(str(ROOT).encode()).hexdigest()[:8]
        run(
            [
                "docker",
                "compose",
                "--env-file",
                str(ENV_FILE),
                "-p",
                project,
                "up",
                "-d",
                "--wait",
                "postgres",
            ]
        )
    subprocess.run(
        [str(PYTHON), "-m", "fx_talanta.cli", "--env-file", str(ENV_FILE), "migrate"],
        cwd=ROOT,
        env=task_environment(),
        check=True,
    )
    print(f"Isolated {backend} PostgreSQL ready. Run: python3 scripts/codex_run.py test")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, subprocess.CalledProcessError) as error:
        raise SystemExit(
            f"Task setup failed ({type(error).__name__}); check prerequisites and service logs."
        ) from None
