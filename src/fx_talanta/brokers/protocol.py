"""Observation interface for M0A; sending/risk/reconciliation engines wait for M0B."""

from collections import deque
from collections.abc import Iterable
from typing import Protocol
from uuid import UUID

from fx_talanta.domain.models import AccountIdentity, ExecutionEvent
from fx_talanta.domain.offline import BrokerBook, BrokerOrder, BrokerRequest, Market


class BrokerAdapter(Protocol):
    @property
    def account(self) -> AccountIdentity: ...

    def observe(self) -> ExecutionEvent:
        """Read the next recorded fixture observation, without sending any order."""
        ...


class ExecutionAdapter(Protocol):
    """M0B contract; only the session-fenced offline Simulator is enabled."""

    def snapshot(self) -> BrokerBook: ...
    def lookup(self, request_id: UUID) -> BrokerOrder | None: ...
    def mutate(self, request: BrokerRequest, market: Market) -> BrokerOrder: ...


class FixtureBroker:
    def __init__(self, account: AccountIdentity, observations: Iterable[ExecutionEvent]):
        self._account = account
        self._observations = deque(observations)

    @property
    def account(self) -> AccountIdentity:
        return self._account

    def observe(self) -> ExecutionEvent:
        return self._observations.popleft()
