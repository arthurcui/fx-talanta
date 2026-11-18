"""Isolated synthetic improvement UI fixture. No credentials or broker access."""

import sys
from pathlib import Path

from test_candidate_research import registration
from test_research_improvement import answer

from fx_talanta.clock import FakeClock
from fx_talanta.dashboard.app import Dashboard
from fx_talanta.dashboard.demo import AT, demo
from fx_talanta.dashboard.server import make_server

state, session = map(Path, sys.argv[1:3])
app = Dashboard(demo(), state, "fixture-improvement-token-at-least-32-characters", FakeClock(AT))
reg = app.research.register(registration(app))
original = app.research.execute(dict(registration_id=reg["id"], partition="training"))
rules = dict(original["payload"]["rules"], signal_period=19)
app.research.transport = lambda _: answer(rules)
server = make_server(app, port=0, local_workspace=True)
session.write_text(
    "http://127.0.0.1:"
    + str(server.server_address[1])
    + "/strategies/results?candidate="
    + original["payload"]["candidate_sha256"]
)
server.serve_forever()
