"""On-demand committed broker observations through a read-only PostgreSQL session.

No MT5 import, terminal action, source write or execution capability.
"""

from contextlib import contextmanager
from hashlib import sha256
from typing import Annotated, Literal
from uuid import UUID

import psycopg
from pydantic import Field, model_validator

from fx_talanta.domain.models import AccountIdentity, FrozenModel, Hash, Record


class BrokerViewConfig(FrozenModel):
    label: Annotated[str, Field(min_length=1, max_length=80)]
    account: AccountIdentity
    run_id: UUID
    binding_hash: Hash
    source: Literal["COMMITTED_OBSERVER_JOURNAL"] = "COMMITTED_OBSERVER_JOURNAL"

    @model_validator(mode="after")
    def scope(self):
        if self.account.venue != "BROKER_DEMO" or self.account.environment != "PAPER":
            raise ValueError("broker view accepts demo observation journals only")
        return self


@contextmanager
def readonly_connection(dsn):
    with psycopg.connect(
        dsn,
        connect_timeout=3,
        options="-c default_transaction_read_only=on -c statement_timeout=3000",
    ) as conn:
        conn.execute("SET TRANSACTION READ ONLY")
        yield conn


def project_observation(record, config, now):
    record = Record.model_validate(record.model_dump(mode="json"))
    if (
        record.account != config.account
        or record.correlation_id != config.run_id
        or record.body.kind != "observation"
        or record.body.binding_hash != config.binding_hash
    ):
        raise ValueError("observation scope mismatch")
    if record.recorded_at > now:
        raise ValueError("future committed observation")
    body = record.body
    result = dict(
        label=config.label,
        scope="RECORDED_BROKER_DEMO_NOT_CURRENT_RECONCILIATION",
        source_sha256=sha256(record.model_dump_json().encode()).hexdigest(),
        recorded_at=record.recorded_at.isoformat(),
        state=body.state,
        reason=body.reason,
        execution_enabled=False,
        entry_ready=False,
        current_positions="UNKNOWN",
        quote_clock="NOT_INDEPENDENTLY_VERIFIED_BY_DASHBOARD",
        snapshot=None,
    )
    if body.snapshot:
        s = body.snapshot
        if (
            s.account_before != config.account
            or s.account_after != config.account
            or s.observed_at > now
        ):
            raise ValueError("snapshot scope/time mismatch")
        age = (now - s.observed_at).total_seconds()
        result["snapshot"] = dict(
            observed_at=s.observed_at.isoformat(),
            age_seconds=age,
            display_status="RECENT_RECORDED" if age <= 15 else "STALE_RECORDED",
            connected_at_capture=s.connected,
            currency=s.currency,
            balance_at_capture=str(s.balance) if s.balance is not None else None,
            equity_at_capture=str(s.equity) if s.equity is not None else None,
            positions_at_capture=len(s.positions),
            orders_at_capture=len(s.orders),
            positions_with_stop_at_capture=sum(p.stop_loss > 0 for p in s.positions),
            history_complete_at_capture=s.history_complete,
            quote_ages_seconds={t.symbol: (now - t.at).total_seconds() for t in s.ticks},
        )
    return result


class BrokerView:
    def __init__(self, config, dsn):
        self.config = BrokerViewConfig.model_validate(config.model_dump(mode="json"))
        self._dsn = dsn

    def read(self, now):
        with readonly_connection(self._dsn) as conn:
            row = conn.execute(
                "SELECT identity,execution_enabled FROM fx.account_binding"
            ).fetchone()
            if not row or row[0] != self.config.account.model_dump(mode="json") or row[1]:
                raise ValueError("disabled account binding mismatch")
            row = conn.execute(
                "SELECT payload FROM fx.records WHERE kind='observation' "
                "AND payload->>'correlation_id'=%s ORDER BY sequence DESC LIMIT 1",
                (str(self.config.run_id),),
            ).fetchone()
            if row is None:
                return dict(
                    label=self.config.label,
                    status="NO_COMMITTED_OBSERVATIONS",
                    execution_enabled=False,
                )
            return project_observation(Record.model_validate(row[0]), self.config, now)
