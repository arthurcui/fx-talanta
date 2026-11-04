"""Synthetic terminal responses, including hung-call and crash injection."""

import os
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from fx_talanta.domain.models import ObservedBar, ObservedSymbol, ObservedTick, TerminalSnapshot


@dataclass(frozen=True)
class FixtureReader:
    fault: str = "NONE"

    def __call__(self, binding, now):
        if self.fault == "HANG":
            time.sleep(120)
        if self.fault == "ERROR":
            raise RuntimeError("fixture failure: diagnostic text must not be persisted")
        if self.fault == "CRASH":
            os._exit(1)
        ticks, bars, symbols = [], [], []
        for name in binding.symbols:
            price = "1.10" if name == "EURUSD" else "150.00"
            symbols.append(
                ObservedSymbol(
                    symbol=name, digits=5, volume_min="0.01", volume_step="0.01", point="0.00001"
                )
            )
            ticks.append(
                ObservedTick(
                    symbol=name,
                    bid=price,
                    ask=price,
                    at=now - timedelta(seconds=10 if self.fault == "STALE" else 0),
                )
            )
            for period in (900, 3600):
                opened = datetime.fromtimestamp((int(now.timestamp()) // period - 1) * period, UTC)
                bars.append(
                    ObservedBar(
                        symbol=name,
                        opened_at=opened,
                        period_seconds=period,
                        open=price,
                        high=price,
                        low=price,
                        close=price,
                    )
                )
        snapshot = TerminalSnapshot(
            account_before=binding.account,
            account_after=binding.account,
            terminal_path=binding.terminal_path,
            data_path=binding.data_path,
            build=binding.expected_build,
            currency=binding.expected_currency,
            connected=self.fault != "DISCONNECTED",
            observed_at=now,
            history_from=now - timedelta(hours=1),
            history_to=now,
            symbols=tuple(symbols),
            ticks=tuple(ticks),
            bars=tuple(bars),
            positions=(),
            orders=(),
            deals=(),
            history_complete=True,
        )
        changes = {
            "ACCOUNT": {"account_after": binding.account.model_copy(update={"login": "other"})},
            "BUILD": {"build": binding.expected_build + 1},
            "PATH": {"data_path": "C:/another-terminal"},
            "CURRENCY": {"currency": "EUR"},
            "MISSING": {"ticks": ()},
            "HISTORY": {"history_complete": False},
            "FUTURE": {"observed_at": now + timedelta(minutes=1)},
        }
        return snapshot.model_copy(update=changes.get(self.fault, {}))
