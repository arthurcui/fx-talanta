"""Pin actual native outputs to source; do not turn offline checks into HTTPS proof."""

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_actual_connected_native_evidence_matches_sources_and_preserved_failures():
    report = json.loads((ROOT / "docs/evidence/m2d-connected-20261104.json").read_text())
    assert report["execution_enabled"] is report["connected_paper_accepted"] is False
    assert report["native_https"].startswith("PENDING_")
    native = report["native"]
    assert native["broker_connected"] is False
    for path, expected in native["sources"].items():
        assert hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == expected
    for result in native["compiler"].values():
        assert result["errors"] == result["warnings"] == 0
    assert sum(run["passed"] for run in native["runs"].values()) == 68
    assert sum(run["failed"] for run in native["runs"].values()) == 0
    for path, expected in report["prior_evidence_sha256"].items():
        assert hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == expected
    attempts = report["capture_attempts"]
    assert attempts["cmc-capture-01"]["reason"] == "ALGORITHMIC_TRADING_MUST_BE_DISABLED"
    assert attempts["forex-capture-01"]["status"] == "BLOCKED"
    assert attempts["forex-capture-02"]["status"] == "CAPTURED_DATA_HOLD"
    assert all(row["original_binding_unchanged"] for row in attempts.values())
    assert all(row["entry_eligibility"] is False for row in attempts.values())
    actual = ROOT / "tests/fixtures/connected-native-inbox.json"
    assert (
        hashlib.sha256(actual.read_bytes()).hexdigest()
        == report["actual_native_journal_fixture_sha256"]
    )


def test_connected_native_host_has_no_broker_mutation_or_trust_bypass():
    path = ROOT / "mql5/connected/ConnectedEA.mq5"
    text = path.read_text()
    for forbidden in ("OrderSend(", "OrderCheck(", "CTrade", "SymbolSelect(", "TesterStart("):
        assert forbidden not in text
    assert "input bool EnableConnected=false;" in text
    assert "TERMINAL_TRADE_ALLOWED)==0" in text
    assert 'WebRequest("POST",co_endpoint' in text
    assert "https://127.0.0.1:" in text
    assert "http://" not in text
