"""Headless test fixture only; never loads credentials or broker connections."""

import sys
from pathlib import Path

from test_dashboard_integration import BUDGET, response

from fx_talanta.clock import FakeClock
from fx_talanta.dashboard.app import Dashboard
from fx_talanta.dashboard.demo import AT, demo
from fx_talanta.dashboard.server import make_server

state = Path(sys.argv[1])
app = Dashboard(
    demo(),
    state,
    "fixture-token-local-only-at-least-32-characters",
    FakeClock(AT),
    model_budget=BUDGET,
    model_transport=response,
)
server = make_server(app, 0)
Path(sys.argv[2]).write_text(f"http://127.0.0.1:{server.server_port}/#token={app.token}")
try:
    server.serve_forever()
finally:
    server.server_close()
    app.close()
