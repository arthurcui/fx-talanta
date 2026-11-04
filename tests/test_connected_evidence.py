"""Pin actual native outputs to source; do not turn offline checks into HTTPS proof."""

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_actual_connected_native_evidence_matches_sources_and_preserved_failures(historical_source):
    report = json.loads((ROOT / "docs/evidence/m2d-connected-20261104.json").read_text())
    assert report["execution_enabled"] is report["connected_paper_accepted"] is False
    assert report["native_https"] == "AUTHENTICATED_CLOCK_EXCHANGES_ONLY_HANDOFF_INCOMPLETE"
    native = report["native"]
    assert native["broker_connected"] is False
    for path, expected in native["sources"].items():
        assert hashlib.sha256(historical_source(path, expected)).hexdigest() == expected
    for result in native["compiler"].values():
        assert result["errors"] == result["warnings"] == 0
    assert sum(run["passed"] for run in native["runs"].values()) == 117
    assert sum(run["failed"] for run in native["runs"].values()) == 0
    for path, expected in report["prior_evidence_sha256"].items():
        assert hashlib.sha256(historical_source(path, expected)).hexdigest() == expected
    for path, expected in report["implementation_sha256"].items():
        assert hashlib.sha256(historical_source(path, expected)).hexdigest() == expected
    actual_https = json.loads((ROOT / report["native_https_evidence"]).read_text())
    assert actual_https["overall"]["native_https_authenticated_sync_observed"] is True
    assert actual_https["overall"]["accepted_native_clock_observed"] is False
    assert actual_https["overall"]["native_receipt_acknowledgements"] == 0
    assert actual_https["overall"]["connected_execution_accepted"] is False
    assert [r["counts"]["committed_backend_records"] for r in actual_https["attempts"]] == [
        1,
        8,
        12,
    ]
    assert all(not r["handoff_accepted"] for r in actual_https["attempts"])
    latest = actual_https["attempts"][-1]
    assert latest["counts"]["observations_consumed_by_native"] == 0
    assert latest["clock"]["actual_candidate_error_range_ms"] == [116, 134]
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


def test_remediation_preserves_failure_and_verifies_native_holds(historical_source):
    root = Path(__file__).resolve().parents[1]
    report = json.loads((root / "docs/evidence/m2d-remediation-20261104.json").read_text())
    failed, completed = report["attempts"]
    assert failed["terminal_status"] == "INCOMPLETE" and failed["receipt_count"] == 0
    assert completed["terminal_status"] == "COMPLETED"
    assert completed["receipt_count"] == completed["signed_acknowledgements"] == 2
    assert completed["native_acknowledged_receipt_count"] == 2
    assert completed["independent_status"] == "INDEPENDENT_INTEGRITY_VERIFIED"
    assert completed["database_read_only"] and completed["bounded_two_symbol_handoff_observed"]
    assert report["entry_ceiling_ms"] == 2000 and report["native_clock_ceiling_ms"] == 100
    assert report["no_order_handoff_verified"] is True
    for field in (
        "execution_enabled",
        "campaign_started",
        "market_data_qualified",
        "connected_execution_accepted",
    ):
        assert report[field] is False
    assert {r["symbol"] for r in completed["receipt_facts"]} == {"EURUSD", "USDJPY"}
    for receipt in completed["receipt_facts"]:
        assert receipt["reason"] == "QUOTE_STALE" and receipt["execution_enabled"] is False
        assert receipt["source_age_upper_ms"] > 2000
    assert completed["clock"]["accepted_error_max_ms"] <= 100
    assert completed["clock"]["hardware_accuracy_certified"] is False
    assert report["postcheck"]["algo_trading_disabled"] is True
    assert report["postcheck"]["positions_count"] == report["postcheck"]["orders_count"] == 0
    for name, expected in report["previous_evidence_sha256"].items():
        assert hashlib.sha256((root / name).read_bytes()).hexdigest() == expected
    for name, expected in report["implementation_sha256"].items():
        assert hashlib.sha256(historical_source(name, expected)).hexdigest() == expected
    assert report["regression"]["status"] == "PASSED"
