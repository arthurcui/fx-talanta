"""Capability-scoped read-only telemetry producers for EA, Python and MCP reads."""

from datetime import datetime

from fx_talanta.domain.ea_protocol import ChannelTelemetry
from fx_talanta.domain.models import AccountIdentity


class ChannelRecorder:
    """Record observed receipts. Heartbeats never manufacture fresh market data.

    Consumers must supply actual read outcomes; this class performs no I/O.
    Latency distributions remain absent until a separate measured timing window
    exists. Poll round-trip time is not labelled quote delivery latency.
    """

    def __init__(
        self,
        account: AccountIdentity,
        symbol: str,
        channel: str,
        capability: str,
        at: datetime,
        configured: bool = True,
    ):
        self._snapshot = ChannelTelemetry(
            account=account,
            symbol=symbol,
            channel=channel,
            capability=capability,
            measured_at=at,
            state="CONNECTING" if configured else "NOT_CONFIGURED",
        )

    def _update(self, at: datetime, **changes) -> ChannelTelemetry:
        if at < self._snapshot.measured_at:
            raise ValueError("observation time regressed")
        data = self._snapshot.model_dump() | changes | {"measured_at": at}
        self._snapshot = ChannelTelemetry.model_validate(data)
        return self._snapshot

    def heartbeat(self, at: datetime) -> ChannelTelemetry:
        return self._update(at, last_heartbeat=at)

    def success(self, at: datetime, original_tick_at: datetime | None = None):
        if self._snapshot.capability == "QUOTES":
            if original_tick_at is None:
                raise ValueError("quote success requires original tick timestamp")
            quote = dict(original_tick_at=original_tick_at, last_quote_receipt=at)
        elif original_tick_at is not None:
            raise ValueError("non-quote capability cannot claim a quote")
        else:
            quote = {}
        return self._update(at, state="HEALTHY", last_success=at, **quote)

    def failure(self, at: datetime, code: str):
        return self._update(at, state="ERROR", last_error=at, error_code=code)

    def snapshot(self, at: datetime):
        return self._update(at)
