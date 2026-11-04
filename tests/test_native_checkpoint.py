import base64
import hashlib
import json
from pathlib import Path

import pytest

from fx_talanta.connected_shadow import native_checkpoint as native
from fx_talanta.connected_shadow.authority import PairCheckpoint, PeerCheckpoint
from fx_talanta.shadow.wire import digest

PINS = dict(
    scope="a" * 64,
    client="c" * 64,
    incarnation="d" * 64,
    epoch=1,
    binding_hash="b" * 64,
    key=b"s" * 32,  # Synthetic key in NativeConnectedTests, never a broker credential.
)


@pytest.fixture
def captured():
    path = Path(__file__).parent / "fixtures" / "connected-native-inbox.json"
    report = json.loads(path.read_text())
    data = tuple(
        base64.b64decode(report[name + "_base64"], validate=True)
        for name in ("journal", "checkpoint")
    )
    for name, value in zip(("journal", "checkpoint"), data, strict=True):
        assert hashlib.sha256(value).hexdigest() == report[name + "_sha256"]
    assert report["synthetic"]
    return data


def records(journal):
    return [line.split("|")[2] for line in journal.decode("ascii").splitlines()]


def repack(items):
    """Generate deliberate derivatives; these are not claimed as new native runs."""
    previous, lines, receipts, acknowledged = "GENESIS", [], [], 0
    for number, item in enumerate(items, 1):
        body = f"{number}|{previous}|{item}"
        previous = digest(body)
        lines.append(f"{body}|{previous}\r\n")
        fields = item.split("\t")
        if fields[0] == "RECEIPT":
            receipts.append(bytes.fromhex(fields[2]).decode("ascii"))
        elif fields[0] == "ACK":
            acknowledged += 1
    journal = "".join(lines).encode("ascii")
    checkpoint = "\t".join(
        (
            "connected-checkpoint/1",
            PINS["scope"],
            PINS["incarnation"],
            "1",
            hashlib.sha256(journal).hexdigest(),
            str(len(receipts)),
            digest(receipts[-1]) if receipts else "0" * 64,
            "1" if acknowledged == len(receipts) else "0",
        )
    )
    return journal, (checkpoint + "\r\n").encode("ascii")


def update_file_hash(journal, checkpoint):
    cp = checkpoint.decode("ascii").split("\t")
    cp[4] = hashlib.sha256(journal).hexdigest()
    return journal, "\t".join(cp).encode("ascii")


def test_actual_native_tester_journal_and_checkpoint_match_independent_parser(captured, tmp_path):
    verified = native.verify_native_journal(*captured, **PINS)
    assert verified.peer.sequence == 1 and verified.peer.acknowledged
    assert verified.receipts[0].split("\t")[9] == "REQUIRED_INPUTS"
    assert verified.key_fingerprint_verified
    assert not verified.transport_authenticated  # No HMAC frames are stored in this format.
    journal, checkpoint = tmp_path / "native.journal", tmp_path / "native.checkpoint"
    journal.write_bytes(captured[0])
    checkpoint.write_bytes(captured[1])
    assert native.read_native_checkpoint(journal, checkpoint, **PINS) == verified.peer
    backend = PeerCheckpoint(PINS["scope"], "f" * 64, 1, verified.peer.receipt_hash)
    assert PairCheckpoint.match(backend, verified.peer).native == verified.peer


@pytest.mark.parametrize(
    "field,value",
    [
        ("scope", "e" * 64),
        ("client", "e" * 64),
        ("incarnation", "e" * 64),
        ("epoch", 2),
        ("binding_hash", "e" * 64),
        ("key", b"x" * 32),
    ],
)
def test_pins_are_checked_independently_of_file_contents(captured, field, value):
    pins = PINS | {field: value}
    with pytest.raises(ValueError, match="BINDING"):
        native.verify_native_journal(*captured, **pins)


def test_exact_file_hash_does_not_normalize_line_endings(captured):
    changed = captured[0].replace(b"\r\n", b"\n")
    with pytest.raises(ValueError, match="NONCANONICAL"):
        native.verify_native_journal(changed, captured[1], **PINS)
    with pytest.raises(ValueError, match="NONCANONICAL"):
        native.verify_native_journal(*update_file_hash(changed, captured[1]), **PINS)


def test_updated_checkpoint_cannot_hide_broken_hash_chain(captured):
    changed = captured[0].replace(b"RECEIPT", b"RECEIPX", 1)
    with pytest.raises(ValueError, match="BINDING_OR_HASH"):
        native.verify_native_journal(changed, captured[1], **PINS)
    with pytest.raises(ValueError, match="JOURNAL_INTEGRITY"):
        native.verify_native_journal(*update_file_hash(changed, captured[1]), **PINS)


def test_truncated_or_extra_data_rejects(captured):
    for changed in (captured[0][:-1], captured[0] + b"partial", captured[0] + b"\r\n"):
        with pytest.raises(ValueError):
            native.verify_native_journal(*update_file_hash(changed, captured[1]), **PINS)
    with pytest.raises(ValueError):
        native.verify_native_journal(captured[0], captured[1][:-1], **PINS)


def test_hash_consistent_forged_accepted_receipt_rejects(captured):
    items = records(captured[0])
    fields = items[1].split("\t")
    receipt = bytes.fromhex(fields[2]).decode("ascii").replace("REQUIRED_INPUTS", "ACCEPTED")
    fields[2] = receipt.encode("ascii").hex()
    items[1] = "\t".join(fields)
    with pytest.raises(ValueError, match="RECEIPT_SEMANTICS"):
        native.verify_native_journal(*repack(items), **PINS)


def test_future_measurement_receipt_refused_even_with_consistent_hashes(captured):
    items = records(captured[0])[:2]
    fields = items[1].split("\t")
    observation = bytes.fromhex(fields[1]).decode("ascii").split("\t")
    receipt = bytes.fromhex(fields[2]).decode("ascii").split("\t")
    now, error = int(observation[5]) - 1, int(receipt[5])
    receipt[4] = str(now)
    receipt[6] = str(now - int(observation[10]) + max(error, int(observation[7])))
    receipt[8] = str(now - int(receipt[7]) + error)
    receipt[9] = "QUOTE_STALE"
    fields[2] = "\t".join(receipt).encode("ascii").hex()
    items[1] = "\t".join(fields)
    with pytest.raises(ValueError, match="RECEIPT_CLOCK"):
        native.verify_native_journal(*repack(items), **PINS)


def test_pending_checkpoint_from_actual_receipt_prefix_preserves_original_receipt(captured):
    derived = repack(records(captured[0])[:2])
    pending = native.verify_native_journal(*derived, **PINS)
    acknowledged = native.verify_native_journal(*captured, **PINS)
    assert not pending.peer.acknowledged and pending.peer.sequence == 1
    assert pending.receipts == acknowledged.receipts
    assert pending.peer.receipt_hash == acknowledged.peer.receipt_hash
    assert pending.peer.journal_hash != acknowledged.peer.journal_hash


def test_bad_or_duplicate_ack_and_wrong_checkpoint_state_reject(captured):
    items = records(captured[0])
    with pytest.raises(ValueError, match="ACK_MISMATCH"):
        native.verify_native_journal(*repack(items + [items[-1]]), **PINS)
    bad = [items[0], "ACK\t" + "f" * 64]
    with pytest.raises(ValueError, match="ACK_MISMATCH"):
        native.verify_native_journal(*repack(bad), **PINS)
    cp = captured[1].decode("ascii").split("\t")
    cp[-1] = "0\r\n"
    with pytest.raises(ValueError, match="CHECKPOINT_STATE"):
        native.verify_native_journal(captured[0], "\t".join(cp).encode("ascii"), **PINS)


def test_receipt_sequence_cannot_skip(captured):
    items = records(captured[0])[:2]
    fields = items[1].split("\t")
    for index in (1, 2):
        decoded = bytes.fromhex(fields[index]).decode("ascii").split("\t")
        decoded[2] = "2"
        fields[index] = "\t".join(decoded).encode("ascii").hex()
    items[1] = "\t".join(fields)
    with pytest.raises(ValueError, match="RECEIPT_SEQUENCE"):
        native.verify_native_journal(*repack(items), **PINS)


def test_coherent_rollback_requires_an_independently_retained_anchor(captured):
    original = native.verify_native_journal(*captured, **PINS)
    rollback = repack(records(captured[0])[:1])
    # Both older files are internally valid; do not pretend their own hashes detect rollback.
    assert native.verify_native_journal(*rollback, **PINS).peer.sequence == 0
    with pytest.raises(ValueError, match="RETAINED_CHECKPOINT_MISMATCH"):
        native.verify_native_journal(
            *rollback, **PINS, expected_journal_hash=original.peer.journal_hash
        )
    with pytest.raises(ValueError, match="CHECKPOINT_ROLLBACK"):
        native.verify_native_journal(*rollback, **PINS, minimum_sequence=1)


def test_concurrent_checkpoint_publication_rejects(captured, monkeypatch):
    responses = iter((captured[1], captured[0], captured[1] + b"changed"))
    monkeypatch.setattr(native, "_bounded_read", lambda *_: next(responses))
    with pytest.raises(ValueError, match="CHANGED_DURING_READ"):
        native.read_native_checkpoint("journal", "checkpoint", **PINS)


@pytest.mark.parametrize(
    "extra",
    [{"epoch": True}, {"key": b"short"}, {"expected_journal_hash": []}, {"minimum_sequence": True}],
)
def test_invalid_caller_pins_reject(captured, extra):
    with pytest.raises(ValueError, match="EXPECTED_BINDING"):
        native.verify_native_journal(*captured, **(PINS | extra))
