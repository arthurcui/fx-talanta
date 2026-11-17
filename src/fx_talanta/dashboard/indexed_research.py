"""Pinned full-session catalog entries and bounded-memory candidate replay."""

from collections import Counter
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import NAMESPACE_URL, uuid5

from pydantic import Field, model_validator

from fx_talanta.domain.models import FrozenModel, Hash
from fx_talanta.research.replay import Experiment, digest, execute_timeline
from fx_talanta.research.session_study import TrackedEvents, timeline
from fx_talanta.research.spool import EquitySpool, SegmentedSpool, Spool, file_hash, rows
from fx_talanta.research.tick_index import TickIndex, milliseconds


class IndexedBundle(FrozenModel):
    index_file: str = Field(pattern=r"^[a-z0-9_-]+\.sqlite$")
    index_sha256: Hash
    experiment: Experiment
    latency_ms: int = Field(default=250, ge=0, le=10000)
    assume_research_inputs: bool = False
    minimum_closed_trades: int = Field(default=20, ge=1, le=10000)
    maximum_drawdown_fraction: float = Field(default=0.05, gt=0, le=1)
    acquired_history: bool = False

    @model_validator(mode="after")
    def bounded(self):
        for phase in ("training", "validation", "holdout"):
            start, end = self.experiment.window(phase)
            if end - start > timedelta(days=366 if self.acquired_history else 1):
                raise ValueError("each partition supports at most one full day")
        return self


def index_path(directory, bundle):
    root = Path(directory).resolve()
    path = root / bundle.index_file
    if path.is_symlink() or path.resolve().parent != root or file_hash(path) != bundle.index_sha256:
        raise ValueError("historical index binding changed")
    return path


def describe(directory, bundle, key):
    path = index_path(directory, bundle)
    index = TickIndex(path)
    try:
        e = bundle.experiment
        if index.metadata["symbol"] != e.symbol:
            raise ValueError("index symbol differs from experiment")
        windows = {}
        for phase in ("training", "validation", "holdout"):
            start, end = e.window(phase)
            n = index.db.execute(
                "SELECT count(*) FROM ticks WHERE at_ms>=? AND at_ms<?",
                (milliseconds(start) - bundle.latency_ms, milliseconds(end) - bundle.latency_ms),
            ).fetchone()[0]
            if not 1 <= n <= (50_000_000 if bundle.acquired_history else 300000):
                raise ValueError("full-session partition tick bound")
            windows[phase] = dict(
                start=start.isoformat(),
                end=end.isoformat(),
                ticks=n,
                duration_seconds=(end - start).total_seconds(),
            )
        bars = index.bars(bundle.latency_ms)
        return dict(
            id=key,
            symbol=e.symbol,
            name=e.name,
            source=f"HistData {e.symbol} SHA256 {index.metadata['archive_sha256']}",
            provenance="HISTORICAL_UNQUALIFIED",
            calendar_assumptions=(
                "Calendar/news assumed clear; receipt latency modeled; not qualified"
            )
            if bundle.assume_research_inputs
            else "Calendar/news unqualified: entries blocked",
            start=e.start.isoformat(),
            training_end=e.training_end.isoformat(),
            validation_end=e.validation_end.isoformat(),
            end=e.end.isoformat(),
            bars=len(bars),
            events=sum(w["ticks"] for w in windows.values()),
            costs=e.costs.model_dump(mode="json"),
            risk_policy=e.policy.model_dump(mode="json"),
            minimum_closed_trades=bundle.minimum_closed_trades,
            maximum_drawdown_fraction=str(bundle.maximum_drawdown_fraction),
            qualification="UNQUALIFIED_RESEARCH_ONLY",
            exposure_note="New acquisition; independent holdout and data quality not qualified"
            if bundle.acquired_history
            else ("Previously available January 2025 inputs; not an independent fresh holdout"),
            windows=windows,
            timeframes=["H1", "M15"],
            warmup_bars={
                tf: sum(b.timeframe == tf and b.available_at < e.start for b in bars)
                for tf in ("H1", "M15")
            },
            replay_mode="FULL_TICK_BACKGROUND",
        )
    finally:
        index.close()


def diagnostics(result):
    e = Experiment.model_validate(result["experiment"])
    start, end = e.window(result["partition"])
    decisions = result.get("decisions", [])
    holds = Counter(x.get("reason", "UNSPECIFIED") for x in decisions if x.get("action") == "HOLD")
    actions = Counter(x.get("action", "UNKNOWN") for x in decisions)
    return dict(
        symbol=e.symbol,
        start=start.isoformat(),
        end=end.isoformat(),
        duration_seconds=(end - start).total_seconds(),
        evaluations=actions.get("HOLD", 0) + actions.get("CANDIDATE", 0),
        actions=dict(actions),
        hold_reasons=dict(holds),
        open_positions=result.get("open_positions", 0),
        pending_signal=result.get("pending_signal", False),
        closed_trades=result["metrics"]["closed_trades"],
    )


def replay(research, plan, partition, key):
    bundle = research.catalog.read(plan.dataset_catalog_sha256)
    path = index_path(research.catalog.entries[plan.dataset_catalog_sha256].parent, bundle)
    directory = research.app.state / "research-runs" / key
    directory.mkdir(parents=True, exist_ok=False)
    index = TickIndex(path)
    journal = equity = None
    try:
        bars = index.bars(bundle.latency_ms)
        start, end = plan.experiment.window(partition)
        metadata = SimpleNamespace(
            bars=bars,
            history_complete=bundle.assume_research_inputs,
            provenance="HISTORICAL_UNQUALIFIED",
            source=f"HistData {plan.experiment.symbol} SHA256 {index.metadata['archive_sha256']}",
        )
        events = TrackedEvents(
            index.events(start, end, bundle.latency_ms, bundle.assume_research_inputs),
            start,
            end,
            maximum_ticks=50_000_000 if bundle.acquired_history else 300000,
        )
        journal = (
            SegmentedSpool(directory / "journal.manifest.json")
            if bundle.acquired_history
            else Spool(directory / "journal.jsonl.gz")
        )
        equity = EquitySpool(directory / "equity.jsonl.gz", plan.experiment.policy.capital)
        result, _ = execute_timeline(
            metadata,
            plan.experiment,
            partition,
            timeline(bars, events, start, end),
            uuid5(NAMESPACE_URL, key),
            journal_sink=journal,
            samples_sink=equity,
            signal=plan.rules.evaluate,
            strategy_version="candidate/"
            + digest(
                dict(
                    candidate=plan.candidate_sha256,
                    rules=plan.rules.model_dump(mode="json"),
                    engine=plan.engine_sha256,
                )
            ),
        )
        journal.close()
        equity.close()
        if file_hash(path) != bundle.index_sha256:
            raise ValueError("index changed during replay")
        result["coverage"] = events.report()
        step = max(1, equity.count // 300)
        result["equity_samples"] = [
            sample
            for i, sample in enumerate(rows(equity.path))
            if i % step == 0 or i == equity.count - 1
        ]
        result["audit_streams"] = {"journal": journal.receipt(), "equity": equity.receipt()}
        result["chart_note"] = (
            "Sampled display; complete tick processing and exact local audit streams preserved"
        )
        result["modeled_latency_ms"] = bundle.latency_ms
        return result, []
    finally:
        index.close()
        for sink in (journal, equity):
            if sink is not None and not sink.raw.closed:
                sink.close()
