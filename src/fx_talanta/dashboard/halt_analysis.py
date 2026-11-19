"""Read retained research evidence and replay only the risk-halt boundary."""

from datetime import datetime, timedelta
from decimal import Decimal, localcontext
from uuid import UUID

from fx_talanta.dashboard.indexed_research import index_path
from fx_talanta.dashboard.research import Registration, indexed_engine_hash
from fx_talanta.domain.models import FrozenModel, Hash
from fx_talanta.research.halt_diagnosis import reproduce
from fx_talanta.research.replay import Costs, digest, priced
from fx_talanta.research.spool import file_hash, rows
from fx_talanta.research.tick_index import TickIndex


class Request(FrozenModel):
    result_id: Hash


def investigate(research, data):
    request = Request.model_validate(data)
    item = research.item(request.result_id)
    if item["kind"] != "BACKTEST" or item["payload"]["partition"] != "training":
        raise ValueError("retained training backtest required")
    payload = item["payload"]
    result = payload["result"]
    halt = result.get("risk_halt")
    if not halt or "aggregate_risk" not in halt["limits"]:
        raise ValueError("measured aggregate-risk halt required")
    with research.repo.lock:
        existing = research.repo.conn.execute(
            "SELECT id,payload FROM research_items WHERE kind='RISK_DIAGNOSIS'"
        ).fetchall()
    import json

    for key, raw in existing:
        if json.loads(raw)["baseline_id"] == request.result_id:
            return research.item(key)
    plan = Registration.model_validate(research.item(payload["registration_id"])["payload"])
    if not plan.indexed or not isinstance(plan.experiment.costs, Costs):
        raise ValueError("indexed research with explicit scenario costs required")
    if plan.engine_sha256 != indexed_engine_hash():
        raise ValueError("recorded replay engine changed; cannot claim exact reproduction")
    bundle = research.catalog.read(plan.dataset_catalog_sha256)
    source = index_path(research.catalog.entries[plan.dataset_catalog_sha256].parent, bundle)
    key = digest(dict(registration_id=payload["registration_id"], partition="training"))
    directory = research.app.state / "research-runs" / key
    receipt = result["audit_streams"]["journal"]
    path = directory / receipt["file"]
    if path.name != "journal.manifest.json" or file_hash(path) != receipt["sha256"]:
        raise ValueError("pinned segmented journal required")
    manifest = json.loads(path.read_text())
    for number, part in enumerate(manifest["parts"]):
        if (
            part["file"] != f"{number:04d}.gz"
            or file_hash(path.with_suffix(".parts") / part["file"]) != part["sha256"]
        ):
            raise ValueError("journal segment changed")
    states = {}
    times = {}
    records = {}
    previous = "0" * 64
    checkpoint = None
    for count, record in enumerate(rows(path), 1):
        p = record["payload"]
        if p["previous"] != previous or digest(p) != record["hash"]:
            raise ValueError("journal chain mismatch")
        previous = record["hash"]
        stream = p["stream"]
        book = p.get("book")
        if "book_delta" in p:
            if p.get("encoding") != "book-delta/1" or stream not in states:
                raise ValueError("missing checkpoint")
            book = dict(states[stream])
            for field in p["book_removed"]:
                book.pop(field)
            book.update(p["book_delta"])
        if stream == "gateway" and book and book["integrity_halt"]:
            if datetime.fromisoformat(p["at"]) != datetime.fromisoformat(halt["at"]):
                raise ValueError("halt boundary mismatch")
            checkpoint = dict(
                gateway=states["gateway"],
                broker=states["broker"],
                previous_at=times["gateway"],
                at=p["at"],
                records=list(records.values()),
            )
            break
        if book is not None:
            states[stream] = book
            times[stream] = p["at"]
        for r in p.get("records", []):
            records[r["record_id"]] = r
        if count >= 2_000_000:
            raise ValueError("targeted diagnosis prefix bound exceeded")
    if checkpoint is None:
        raise ValueError("halt checkpoint absent")
    index = TickIndex(source)
    try:

        def market(at):
            at = datetime.fromisoformat(at)
            events = list(
                index.events(
                    at,
                    at + timedelta(milliseconds=1),
                    bundle.latency_ms,
                    bundle.assume_research_inputs,
                )
            )
            if len(events) != 1 or events[0].available_at != at:
                raise ValueError("ambiguous historical quote; cannot infer checkpoint")
            return priced(events[0].market, plan.experiment.costs, at)

        checkpoint["previous_market"] = market(checkpoint["previous_at"]).model_dump(mode="json")
        checkpoint["market"] = market(checkpoint["at"]).model_dump(mode="json")
        replay = reproduce(checkpoint, plan.experiment.costs)
        if replay["breach"]["limits"] != halt["limits"]:
            raise ValueError("replay breach differs from recorded result")
        final_deals = result["deals"]
        trades = []
        with localcontext() as context:
            context.prec = 34
            for number, entry in enumerate(checkpoint["gateway"]["entries"], 1):
                position = next(
                    p
                    for p in checkpoint["broker"]["positions"]
                    if p["entry_id"] == entry["intent"]["intent_id"]
                )
                deals = [
                    d
                    for d in final_deals
                    if UUID(d["position_id"]) == UUID(position["position_id"])
                ]
                opened = next(d for d in deals if d["action"] == "ENTER")
                closed = next(d for d in deals if d["action"] == "CLOSE")
                q = market(closed["at"]).quote_for(position["symbol"])
                stop = Decimal(entry["intent"]["stop"])
                stop_hit = q.bid <= stop if position["side"] == "BUY" else q.ask >= stop
                reason = (
                    "AGGREGATE_RISK_HALT"
                    if datetime.fromisoformat(closed["at"]) == datetime.fromisoformat(halt["at"])
                    else "STOP_REACHED"
                    if stop_hit
                    else "OTHER_EXIT_NOT_CLASSIFIED"
                )
                trades.append(
                    dict(
                        trade=number,
                        symbol=position["symbol"],
                        side=position["side"],
                        opened_at=opened["at"],
                        closed_at=closed["at"],
                        volume=opened["volume"],
                        admitted_risk=str(
                            Decimal(entry["reservation"]["risk_per_lot"])
                            * Decimal(opened["volume"])
                        ),
                        net_pnl=str(sum((Decimal(d["realized"]) for d in deals), Decimal(0))),
                        exit_reason=reason,
                    )
                )
        # The short replay must reproduce the actual close, not only the halt flag.
        expected = next(
            d
            for d in final_deals
            if d["action"] == "CLOSE"
            and datetime.fromisoformat(d["at"]) == datetime.fromisoformat(halt["at"])
        )
        if len(replay["new_deals"]) != 1:
            raise ValueError("unexpected protective replay deals")
        actual = replay.pop("new_deals")[0]
        for field in ("action", "price", "volume", "realized", "commission"):
            if actual[field] != expected[field]:
                raise ValueError("protective close mismatch")
    finally:
        index.close()
    return research.retain(
        "RISK_DIAGNOSIS",
        dict(
            baseline_id=request.result_id,
            candidate_sha256=plan.candidate_sha256,
            trades=trades,
            replay=replay,
            checkpoint_sha256=digest(checkpoint),
            journal_sha256=receipt["sha256"],
            index_sha256=bundle.index_sha256,
            verified_prefix_rows=count,
            checkpoint_chain_tip=previous,
            conclusion="CURRENT_TO_STOP_GIVEBACK_EXCEEDED_AGGREGATE_LIMIT",
            policy_matches_documented_definition=True,
            calculation_defect_reproduced=False,
            explanation=(
                "Ongoing risk includes unrealized profit that can be given back to a fixed stop. "
                "This differs from initial entry-to-stop capital risk and matches the documented "
                "policy. The current-equity aggregate limit was crossed; the protective close "
                "was reproduced from retained evidence."
            ),
            next_action=(
                "Review protective management within the unchanged limits "
                "before another parameter sweep."
            ),
            scope=(
                "Two historical observations replayed; repeated-quote latch check; "
                "no new entry or full-study run."
            ),
            execution_enabled=False,
            qualified_for_paper=False,
        ),
    )
