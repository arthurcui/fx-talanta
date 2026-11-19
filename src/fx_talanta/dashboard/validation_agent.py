"""Evidence-bound research planning and staged, offline validation orchestration.

Period heuristics are versioned planning assumptions, never profitability forecasts.
The agent cannot change rules, weaken gates, or grant trading authority.
"""

import json
import math
import os
import threading
import time
from datetime import datetime, timedelta
from decimal import Decimal

from fx_talanta.research.replay import digest

POLICY = "strategy-validation/3"
TRADE_TARGETS = {"training": 100, "validation": 50, "holdout": 50}


def parse(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def sessions(start, end):
    return sum(
        (start + timedelta(days=i)).weekday() < 5
        for i in range(math.ceil((end - start).total_seconds() / 86400))
    )


def choose_plan(candidate, rules, catalog, now):
    if rules.family == "STRUCTURAL_PULLBACK":
        raise ValueError(
            "structural research uses its preregistered development dataset; "
            "register the reviewed study in Backtest, without automatic expansion"
        )
    hours = rules.end_hour_utc - rules.start_hour_utc
    if rules.entry_session != "UTC_WINDOW":
        from fx_talanta.research.market_sessions import bounds

        names = (
            ["LONDON", "NEW_YORK"]
            if rules.entry_session == "LONDON_NEW_YORK_OVERLAP"
            else [rules.entry_session]
        )
        observed = []
        for i in range(366):
            day = (now - timedelta(days=i)).replace(hour=12, minute=0, second=0, microsecond=0)
            if day.weekday() >= 5:
                continue
            windows = [bounds(name, day) for name in names]
            start = max([day.replace(hour=rules.start_hour_utc)] + [w[0] for w in windows])
            end = min([day.replace(hour=rules.end_hour_utc)] + [w[1] for w in windows])
            observed.append(max(0, (end - start).total_seconds() / 3600))
        hours = sum(observed) / len(observed)
        if not hours:
            raise ValueError("named session does not overlap the UTC cap")
    spacing = max(rules.signal_period, rules.hold_bars)
    target_days = max(126, math.ceil(sum(TRADE_TARGETS.values()) * spacing / (hours * 4)))
    end = now.replace(hour=0, minute=0, second=0, microsecond=0)
    start = end - timedelta(days=math.ceil(target_days * 7 / 5))
    boundaries = [start, start + (end - start) * 0.6, start + (end - start) * 0.8, end]
    warmup = {
        "H1": rules.trend_period + 3,
        "M15": max(
            rules.signal_period + 1 if rules.reference_window == "ROLLING" else 37,
            rules.atr_period + 1,
        ),
    }
    selected = []
    for symbol in candidate["specification"]["pairs"]:
        choices = [x for x in catalog if x["symbol"] == symbol]
        # Choose coverage before seeing outcomes. Never rank datasets by P&L.
        choices.sort(
            key=lambda x: (
                max(0, (min(parse(x["end"]), end) - max(parse(x["start"]), start)).total_seconds()),
                (parse(x["end"]) - parse(x["start"])).total_seconds(),
                x["end"],
                x["id"],
            ),
            reverse=True,
        )
        if not choices:
            selected.append(
                dict(
                    symbol=symbol,
                    dataset_id=None,
                    blockers=["NO_DATASET"],
                    available_sessions=0,
                    required_sessions=target_days,
                    exploratory_ready=False,
                )
            )
            continue
        data = choices[0]
        available = sessions(parse(data["start"]), parse(data["end"]))
        actual_warmup = data.get("warmup_bars", {})
        warmup_ok = all(actual_warmup.get(tf, 0) >= n for tf, n in warmup.items())
        blockers = []
        if available < target_days:
            blockers.append("INSUFFICIENT_HISTORY")
        if parse(data["start"]) > start or parse(data["end"]) < end:
            blockers.append("REQUESTED_PERIOD_NOT_COVERED")
        if not warmup_ok:
            blockers.append("WARMUP_NOT_VERIFIED")
        if data.get("qualification") != "QUALIFIED":
            blockers.append("SOURCE_COST_CALENDAR_UNQUALIFIED")
        if data.get("independent_holdout") is not True:
            blockers.append("INDEPENDENT_HOLDOUT_UNVERIFIED")
        windows = data.get("windows", {})
        if any(
            windows.get(phase, {}).get("start") != boundaries[i].isoformat()
            or windows.get(phase, {}).get("end") != boundaries[i + 1].isoformat()
            for i, phase in enumerate(TRADE_TARGETS)
        ):
            blockers.append("PLANNED_WINDOWS_NOT_AVAILABLE")
        selected.append(
            dict(
                symbol=symbol,
                dataset_id=data["id"],
                source=data["source"],
                available_start=data["start"],
                available_end=data["end"],
                available_sessions=available,
                required_sessions=target_days,
                missing_sessions=max(0, target_days - available),
                age_days=max(0, (end - parse(data["end"])).days),
                warmup=actual_warmup,
                blockers=blockers,
                exploratory_ready=warmup_ok and data.get("replay_mode") == "FULL_TICK_BACKGROUND",
                available_windows=data.get("windows", {}),
            )
        )
    return dict(
        policy=POLICY,
        planner="DETERMINISTIC_STRATEGY_POLICY",
        candidate_sha256=candidate["sha256"],
        rules=rules.model_dump(mode="json"),
        as_of=end.isoformat(),
        requested_start=start.isoformat(),
        requested_end=end.isoformat(),
        required_sessions=target_days,
        warmup_required=warmup,
        planned_windows={
            phase: dict(
                start=boundaries[i].isoformat(),
                end=boundaries[i + 1].isoformat(),
                minimum_closed_trades=TRADE_TARGETS[phase],
            )
            for i, phase in enumerate(TRADE_TARGETS)
        },
        rationale=[
            (
                f"H1 trend requires {warmup['H1']} completed hourly bars; M15 "
                f"signal/ATR requires {warmup['M15']} completed bars before the "
                f"test."
            ),
            (
                f"{hours:.2f} average eligible hours/weekday within session and UTC caps, "
                f"{spacing} signal/holding bars: "
                f"planning proxy only, not a measured trading frequency."
            ),
            (
                f"Request at least {target_days} trading sessions (minimum "
                f"six-month planning floor) to seek 100/50/50 closed trades across "
                f"chronological 60/20/20 windows."
            ),
            (
                "Dates and gates are fixed before results. Insufficient "
                "observations request more data; periods are never searched for "
                "better profits."
            ),
        ],
        datasets=selected,
        full_validation_ready=all(not x["blockers"] for x in selected),
        execution_enabled=False,
        qualified_for_paper=False,
    )


def assessment(result, phase):
    metrics = result["metrics"]
    ceiling = min(
        Decimal(".05"),
        Decimal(result.get("experiment", {}).get("policy", {}).get("drawdown_fraction", ".05")),
    )
    if metrics["closed_trades"] < TRADE_TARGETS[phase] or not result["fully_settled"]:
        return "MORE_OBSERVATIONS_REQUIRED"
    if (
        Decimal(result["net_realized_pnl"]) <= 0
        or Decimal(metrics["maximum_observed_drawdown_fraction"]) > ceiling
    ):
        return "REJECT_OR_REVISE"
    return "PASS_TO_NEXT_STAGE"


class ValidationAgent:
    def __init__(self, research):
        self.research = research
        self.repo = research.repo
        self.active = set()
        with self.repo.lock, self.repo.conn:
            self.repo.conn.executescript("""
                CREATE TABLE IF NOT EXISTS validation_agent_runs
                (id TEXT PRIMARY KEY, plan TEXT NOT NULL, progress TEXT NOT NULL, result TEXT);
            """)

    def plan(self, data):
        from fx_talanta.dashboard.research import indexed_engine_hash

        if set(data) == {"from_plan_id"}:
            prior = self.research.item(data["from_plan_id"])
            if prior["kind"] != "VALIDATION_PLAN":
                raise ValueError("expected prior validation plan")
            value = dict(prior["payload"])
            if value.get("engine_sha256") == indexed_engine_hash():
                raise ValueError("same engine; inspect the existing run instead")
            if self.active or self.research.active_runs:
                raise ValueError("research worker still active")
            previous = self.status(digest(dict(plan=prior["id"])))
            if previous["status"] == "RUNNING":
                raise ValueError("prior study still active")
            if value["policy"] != POLICY:
                raise ValueError("planning policy changed; review a new plan")
            value["supersedes_plan_id"] = prior["id"]
            value["engine_sha256"] = indexed_engine_hash()
            return self.research.retain("VALIDATION_PLAN", value)

        from pydantic import TypeAdapter

        from fx_talanta.domain.models import Hash
        from fx_talanta.research.candidate import ExecutableRules

        if set(data) != {"candidate_sha256", "rules"}:
            raise ValueError("invalid plan request")
        sha = TypeAdapter(Hash).validate_python(data["candidate_sha256"])
        rules = TypeAdapter(ExecutableRules).validate_python(data["rules"])
        with self.repo.lock:
            candidate = self.research.app.strategies._record(sha)
        if candidate["state"] != "FROZEN_FOR_RESEARCH":
            raise ValueError("freeze strategy before planning")
        value = choose_plan(
            candidate, rules, self.research.catalog.metadata, self.research.app.clock.now()
        )
        value["automatic_acquisition"] = os.environ.get("FX_HISTORY_ACQUISITION") == "histdata"
        from fx_talanta.dashboard.research import indexed_engine_hash

        value["engine_sha256"] = indexed_engine_hash()
        return self.research.retain("VALIDATION_PLAN", value)

    def status(self, key):
        with self.repo.lock:
            row = self.repo.conn.execute(
                "SELECT plan,progress,result FROM validation_agent_runs WHERE id=?", (key,)
            ).fetchone()
            if not row:
                raise ValueError("unknown agent run")
            plan, progress, result = map(lambda x: json.loads(x) if x else None, row)
            return dict(
                id=key,
                candidate_sha256=plan["candidate_sha256"],
                plan=plan,
                progress=progress,
                status=result["status"]
                if result
                else "RUNNING"
                if key in self.active
                else "INTERRUPTED_NO_RESEND",
                result=result,
            )

    def recent(self):
        with self.repo.lock:
            keys = [
                x[0]
                for x in self.repo.conn.execute(
                    "SELECT id FROM validation_agent_runs ORDER BY rowid DESC LIMIT 10"
                )
            ]
        return [self.status(key) for key in keys]

    def start(self, data):
        if set(data) != {"plan_id", "reviewed_mapping"} or data["reviewed_mapping"] is not True:
            raise ValueError("review rules mapping before starting agent research")
        record = self.research.item(data["plan_id"])
        if record["kind"] != "VALIDATION_PLAN":
            raise ValueError("expected validation plan")
        plan = record["payload"]
        from fx_talanta.dashboard.research import indexed_engine_hash

        if plan.get("engine_sha256") != indexed_engine_hash():
            raise ValueError("research engine changed; review a new plan")
        # Check selected catalog identities now; old plans never silently substitute data.
        for source in plan["datasets"]:
            if source["dataset_id"]:
                self.research.catalog.read(source["dataset_id"])
        if plan["policy"] != POLICY:
            raise ValueError("planning policy changed; create a new plan")
        key = digest(dict(plan=data["plan_id"]))
        with self.repo.lock, self.repo.conn:
            old = self.repo.conn.execute(
                "SELECT id FROM validation_agent_runs WHERE id=?", (key,)
            ).fetchone()
            if old:
                return self.status(key)
            if self.active or self.research.active_runs:
                raise ValueError("another research worker is active")
            self.repo.conn.execute(
                "INSERT INTO validation_agent_runs VALUES (?,?,?,NULL)",
                (key, json.dumps(plan), "[]"),
            )
            self.active.add(key)
        threading.Thread(target=self._work, args=(key, plan), daemon=True).start()
        return self.status(key)

    def _work(self, key, plan):
        progress = []
        try:
            for source in plan["datasets"]:
                if plan.get("automatic_acquisition") and any(
                    b in source["blockers"]
                    for b in (
                        "NO_DATASET",
                        "INSUFFICIENT_HISTORY",
                        "REQUESTED_PERIOD_NOT_COVERED",
                        "PLANNED_WINDOWS_NOT_AVAILABLE",
                    )
                ):
                    from fx_talanta.dashboard.indexed_research import IndexedBundle
                    from fx_talanta.research.acquisition import prepare

                    def update(value):
                        if progress and progress[-1].get("phase") == "acquisition":
                            progress[-1] = value
                        else:
                            progress.append(value)
                        self._progress(key, progress)

                    directory, receipt = prepare(
                        self.research.app.state / "history",
                        source["symbol"],
                        parse(plan["requested_start"]),
                        parse(plan["requested_end"]),
                        plan["warmup_required"]["H1"],
                        update,
                    )
                    if not source["dataset_id"]:
                        raise ValueError("no reviewed cost/risk template for acquired symbol")
                    template = self.research.catalog.read(source["dataset_id"])
                    experiment = template.experiment.model_dump(mode="json")
                    experiment.update(
                        start=plan["requested_start"],
                        end=plan["requested_end"],
                        training_end=plan["planned_windows"]["training"]["end"],
                        validation_end=plan["planned_windows"]["validation"]["end"],
                    )
                    bundle = IndexedBundle(
                        index_file="ticks.sqlite",
                        index_sha256=receipt["index_sha256"],
                        experiment=experiment,
                        acquired_history=True,
                        assume_research_inputs=True,
                        minimum_closed_trades=100,
                    )
                    manifest = directory / "acquired-index.json"
                    encoded = bundle.model_dump_json()
                    if manifest.exists() and manifest.read_text(encoding="utf8") != encoded:
                        raise ValueError("prepared registration binding changed")
                    manifest.write_text(encoded, encoding="utf8")
                    with self.repo.lock:
                        metadata = self.research.catalog.add_prepared(manifest)
                    source = dict(
                        source,
                        dataset_id=metadata["id"],
                        exploratory_ready=all(
                            metadata["warmup_bars"].get(tf, 0) >= n
                            for tf, n in plan["warmup_required"].items()
                        ),
                        blockers=[
                            "SOURCE_COST_CALENDAR_UNQUALIFIED",
                            "INDEPENDENT_HOLDOUT_UNVERIFIED",
                        ],
                    )
                    update(
                        dict(
                            symbol=source["symbol"],
                            phase="acquisition",
                            status="PREPARED",
                            receipt=receipt,
                            dataset_id=metadata["id"],
                        )
                    )
                if not source["exploratory_ready"]:
                    progress.append(
                        dict(
                            symbol=source["symbol"],
                            status="DATA_REQUIRED",
                            reasons=source["blockers"],
                        )
                    )
                    self._progress(key, progress)
                    continue
                reg = self.research.select_dataset(
                    dict(
                        dataset_id=source["dataset_id"],
                        candidate_sha256=plan["candidate_sha256"],
                        rules=plan["rules"],
                        reviewed_mapping=True,
                    )
                )
                for phase in TRADE_TARGETS:
                    if phase != "training" and source["blockers"]:
                        break
                    progress.append(
                        dict(
                            symbol=source["symbol"],
                            phase=phase,
                            status="RUNNING",
                            scope="EXPLORATORY_ONLY" if source["blockers"] else "VALIDATION",
                        )
                    )
                    self._progress(key, progress)
                    outcome = self.research._execute(
                        dict(registration_id=reg["id"], partition=phase), agent_key=key
                    )
                    if outcome.get("kind") == "BACKGROUND_RUN":
                        while outcome["status"] == "RUNNING":
                            time.sleep(0.25)
                            outcome = self.research.run_status(outcome["id"])
                        if outcome["status"] != "COMPLETED":
                            raise ValueError("interrupted replay; no resend")
                        outcome = outcome["outcome"]
                    if outcome.get("kind") != "BACKTEST":
                        progress[-1].update(
                            status="FAILED", error_code=outcome.get("error_code", "REPLAY_FAILED")
                        )
                        self._progress(key, progress)
                        raise ValueError("failed or uncertain replay; no resend")
                    result = outcome["payload"]["result"]
                    decision = assessment(result, phase)
                    if outcome["payload"]["verdict"] == "REJECT_OR_REVISE":
                        decision = "REJECT_OR_REVISE"
                    elif outcome["payload"]["verdict"] == "INSUFFICIENT_EVIDENCE":
                        decision = "MORE_OBSERVATIONS_REQUIRED"
                    progress[-1].update(
                        status="COMPLETE",
                        result_id=outcome["id"],
                        closed_trades=result["metrics"]["closed_trades"],
                        minimum_closed_trades=TRADE_TARGETS[phase],
                        assessment=decision,
                    )
                    self._progress(key, progress)
                    if decision != "PASS_TO_NEXT_STAGE":
                        break
            status = (
                "DATA_REQUIRED"
                if not plan["full_validation_ready"]
                else "REJECT_OR_REVISE"
                if any(x.get("assessment") == "REJECT_OR_REVISE" for x in progress)
                else "MORE_OBSERVATIONS_REQUIRED"
                if any(x.get("assessment") == "MORE_OBSERVATIONS_REQUIRED" for x in progress)
                else "OFFLINE_GATES_COMPLETE_NOT_PAPER_AUTHORIZED"
                if all(
                    any(
                        x.get("symbol") == source["symbol"]
                        and x.get("phase") == "holdout"
                        and x.get("assessment") == "PASS_TO_NEXT_STAGE"
                        for x in progress
                    )
                    for source in plan["datasets"]
                )
                else "DATA_REQUIRED"
            )
            result = dict(
                status=status,
                execution_enabled=False,
                qualified_for_paper=False,
                validation_complete=status == "OFFLINE_GATES_COMPLETE_NOT_PAPER_AUTHORIZED",
                next_action=(
                    "Review acquired data coverage and exploratory results. "
                    "Dated costs, calendar/news coverage and independent holdout "
                    "qualification remain required."
                )
                if not plan["full_validation_ready"]
                else (
                    "Revise/review strategy if rejected; collect more observations if "
                    "insufficient. No trading permission."
                ),
                holdout_opened=any(x.get("phase") == "holdout" for x in progress),
            )
        except Exception as error:
            import urllib.error

            for step in progress:
                if step.get("status") == "RUNNING":
                    step["status"] = "FAILED"
            completed_symbols = {step["symbol"] for step in progress}
            for source in plan["datasets"]:
                if source["symbol"] not in completed_symbols:
                    progress.append(
                        dict(symbol=source["symbol"], status="NOT_STARTED_AFTER_FAILURE")
                    )
            self._progress(key, progress)

            result = dict(
                status="FAILED_NO_RESEND",
                error_type=type(error).__name__,
                error_code=next(
                    (p["error_code"] for p in reversed(progress) if "error_code" in p),
                    "PREPARATION_OR_REPLAY_FAILED",
                ),
                execution_enabled=False,
                qualified_for_paper=False,
                validation_complete=False,
                next_action=(
                    f"Historical provider returned HTTP {error.code}; "
                    "downloads were stopped. No automatic retry or substitution."
                )
                if isinstance(error, urllib.error.HTTPError)
                else (
                    "Preparation or replay failed; preserved files require review. "
                    "No automatic retry."
                ),
            )
        with self.repo.lock, self.repo.conn:
            self.repo.conn.execute(
                "UPDATE validation_agent_runs SET result=? WHERE id=? AND result IS NULL",
                (json.dumps(result), key),
            )
            self.active.discard(key)

    def _progress(self, key, progress):
        with self.repo.lock, self.repo.conn:
            self.repo.conn.execute(
                "UPDATE validation_agent_runs SET progress=? WHERE id=? AND result IS NULL",
                (json.dumps(progress), key),
            )
