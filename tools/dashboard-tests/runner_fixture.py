"""Isolated direct runner-view browser fixture; no external calls."""

import sys
from datetime import timedelta
from pathlib import Path

from fx_talanta.clock import FakeClock
from fx_talanta.dashboard.app import Dashboard
from fx_talanta.dashboard.demo import demo
from fx_talanta.dashboard.server import make_server
from fx_talanta.dashboard.workflow import WorkflowView
from tools.qualification.runner_operations_acceptance import run

root = Path(sys.argv[1])
result = run(root / "simulation")
clock = FakeClock(demo().captured_at + timedelta(days=1))
app = Dashboard(
    demo(),
    root / "ui",
    "fixture-runner-view-token-at-least-32-characters",
    clock,
    workflow_view=WorkflowView(
        dict(
            source_kind="OPERATIONS",
            journal=str(root / "simulation/source.sqlite"),
            plan_hash=result["report"]["binding_hash"],
        )
    ),
)
server = make_server(app, 0)
Path(sys.argv[2]).write_text(
    f"http://127.0.0.1:{server.server_port}/#token={app.token}", encoding="utf-8"
)
try:
    server.serve_forever()
finally:
    server.server_close()
    app.close()
