"""Explicit server-configured historical catalog; clients select hashes, never paths."""

import hashlib
from decimal import Decimal
from pathlib import Path

from pydantic import Field

from fx_talanta.domain.models import FrozenModel
from fx_talanta.research.replay import Dataset, Experiment


class Bundle(FrozenModel):
    dataset: Dataset
    experiment: Experiment
    minimum_closed_trades: int = Field(ge=1, le=10000, strict=True)
    maximum_drawdown_fraction: Decimal = Field(gt=0, le=1)


class DatasetCatalog:
    def __init__(self, directory=None):
        self.entries = {}
        self.metadata = []
        if directory is None:
            return
        root = Path(directory).resolve(strict=True)
        paths = sorted(root.glob("*-bundle.json"))
        if len(paths) > 8:
            raise ValueError("catalog supports at most eight bounded bundles")
        for path in paths:
            if path.is_symlink() or path.resolve().parent != root:
                raise ValueError("catalog files must remain in configured directory")
            raw = self._read(path)
            bundle = Bundle.model_validate_json(raw)
            d, e = bundle.dataset, bundle.experiment
            if len(d.bars) > 2000 or len(d.events) > 5000:
                raise ValueError("catalog bundle exceeds interactive replay bounds")
            if any(e.symbol not in {q.symbol for q in event.market.quotes} for event in d.events):
                raise ValueError("dataset symbol differs from experiment")
            key = hashlib.sha256(raw).hexdigest()
            self.entries[key] = path
            self.metadata.append(
                dict(
                    id=key,
                    symbol=e.symbol,
                    name=e.name,
                    source=d.source,
                    provenance=d.provenance,
                    calendar_assumptions=d.session_calendar,
                    start=e.start.isoformat(),
                    training_end=e.training_end.isoformat(),
                    validation_end=e.validation_end.isoformat(),
                    end=e.end.isoformat(),
                    bars=len(d.bars),
                    events=len(d.events),
                    costs=e.costs.model_dump(mode="json"),
                    risk_policy=e.policy.model_dump(mode="json"),
                    minimum_closed_trades=bundle.minimum_closed_trades,
                    maximum_drawdown_fraction=str(bundle.maximum_drawdown_fraction),
                    qualification="UNQUALIFIED_RESEARCH_ONLY",
                    exposure_note=(
                        "Previously available research inputs; not a fresh independent holdout"
                    ),
                )
            )

    @staticmethod
    def _read(path):
        with path.open("rb") as stream:
            raw = stream.read(8 * 1024 * 1024 + 1)
        if len(raw) > 8 * 1024 * 1024:
            raise ValueError("catalog file too large")
        return raw

    def read(self, key):
        if key not in self.entries:
            raise ValueError("unknown dataset selection")
        path = self.entries[key]
        if path.is_symlink():
            raise ValueError("catalog file changed")
        raw = self._read(path)
        if hashlib.sha256(raw).hexdigest() != key:
            raise ValueError("dataset changed; reload configured catalog before registering")
        return Bundle.model_validate_json(raw)
