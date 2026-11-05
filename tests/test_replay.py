from datetime import timedelta
from decimal import Decimal

import pytest

from fx_talanta.domain.offline import Fault
from fx_talanta.research.replay import Dataset, digest, execute, register, run
from tools.fixtures.b01_replay import AT, scenario


def test_lifecycle_is_deterministic_and_costed():
    data, experiment = scenario()
    result, journal = run(data, experiment, "training")
    assert run(data, experiment, "training") == (result, journal)
    assert [d["action"] for d in result["deals"]] == ["ENTER", "CLOSE"]
    assert result["open_positions"] == 0
    assert not result["execution_enabled"] and not result["m1_qualified"]
    assert Decimal(result["net_realized_pnl"]) < 0
    assert Decimal(result["commission"]) > 0
    assert Decimal(result["financing"][0]["charge"]) > 0
    volume = Decimal(result["deals"][0]["volume"])
    charge = Decimal(result["financing"][0]["charge"])
    # Unchanged market: round-trip spread + two slippages/commissions + financing.
    expected = -(Decimal("10") + Decimal("4") + Decimal("8")) * volume - charge
    assert abs(Decimal(result["net_realized_pnl"]) - expected) < Decimal("1e-24")


def test_rejection_is_not_retried():
    data, experiment = scenario()
    events = list(data.events)
    events[2] = events[2].model_copy(update={"fault": Fault(kind="REJECT")})
    result, _ = run(data.model_copy(update={"events": tuple(events)}), experiment, "training")
    assert not result["deals"]
    assert sum(d["action"] == "SUBMITTED_TO_SIMULATOR" for d in result["decisions"]) == 1


def test_missing_completeness_stays_hold():
    data, experiment = scenario()
    result, _ = run(data.model_copy(update={"history_complete": False}), experiment, "training")
    assert not result["deals"]


def test_quote_arrival_order_is_required():
    data, _ = scenario()
    with pytest.raises(ValueError, match="strictly ordered"):
        Dataset.model_validate({**data.model_dump(), "events": tuple(reversed(data.events))})


def test_journal_preserves_decision_and_valid_hash_chain():
    result, journal = run(*scenario(), "training")
    previous = "0" * 64
    records = []
    for item in journal:
        assert item["payload"]["previous"] == previous
        assert digest(item["payload"]) == item["hash"]
        previous = item["hash"]
        records.extend(item["payload"]["records"])
    assert previous == result["journal_tip"]
    assert any(r["body"]["kind"] == "decision" for r in records)


def test_stale_quotes_never_enter_and_original_expiry_is_preserved():
    data, experiment = scenario()
    events = list(data.events)
    for i in (2, 3):
        e = events[i]
        events[i] = e.model_copy(update={"available_at": e.available_at + timedelta(seconds=3)})
    result, _ = run(data.model_copy(update={"events": tuple(events)}), experiment, "training")
    assert not result["deals"]
    assert any(d["action"] == "EXPIRED" for d in result["decisions"])


def test_end_of_data_does_not_invent_a_close():
    data, experiment = scenario()
    result, _ = run(data.model_copy(update={"events": data.events[:4]}), experiment, "training")
    assert result["open_positions"] == 1
    assert not result["fully_settled"]
    assert [d["action"] for d in result["deals"]] == ["ENTER"]


def test_partial_fill_keeps_remainder_visible():
    data, experiment = scenario()
    events = list(data.events)
    events[2] = events[2].model_copy(update={"fault": Fault(kind="PARTIAL")})
    result, _ = run(data.model_copy(update={"events": tuple(events[:3])}), experiment, "training")
    assert result["open_positions"] == 1
    assert result["unsettled_entry_orders"] == 1
    assert not result["fully_settled"]


def test_gap_closes_at_observed_price_not_stop_level():
    data, experiment = scenario()
    events = list(data.events)
    e = events[3]
    q = e.market.quotes[0].model_copy(update={"bid": Decimal("1.0100"), "ask": Decimal("1.0101")})
    events[3] = e.model_copy(update={"market": e.market.model_copy(update={"quotes": (q,)})})
    result, _ = run(data.model_copy(update={"events": tuple(events)}), experiment, "training")
    assert Decimal(result["deals"][1]["price"]) == Decimal("1.00998")
    assert result["fully_settled"]


def test_manifest_and_outputs_are_not_silently_rewritten(tmp_path):
    data, experiment = scenario()
    dataset = tmp_path / "dataset.json"
    spec = tmp_path / "experiment.json"
    dataset.write_text(data.model_dump_json(), encoding="utf-8")
    spec.write_text(experiment.model_dump_json(), encoding="utf-8")
    directory = tmp_path / "registered"
    register(directory, dataset, spec)
    with pytest.raises(FileNotFoundError):
        execute(directory, dataset, "holdout")
    result = execute(directory, dataset, "training")
    assert result["fully_settled"]
    with pytest.raises(FileExistsError):
        execute(directory, dataset, "training")
    dataset.write_text(data.model_dump_json() + " ", encoding="utf-8")
    with pytest.raises(ValueError, match="changed"):
        execute(directory, dataset, "validation")


def test_missing_phase_records_failed_attempt_without_retry(tmp_path):
    data, experiment = scenario()
    dataset = tmp_path / "dataset.json"
    spec = tmp_path / "experiment.json"
    dataset.write_text(data.model_dump_json(), encoding="utf-8")
    spec.write_text(experiment.model_dump_json(), encoding="utf-8")
    directory = tmp_path / "registered"
    register(directory, dataset, spec)
    execute(directory, dataset, "training")
    with pytest.raises(ValueError, match="no market evidence"):
        execute(directory, dataset, "validation")
    assert (directory / "validation" / "failed.json").exists()
    with pytest.raises(FileExistsError):
        execute(directory, dataset, "validation")


def test_sell_costs_are_adverse_too():
    data, experiment = scenario()
    center = Decimal("2.1")
    bars = tuple(
        b.model_copy(
            update={
                "open": center - b.open,
                "close": center - b.close,
                "high": center - b.low,
                "low": center - b.high,
            }
        )
        for b in data.bars
    )
    events = []
    for e in data.events:
        q = e.market.quotes[0]
        changed = q.model_copy(update={"bid": center - q.ask, "ask": center - q.bid})
        market = e.market.model_copy(
            update={"quotes": (changed,), "conversion": {"USD": Decimal(1), "EUR": changed.bid}}
        )
        events.append(e.model_copy(update={"market": market}))
    result, _ = run(
        data.model_copy(update={"bars": bars, "events": tuple(events)}), experiment, "training"
    )
    assert [d["action"] for d in result["deals"]] == ["ENTER", "CLOSE"]
    assert Decimal(result["deals"][0]["price"]) == Decimal("1.07988")
    assert Decimal(result["deals"][1]["price"]) == Decimal("1.08002")
    assert Decimal(result["net_realized_pnl"]) < 0


def test_replay_rejects_broker_account_and_closed_store():
    from uuid import uuid4

    from fx_talanta.clock import FakeClock
    from fx_talanta.domain.models import AccountIdentity
    from fx_talanta.research.store import ReplayStore
    from fx_talanta.storage.repository import AccountMismatch

    account = AccountIdentity(
        environment="PAPER", venue="BROKER_DEMO", broker="fixture", server="test", login="test"
    )
    with pytest.raises(AccountMismatch):
        ReplayStore(account, uuid4(), FakeClock(AT))
    store = ReplayStore(account.model_copy(update={"venue": "SIMULATOR"}), uuid4(), FakeClock(AT))
    store.close()
    with pytest.raises(RuntimeError, match="closed"):
        store.next_id()


def test_committed_synthetic_result_reproduces():
    import json
    from pathlib import Path

    evidence = json.loads(
        (Path(__file__).resolve().parents[1] / "docs/evidence/m3-synthetic-replay.json").read_text(
            encoding="utf-8"
        )
    )
    result, journal = run(*scenario(), "training")
    assert digest(result) == evidence["receipt"]["result_hash"]
    assert digest(journal) == evidence["receipt"]["journal_hash"]
