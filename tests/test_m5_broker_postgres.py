from dataclasses import replace
from uuid import uuid4

import psycopg
import pytest
from test_dashboard_broker import observation

from fx_talanta.dashboard.broker_view import BrokerView, readonly_connection
from fx_talanta.dashboard.demo import AT
from fx_talanta.domain.models import Environment
from fx_talanta.storage.bootstrap import bootstrap
from fx_talanta.storage.repository import Repository


@pytest.mark.integration
def test_actual_postgres_reader_cannot_write_and_preserves_record(settings):
    record, config = observation()
    isolated = replace(settings, namespace="m5_read_" + uuid4().hex[:12])
    bootstrap(isolated, paper_account=config.account)
    dsn = isolated.runtime_dsn(Environment.PAPER)
    repo = Repository(dsn, config.account)
    repo.append(record)
    value = BrokerView(config, dsn).read(AT)
    assert value["state"] == "HEALTHY" and not value["entry_ready"]
    with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
        with readonly_connection(dsn) as conn:
            conn.execute(
                "INSERT INTO fx.records(record_id,kind,recorded_at,supersedes,payload) "
                "SELECT record_id,kind,recorded_at,supersedes,payload FROM fx.records "
                "ON CONFLICT(record_id) DO NOTHING"
            )
    assert repo.get(record.record_id) == record
