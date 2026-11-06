"""Headless test fixture only; never loads credentials or broker connections."""

import sys
from pathlib import Path
from uuid import uuid4

from test_dashboard_integration import BUDGET, response
from test_dashboard_operator import OPERATOR

from fx_talanta.clock import FakeClock
from fx_talanta.dashboard.app import Dashboard
from fx_talanta.dashboard.demo import AT, demo
from fx_talanta.dashboard.server import make_server
from fx_talanta.dashboard.service import InspectionService
from fx_talanta.domain.offline import Policy
from fx_talanta.gateway.offline import Gateway
from fx_talanta.research.offline import market_at, warmup

state = Path(sys.argv[1])
clock = FakeClock(AT)
gateway = Gateway.for_replay(demo().account, uuid4(), clock, Policy())
warmup(gateway, clock)
app = Dashboard(
    demo(),
    state,
    "fixture-token-local-only-at-least-32-characters",
    clock,
    operator_gateway=gateway,
    operator_market=lambda: market_at(clock.now()),
    operator_token=OPERATOR,
    model_budget=BUDGET,
    model_transport=response,
)
app.service = InspectionService(app, 1)
app.service.start()
if "--owner" in sys.argv:
    from test_dashboard_service import certificates

    from fx_talanta.dashboard.sessions import Owner

    certs = state / "test-certificates"
    certs.mkdir()
    certificates(certs)
    server = make_server(
        app,
        0,
        owner=Owner.create("owner", "fixture-only-long-passphrase"),
        remote_cert=certs / "server.pem",
        remote_key=certs / "server.key",
    )
    url = f"https://127.0.0.1:{server.server_port}/"
else:
    server = make_server(app, 0)
    url = f"http://127.0.0.1:{server.server_port}/#token={app.token}"
Path(sys.argv[2]).write_text(url)
try:
    server.serve_forever()
finally:
    server.server_close()
    app.service.stop()
    app.close()
    gateway.close()
