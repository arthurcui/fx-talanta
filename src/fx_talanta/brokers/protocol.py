"""Observation interface for M0A; sending/risk/reconciliation engines wait for M0B."""

from collections import deque
from collections.abc import Iterable
from typing import Protocol

from fx_talanta.domain.models import AccountIdentity, ExecutionEvent


class BrokerAdapter(Protocol):
    @property
    def account(self) -> AccountIdentity: ...

    def observe(self) -> ExecutionEvent:
        """Read the next recorded fixture observation, without sending any order."""
        ...


class FixtureBroker:
    def __init__(self, account: AccountIdentity, observations: Iterable[ExecutionEvent]):
        self._account = account
        self._observations = deque(observations)

    @property
    def account(self) -> AccountIdentity:
        return self._account

    def observe(self) -> ExecutionEvent:
        return self._observations.popleft()
