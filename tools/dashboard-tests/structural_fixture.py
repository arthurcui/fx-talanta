"""Headless structural workflow fixture. Synthetic inputs; no external APIs."""

import sys
from pathlib import Path
from uuid import uuid4

from test_candidate_research import specification
from test_structural_research import scenario

from fx_talanta.clock import FakeClock
from fx_talanta.dashboard.app import Dashboard
from fx_talanta.dashboard.datasets import Bundle
from fx_talanta.dashboard.demo import AT, demo
from fx_talanta.dashboard.server import make_server

state, session = map(Path, sys.argv[1:3])
catalog = state.parent / "catalog"
catalog.mkdir()
data, experiment = scenario()
(catalog / "structural-bundle.json").write_text(
    Bundle(
        dataset=data,
        experiment=experiment,
        minimum_closed_trades=1,
        maximum_drawdown_fraction="0.05",
    ).model_dump_json()
)
app = Dashboard(
    demo(),
    state,
    "synthetic-structural-token-at-least-32",
    FakeClock(AT),
    dataset_directory=catalog,
)
spec = specification()
spec.update(
    name="Structural synthetic workflow", risk_per_trade_pct="0.10", total_open_risk_pct="0.10"
)
saved = app.strategies.save(
    dict(request_id=str(uuid4()), strategy_id=str(uuid4()), specification=spec)
)
app.strategies.freeze(dict(sha256=saved["sha256"]))
server = make_server(app, port=0, local_workspace=True)
session.write_text(
    "http://127.0.0.1:"
    + str(server.server_address[1])
    + "/strategies/backtest?candidate="
    + saved["sha256"]
)
server.serve_forever()
