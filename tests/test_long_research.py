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
