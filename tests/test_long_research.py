import json
from datetime import datetime, timedelta
from decimal import Decimal, localcontext
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from fx_talanta.clock import FakeClock
from fx_talanta.domain.models import Record
from fx_talanta.domain.offline import BrokerBook, GatewayBook, Market
from fx_talanta.gateway.offline import Gateway
from fx_talanta.research.replay import Costs, CostSimulator
from fx_talanta.research.spool import SegmentedSpool, rows


def test_original_halt_is_a_real_risk_breach_and_still_closes():
    data = json.loads((Path(__file__).parent / "fixtures/research-halt.json").read_text())
    book = GatewayBook.model_validate(data["gateway"])
    clock = FakeClock(datetime.fromisoformat(data["at"]))
    gateway = Gateway.for_replay(book.account, uuid4(), clock, book.policy)
    gateway.book = book
    gateway.store.records = {
        UUID(r["record_id"]): Record.model_validate(r) for r in data["records"]
    }
    gateway.store.books["broker"] = BrokerBook.model_validate(data["broker"])
    gateway.broker = CostSimulator(
        gateway.store,
        book.policy.capital,
        Costs(
            commission_per_lot_per_side="4",
            slippage_per_lot_per_side="2",
            financing_per_lot_day="3",
            basis="Original research assumptions",
        ),
    )
    market = Market.model_validate(data["market"])
    with localcontext() as context:
        context.prec = 34
        gateway.reconcile(market)
        assert gateway.book.integrity_halt
        assert gateway.book.state == "HARD_HALT"
        breach = gateway.integrity_breach
        assert breach["reason"] == "RISK_LIMIT_BREACH"
        risk = breach["limits"]["aggregate_risk"]
        assert Decimal(risk["actual"]) == Decimal("10.08")
        assert Decimal("9.9969") < Decimal(risk["limit"]) < Decimal("9.9970")
        assert not any(p.volume for p in gateway.broker.book.positions)
        assert gateway.book.policy == book.policy
        clock.advance(timedelta(seconds=1))
        newer = market.model_copy(
            update={
                "at": clock.now(),
                "quotes": tuple(q.model_copy(update={"at": clock.now()}) for q in market.quotes),
            }
        )
        gateway.reconcile(newer)
        assert gateway.book.state == "HARD_HALT"
        assert gateway.integrity_breach == breach
    gateway.close()


def test_segmented_audit_reconstructs_every_record_and_detects_tampering(tmp_path, monkeypatch):
    from fx_talanta.research import spool

    monkeypatch.setattr(spool, "MAX_LINE", 1024)
    monkeypatch.setattr(spool, "MAX_RAW", 1024)
    path = tmp_path / "journal.json"
    stream = SegmentedSpool(path, segment_bytes=1024)
    values = [{"sequence": i, "payload": "x" * 240} for i in range(30)]
    for value in values:
        stream.append(value)
    assert stream[-1] == values[-1]
    stream.close()
    assert stream.bytes > spool.MAX_RAW  # Total spans the old single-file limit.
    manifest = json.loads(path.read_text())
    assert len(manifest["parts"]) > 1
    assert list(rows(path)) == values
    assert stream.receipt()["rows"] == len(values)
    with pytest.raises(FileExistsError):
        SegmentedSpool(path, segment_bytes=1024)
    part = path.with_suffix(".parts") / manifest["parts"][1]["file"]
    with part.open("ab") as out:
        out.write(b"changed")
    with pytest.raises(ValueError, match="hash mismatch"):
        list(rows(path))


def test_segmented_audit_interruption_and_disk_reserve(tmp_path, monkeypatch):
    from fx_talanta.research import spool

    monkeypatch.setattr(spool, "MAX_LINE", 1024)
    path = tmp_path / "interrupted.json"
    stream = SegmentedSpool(path, segment_bytes=1024)
    stream.append({"retained": True})
    stream.current.close()  # Abrupt interruption has no success manifest.
    assert not path.exists()
    with pytest.raises(FileExistsError):
        SegmentedSpool(path)
    from types import SimpleNamespace

    monkeypatch.setattr(spool.shutil, "disk_usage", lambda _: SimpleNamespace(free=0))
    with pytest.raises(ValueError, match="disk reserve"):
        SegmentedSpool(tmp_path / "full.json")


def test_compact_audit_reconstructs_exact_legacy_states_and_financials():
    from fx_talanta.research.replay import execute_timeline
    from fx_talanta.research.session_study import timeline
    from fx_talanta.research.store import reconstruct_books
    from tools.fixtures.b01_replay import scenario

    data, experiment = scenario()
    start, end = experiment.window("training")
    run_id = uuid4()

    def run(compact):
        return execute_timeline(
            data,
            experiment,
            "training",
            timeline(data.bars, data.events, start, end),
            run_id,
            compact_journal=compact,
        )

    normal, original = run(False)
    compact, encoded = run(True)
    normal.pop("journal_tip")
    compact.pop("journal_tip")
    assert normal == compact
    expanded = list(reconstruct_books(encoded))
    assert len(expanded) == len(original)
    for before, after in zip(original, expanded, strict=True):
        a, b = dict(before["payload"]), dict(after["payload"])
        a.pop("previous")
        b.pop("previous")
        b.pop("encoding", None)
        assert a == b
    assert any("book_delta" in r["payload"] for r in encoded)


def test_compact_cache_detects_nested_mapping_mutation():
    from fx_talanta.research.store import ReplayStore, reconstruct_books

    data = json.loads((Path(__file__).parent / "fixtures/research-halt.json").read_text())
    book = GatewayBook.model_validate(data["gateway"])
    store = ReplayStore(book.account, uuid4(), FakeClock(datetime.fromisoformat(data["at"])))
    store.compact = True
    store.save("gateway", book, "BEFORE")
    currency = book.entries[-1].reservation.currency_per_lot
    currency["USD"] += Decimal(1)
    store.save("gateway", book, "AFTER")
    expanded = list(reconstruct_books(store.journal))
    assert expanded[-1]["payload"]["book"] == book.model_dump(mode="json")
    assert "entries" in store.journal[-1]["payload"]["book_delta"]
