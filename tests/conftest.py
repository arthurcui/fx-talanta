from uuid import uuid4

import pytest

from fx_talanta.domain.models import Environment
from fx_talanta.research.records import run_demo
from fx_talanta.storage.bootstrap import bootstrap
from fx_talanta.storage.config import Settings, fixture_account
from fx_talanta.storage.repository import Repository


def pytest_addoption(parser):
    parser.addoption("--integration", action="store_true", help="run actual PostgreSQL tests")


def pytest_collection_modifyitems(config, items):
    if not config.getoption("--integration"):
        for item in items:
            if "integration" in item.keywords:
                item.add_marker(pytest.mark.skip(reason="pass --integration for PostgreSQL"))


@pytest.fixture(scope="session")
def settings():
    settings = Settings.load()
    bootstrap(settings)
    return settings


@pytest.fixture
def repo(settings):
    return Repository(settings.runtime_dsn(Environment.PAPER), fixture_account(Environment.PAPER))


@pytest.fixture
def demo(repo):
    run_id = uuid4()
    result = run_demo(repo, run_id)
    return run_id, result


@pytest.fixture
def historical_source():
    """Historical evidence pins its original source, never a later revision."""
    import hashlib
    import json
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]

    paths = json.loads((root / "docs/architecture/path-migration.json").read_text())["paths"]

    def read(name, expected):
        current_path = root / paths.get(name, name)
        current = current_path.read_bytes() if current_path.is_file() else b""
        if hashlib.sha256(current).hexdigest() == expected:
            return current
        archived = root / "tests/fixtures/source-archive" / (expected + ".txt")
        data = archived.read_bytes()
        assert hashlib.sha256(data).hexdigest() == expected
        return data

    return read
