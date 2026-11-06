from dataclasses import replace
from uuid import uuid4

import pytest
from test_dashboard import TOKEN
from test_dashboard_operator import OPERATOR, confirm, preview

from fx_talanta.clock import FakeClock
from fx_talanta.dashboard.app import Dashboard
from fx_talanta.dashboard.demo import AT
from fx_talanta.dashboard.models import Snapshot
from fx_talanta.domain.models import Environment
from fx_talanta.gateway.offline import Gateway
from fx_talanta.research.offline import make_intent, market_at, warmup
from fx_talanta.storage.bootstrap import bootstrap
from fx_talanta.storage.config import fixture_account


@pytest.mark.integration
def test_operator_confirmed_close_and_restart_use_real_durable_gateway(settings, tmp_path):
    isolated = replace(settings, namespace="m5_ops_" + uuid4().hex[:12])
    bootstrap(isolated)
    account = fixture_account(Environment.PAPER)
    clock = FakeClock(AT)
    run_id = uuid4()
    dsn = isolated.runtime_dsn(Environment.PAPER)
    g = Gateway(dsn, account, run_id, clock)
    warmup(g, clock)
    g.submit(make_intent(g), market_at(clock.now()))
    position = next(p.position_id for p in g.broker.book.positions if p.volume)
    snapshot = Snapshot(
        label="Isolated CI simulator", source="SYNTHETIC", account=account, captured_at=AT
    )
    app = Dashboard(
        snapshot,
        tmp_path,
        TOKEN,
        clock,
        operator_gateway=g,
        operator_market=lambda: market_at(clock.now()),
        operator_token=OPERATOR,
    )
    try:
        p = preview(app, "CLOSE_OWNED_POSITION", position)
        result = confirm(app, p)
        assert result["status"] == "COMPLETED"
        calls = tuple(g.broker.book.calls)
        assert not any(p.volume for p in g.broker.book.positions)
    finally:
        app.close()
        g.close()
    g = Gateway(dsn, account, run_id, clock)
    app = Dashboard(
        snapshot,
        tmp_path,
        TOKEN,
        clock,
        operator_gateway=g,
        operator_market=lambda: market_at(clock.now()),
        operator_token=OPERATOR,
    )
    try:
        assert confirm(app, p) == result
        assert tuple(g.broker.book.calls) == calls
        assert not any(p.volume for p in g.broker.book.positions)
    finally:
        app.close()
        g.close()
