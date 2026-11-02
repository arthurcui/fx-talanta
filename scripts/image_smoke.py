"""Assert the actual runtime image's credential, filesystem and network boundary."""

import errno
import importlib.util
import json
import os
import socket
from pathlib import Path

from fx_talanta.domain.models import Environment
from fx_talanta.storage.config import Settings, fixture_account
from fx_talanta.storage.repository import Repository

assert os.getuid() != 0
assert not os.environ.get("FX_DB_ADMIN_PASSWORD")
assert not os.environ.get("FX_LIVE_PASSWORD")
assert not os.environ.get("OPENAI_API_KEY")
assert importlib.util.find_spec("MetaTrader5") is None
assert not Path("/app/.env").exists()
try:
    Path("/app/should-be-read-only").write_text("probe")
except OSError as error:
    assert error.errno in {errno.EROFS, errno.EACCES}
else:
    raise AssertionError("runtime root filesystem is writable")
try:
    connection = socket.create_connection(("1.1.1.1", 443), timeout=2)
except OSError:
    pass
else:
    connection.close()
    raise AssertionError("offline runtime has external network access")
settings = Settings.load(runtime=Environment.PAPER)
Repository(settings.runtime_dsn(Environment.PAPER), fixture_account(Environment.PAPER))
print(
    json.dumps(
        {
            "runtime_user": "nonroot",
            "filesystem": "read-only",
            "external_network": "blocked",
            "credentials": "PAPER-only",
        }
    )
)
