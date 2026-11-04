import importlib.util
from pathlib import Path

import pytest

from fx_talanta.domain.models import Environment
from fx_talanta.storage.config import Settings


def test_paper_runtime_requires_no_live_or_admin_credentials(monkeypatch, tmp_path):
    for name in ("FX_DB_ADMIN_PASSWORD", "FX_PAPER_PASSWORD", "FX_LIVE_PASSWORD"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("FX_PAPER_PASSWORD", "generated-paper-only")
    settings = Settings.load(tmp_path / "absent", runtime=Environment.PAPER)
    assert settings.paper_password and not settings.live_password and not settings.admin_password
    with pytest.raises(ValueError, match="administrative"):
        settings.admin_dsn()
    with pytest.raises(ValueError, match="LIVE runtime"):
        settings.runtime_dsn(Environment.LIVE)


@pytest.mark.parametrize("namespace", ["", "UPPER", "fx;DROP", "../fx", "a" * 32])
def test_namespace_cannot_escape_its_database_identifiers(namespace):
    with pytest.raises(ValueError, match="namespace"):
        Settings("127.0.0.1", 5432, "postgres", "a", "b", "c", namespace=namespace)


def test_task_runner_does_not_inherit_external_credentials(monkeypatch, tmp_path):
    path = Path(__file__).resolve().parents[1] / "tools/dev/task_environment.py"
    spec = importlib.util.spec_from_file_location("task_environment", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    values = {
        "FX_DB_HOST": "127.0.0.1",
        "FX_DB_PORT": "55434",
        "FX_DB_ADMIN_USER": "postgres",
        "FX_PROFILE": "codex",
        "FX_DB_NAMESPACE": "fx",
        "FX_DB_ADMIN_PASSWORD": "a" * 32,
        "FX_PAPER_PASSWORD": "b" * 32,
        "FX_LIVE_PASSWORD": "c" * 32,
    }
    env_file = tmp_path / ".env"
    env_file.write_text("\n".join(f"{key}={value}" for key, value in values.items()))
    monkeypatch.setattr(module, "ENV_FILE", env_file)
    monkeypatch.setattr(module, "STATE", tmp_path)
    for name in ("OPENAI_API_KEY", "MT5_PASSWORD", "AWS_SECRET_ACCESS_KEY", "FX_LIVE_PASSWORD"):
        monkeypatch.setenv(name, "must-not-inherit")
    env = module.task_environment()
    assert not any(value == "must-not-inherit" for value in env.values())
    assert env["FX_LIVE_PASSWORD"] == "c" * 32
