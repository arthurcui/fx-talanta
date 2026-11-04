import hashlib
import json
from datetime import timedelta
from pathlib import Path

import pytest

from fx_talanta.domain.ea_protocol import Envelope, ExecutionRequest
from fx_talanta.execution_contracts.channel_recorder import ChannelRecorder
from fx_talanta.execution_contracts.ea_file import decode_request, encode_request
from fx_talanta.execution_contracts.ea_journal import read_journal
from tools.fixtures.m2b_fixtures import NOW, SCOPE, fixture_requests

ROOT = Path(__file__).resolve().parents[1]


def test_committed_native_evidence_matches_its_original_sources(historical_source):
    report = json.loads((ROOT / "docs/evidence/m2b-native-20261103.json").read_text("utf-8"))
    for name, expected in report["source_sha256"].items():
        assert hashlib.sha256(historical_source(name, expected)).hexdigest() == expected
    native = report["native_checks"]
    assert native["count"] == len(native["checks"]) == 85
    assert all(value == "PASS" for value in native["checks"].values())
    assert native["failures"] == native["final_positions"] == native["final_orders"] == 0
    assert report["journal"]["all_closed"]
    assert report["connected_mode_refused"] and not report["connected_trading_enabled"]


@pytest.mark.parametrize("envelope", fixture_requests())
def test_native_frame_roundtrip_preserves_python_canonical_hash(envelope):
    assert decode_request(encode_request(envelope)) == envelope


@pytest.mark.parametrize(
    "changes",
    [
        {"max_volume": "0.000000001"},
        {"max_risk": "100000000"},
        {"broker_symbol": "not|a|symbol"},
        {"broker_symbol": "€"},
        {"sequence": 10**15},
    ],
)
def test_codec_rejects_values_outside_native_exact_domain(changes):
    p = fixture_requests()[0].payload.model_dump() | changes
    with pytest.raises(ValueError):
        encode_request(Envelope.seal(ExecutionRequest.model_validate(p)))


def test_codec_never_encodes_a_broker_account():
    p = fixture_requests()[0].payload.model_dump()
    p["account"]["venue"] = "BROKER_DEMO"
    with pytest.raises(ValueError, match="PAPER/SIMULATOR"):
        encode_request(Envelope.seal(ExecutionRequest.model_validate(p)))


@pytest.mark.parametrize(
    "mutation",
    [
        lambda frame: frame.replace("\t0.09\t", "\t0.1\t"),
        lambda frame: frame.replace("\t1\t2026", "\t01\t2026"),
        lambda frame: frame + "\tunexpected",
    ],
)
def test_decoder_rejects_corrupt_or_noncanonical_frames(mutation):
    with pytest.raises(ValueError):
        decode_request(mutation(encode_request(fixture_requests()[0])))


def journal_bytes(rows):
    previous = "GENESIS"
    result = []
    for number, row in enumerate(rows, 1):
        body = f"{number}|{previous}|{row}"
        previous = hashlib.sha256(body.encode("ascii")).hexdigest()
        result.append(f"{body}|{previous}\r\n")
    return "".join(result).encode("ascii")


def record(state="READY", version=1, filled=0, opened=0, remaining=9_000_000):
    fields = [state, "FIXTURE", version, filled, opened, remaining, 0, 0, 0]
    return "\t".join(map(str, fields)) + "\t" + encode_request(fixture_requests()[0])


def test_independent_reader_reconstructs_write_ahead_without_broker_access():
    data = journal_bytes([record(), record("SUBMITTING", 2), record("OUTCOME_UNKNOWN", 3)])
    records = read_journal(data)
    assert records[-1].state == "OUTCOME_UNKNOWN"
    assert records[-1].remaining_units == 9_000_000
    assert records[-1].filled_units == 0


def test_rounded_allocation_cannot_expand_during_partial_reconciliation():
    initial = record(remaining=8_000_000)
    expanded = record("OUTCOME_UNKNOWN", version=2, remaining=9_000_000)
    with pytest.raises(ValueError, match="reservation expanded"):
        read_journal(journal_bytes([initial, expanded]))


@pytest.mark.parametrize(
    "mutation",
    [lambda b: b[:-1], lambda b: b + b"partial", lambda b: b.replace(b"READY", b"CLOSED")],
)
def test_journal_torn_or_corrupt_tail_fails_closed(mutation):
    with pytest.raises(ValueError):
        read_journal(mutation(journal_bytes([record()])))


@pytest.mark.parametrize(
    "row",
    [record(version=2), record(filled=10_000_000), record(state="UNKNOWN_BUG"), record(opened=1)],
)
def test_hash_alone_does_not_make_invalid_evidence_valid(row):
    with pytest.raises(ValueError):
        read_journal(journal_bytes([row]))


@pytest.mark.parametrize("channel", ["EA", "PYTHON_PACKAGE", "MCP"])
def test_channel_heartbeat_does_not_refresh_a_stale_quote(channel):
    recorder = ChannelRecorder(SCOPE, "EURUSD", channel, "QUOTES", NOW)
    recorder.success(NOW, NOW)
    snapshot = recorder.heartbeat(NOW + timedelta(seconds=5))
    assert snapshot.state == "HEALTHY"
    assert not snapshot.quote_fresh(snapshot.measured_at)
    assert snapshot.original_tick_at == NOW
    assert snapshot.last_quote_receipt == NOW
    assert snapshot.samples == 0 and snapshot.delivery_p95_ms is None
    recorder.failure(NOW + timedelta(seconds=6), "READ_FAILED")
    assert recorder.snapshot(NOW + timedelta(seconds=7)).state == "ERROR"
    recovered = recorder.success(NOW + timedelta(seconds=8), NOW + timedelta(seconds=8))
    assert recovered.state == "HEALTHY" and recovered.quote_fresh(recovered.measured_at)


@pytest.mark.parametrize("capability", ["ACCOUNT_RECONCILIATION", "NEWS", "CALENDAR"])
def test_capability_is_not_inferred_from_mcp_connection(capability):
    recorder = ChannelRecorder(SCOPE, "EURUSD", "MCP", capability, NOW)
    assert not recorder.success(NOW).quote_fresh(NOW)
    with pytest.raises(ValueError, match="non-quote"):
        recorder.success(NOW, NOW)


def test_unconfigured_channel_and_regressed_clock_are_explicit():
    recorder = ChannelRecorder(SCOPE, "EURUSD", "MCP", "QUOTES", NOW, configured=False)
    assert recorder.snapshot(NOW).state == "NOT_CONFIGURED"
    with pytest.raises(ValueError, match="requires original"):
        recorder.success(NOW)
    with pytest.raises(ValueError, match="regressed"):
        recorder.heartbeat(NOW - timedelta(seconds=1))


def test_connected_order_boundary_is_not_configurable():
    folder = ROOT / "mql5/gateway"
    source = "\n".join(
        p.read_text(encoding="utf-8") for p in folder.iterdir() if p.suffix in {".mq5", ".mqh"}
    )
    assert source.count("OrderSend(") == 1
    assert "OrderSendAsync(" not in source
    assert "#import" not in source and "WebRequest(" not in source
    broker = (folder / "Broker.mqh").read_text(encoding="utf-8")
    boundary = broker.split("bool FxTesterSend", 1)[1].split("bool FxKnownComment", 1)[0]
    assert boundary.index("MQL_TESTER") < boundary.index("OrderSend(")
    assert boundary.index("SYMBOL_CUSTOM") < boundary.index("OrderSend(")
    gateway = (ROOT / "tests/native/gateway/FixedGateway.mq5").read_text(encoding="utf-8")
    assert "FX_M2B_CONNECTED_EXECUTION_DISABLED" in gateway
    assert "input " not in gateway
