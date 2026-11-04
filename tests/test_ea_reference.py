import importlib.util
import json
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from uuid import UUID

from fx_talanta.domain.models import Environment
from fx_talanta.domain.offline import BrokerBook, EntryIntent, Policy
from fx_talanta.execution_contracts.reference import RiskVector, calculate
from fx_talanta.research.offline import market_at
from fx_talanta.research.records import START
from fx_talanta.risk.governor import losses, size
from fx_talanta.storage.config import fixture_account

ROOT = Path(__file__).resolve().parents[1]


def test_human_reference_vectors_and_deterministic_native_export(tmp_path):
    spec = importlib.util.spec_from_file_location(
        "m2a_reference", ROOT / "tools/fixtures/m2a_reference.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    result = module.run(tmp_path)
    assert result["all_pass"], [r for r in result["results"] if not r["pass"]]
    assert len(result["results"]) == 27
    assert result["native_compiler"] == "NOT_RUN"
    assert result["native_parity"] == "NOT_QUALIFIED"
    assert "expected" not in (tmp_path / "risk.tsv").read_text()
    original = (tmp_path / "report.json").read_bytes()
    module.run(tmp_path)
    assert (tmp_path / "report.json").read_bytes() == original


def test_existing_usd_governor_is_the_behavioral_oracle():
    data = json.loads((ROOT / "tests/fixtures/ea_protocol/risk.json").read_text(encoding="utf-8"))
    account = fixture_account(Environment.PAPER)
    market = market_at(START)
    book = BrokerBook(account=account, initial_balance="10000", balance="10000")
    policy = Policy()
    ledger = losses(None, book, market, policy, START)
    for case in data["cases"][:4]:
        v = RiskVector.model_validate(data["defaults"] | case["input"])
        if v.currency != "USD":
            continue
        intent = EntryIntent(
            intent_id=UUID(int=1),
            account=account,
            decision_id=UUID(int=2),
            symbol=v.symbol,
            side="BUY",
            stop=v.stop,
            target="1.1046" if v.symbol == "EURUSD" else "150.46",
            benchmark=v.ask,
            expires_at=START + timedelta(seconds=60),
            exit_at=START + timedelta(hours=1),
        )
        reservation, reason = size(intent, book, (), market, policy, ledger, START)
        reference = calculate(v)
        assert reason == "approved"
        assert reservation.volume == Decimal(reference["volume"])
        assert (reservation.volume * reservation.risk_per_lot).quantize(
            Decimal(".000001")
        ) == Decimal(reference["risk"])
        assert reservation.gross_per_lot * reservation.volume == Decimal(reference["gross"])
        assert reservation.margin_per_lot * reservation.volume == Decimal(reference["margin"])
