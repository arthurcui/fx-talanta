"""Standard-library helpers for an isolated, credential-free task profile."""

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / ".local" / "codex"
ENV_FILE = STATE / ".env"
PYTHON = ROOT / ".venv" / "bin" / "python"
KEYS = {
    "FX_DB_HOST",
    "FX_DB_PORT",
    "FX_DB_ADMIN_USER",
    "FX_DB_NAMESPACE",
    "FX_PROFILE",
    "FX_DB_ADMIN_PASSWORD",
    "FX_PAPER_PASSWORD",
    "FX_LIVE_PASSWORD",
}


def clean_environment():
    # Inherited broker, LLM, cloud and local DB credentials never reach test code.
    home = STATE / "home"
    home.mkdir(parents=True, exist_ok=True, mode=0o700)
    return {
        key: os.environ[key] for key in ("PATH", "LANG", "LC_ALL", "TMPDIR") if key in os.environ
    } | {"HOME": str(home), "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUNBUFFERED": "1"}


def task_environment():
    values = dict(line.split("=", 1) for line in ENV_FILE.read_text().splitlines() if line)
    if set(values) != KEYS or any(
        values[k] != v
        for k, v in {
            "FX_DB_HOST": "127.0.0.1",
            "FX_DB_ADMIN_USER": "postgres",
            "FX_DB_NAMESPACE": "fx",
            "FX_PROFILE": "codex",
        }.items()
    ):
        raise ValueError("task settings must name the isolated local fixture service")
    if any(len(values[key]) < 24 for key in KEYS if key.endswith("PASSWORD")):
        raise ValueError("task settings require generated fixture credentials")
    return clean_environment() | values
