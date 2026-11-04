import hashlib
import json
from pathlib import Path

import pytest

from fx_talanta.integration.checkpoint import verify_native
from fx_talanta.shadow.work import scope_for
from scripts.disabled_integration_fixtures import compare
from scripts.shadow_fixtures import ACCOUNT, CLIENT, KEY, POLICY, RELEASE

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/integration"


def test_independent_native_results_and_source_pins():
    report = json.loads((ROOT / "docs/evidence/m2-disabled-integration.json").read_text())
    assert compare(FIXTURE)["native_cases"] == 60
    assert report["native"]["native_fault_checks"] == 12
    assert report["regression"]["passed"] >= 797 and report["regression"]["skipped"] == 0
    assert not report["full_m2_complete"] and not report["native_live_transport_run"]
    for name, expected in (report["artifacts"] | report["native"]["source_sha256"]).items():
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == expected


def test_native_checkpoint_independent_rebuild_and_rollback_detection():
    data = (FIXTURE / "recovery.journal.txt").read_bytes()
    pins = dict(scope=scope_for(ACCOUNT), client=CLIENT, release=RELEASE, policy=POLICY, key=KEY)
    peer = verify_native(data, **pins)
    assert peer.sequence == 1 and peer.acknowledged
    assert verify_native(data, expected_tip=peer.journal_hash, **pins) == peer
    prefix = b"\n".join(data.splitlines()[:-1]) + b"\n"
    with pytest.raises(ValueError, match="NATIVE_CHECKPOINT_CONFLICT"):
        verify_native(prefix, expected_tip=peer.journal_hash, **pins)
    assert not verify_native(prefix, **pins).acknowledged


def test_native_checkpoint_rejects_wrong_binding_or_torn_file():
    data = (FIXTURE / "recovery.journal.txt").read_bytes()
    pins = dict(scope=scope_for(ACCOUNT), client=CLIENT, release=RELEASE, policy=POLICY, key=KEY)
    with pytest.raises(ValueError, match="NATIVE_BINDING_CONFLICT"):
        verify_native(data, **(pins | dict(client="f" * 64)))
    with pytest.raises(ValueError, match="NATIVE_JOURNAL_INCOMPLETE"):
        verify_native(data[:-1], **pins)


def test_actual_native_receipt_matches_committed_backend_checkpoint(tmp_path):
    from fx_talanta.integration.checkpoint import paired_checkpoint
    from scripts.shadow_fixtures import NOW, work
    from tests.test_disabled_integration import call, make

    data = (FIXTURE / "recovery.journal.txt").read_bytes()
    records = [line.split("|")[2].split("\t") for line in data.decode().splitlines()]
    receipt = bytes.fromhex(records[1][2]).decode()
    coordinator = make(tmp_path)
    coordinator.publish(*work(), NOW)
    call(coordinator, "REPORT", receipt, "b" * 64)
    pair = paired_checkpoint(
        coordinator.store,
        data,
        scope=scope_for(ACCOUNT),
        client=CLIENT,
        release=RELEASE,
        policy=POLICY,
        key=KEY,
    )
    assert pair.backend.sequence == pair.native.sequence == 1
    assert pair.backend.receipt_hash == pair.native.receipt_hash
