"""Attach a new session interpretation without rewriting an existing backtest."""

from pathlib import Path

from fx_talanta.domain.models import FrozenModel, Hash
from fx_talanta.research import market_sessions, session_results
from fx_talanta.research.replay import digest


class Request(FrozenModel):
    result_id: Hash


def analyze(research, data):
    request = Request.model_validate(data)
    item = research.item(request.result_id)
    if item["kind"] != "BACKTEST" or item["payload"]["partition"] != "training":
        raise ValueError("session diagnosis accepts training results only")
    result = item["payload"]["result"]
    report = session_results.summarize(result)
    return research.retain(
        "SESSION_ANALYSIS",
        dict(
            baseline_id=request.result_id,
            candidate_sha256=item["payload"]["candidate_sha256"],
            sessions=report,
            analyzer_sha256=digest(
                {
                    name: Path(module.__file__).read_text(encoding="utf-8-sig")
                    for name, module in [("sessions", market_sessions), ("report", session_results)]
                }
            ),
            source_result_sha256=digest(result),
            scope=(
                "Retrospective attribution of retained trades; "
                "no strategy rerun or changed verdict."
            ),
            execution_enabled=False,
        ),
    )
