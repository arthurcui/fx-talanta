"""Independently validate stopped/consistently copied native inbox evidence.

CoInbox stores SHA-256 chains and a pinned key fingerprint, not HMAC frames.
Consequently this verifies file integrity, bindings and receipt calculations;
it cannot prove transport authentication from the journal alone. A separately
retained checkpoint is needed to detect a coherent rollback of both files.
"""

import hashlib
import hmac
import re
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from fx_talanta.connected_shadow.authority import PeerCheckpoint
from fx_talanta.shadow.wire import digest, hex64, integer

MAX_JOURNAL = 8_000_000


@dataclass(frozen=True)
class VerifiedNativeJournal:
    peer: PeerCheckpoint
    client: str
    incarnation: str
    epoch: int
    binding_hash: str
    journal_tip: str
    observations: tuple[str, ...]
    receipts: tuple[str, ...]
    key_fingerprint_verified: bool = True
    # Deliberately not inferred from a matching key fingerprint/hash chain.
    transport_authenticated: bool = False


def _ascii(data, limit):
    if type(data) is not bytes or not 0 < len(data) <= limit:
        raise ValueError("NATIVE_FILE_SIZE_OR_TYPE")
    try:
        return data.decode("ascii")
    except UnicodeDecodeError:
        raise ValueError("NATIVE_FILE_ENCODING") from None


def _signed(value):
    if value.startswith("-"):
        if value == "-0":
            raise ValueError("NATIVE_INTEGER")
        return -integer(value[1:])
    return integer(value)


def _unhex(value):
    if value == "-":
        return ""
    if len(value) % 2 or not re.fullmatch("[0-9a-f]*", value):
        raise ValueError("NATIVE_PAYLOAD_HEX")
    try:
        raw = bytes.fromhex(value)
        if any(c > 126 or (c < 32 and c not in (9, 10)) for c in raw):
            raise ValueError("NATIVE_PAYLOAD_ASCII")
        return raw.decode("ascii")
    except UnicodeDecodeError:
        raise ValueError("NATIVE_PAYLOAD_ASCII") from None


def _observation(work, scope, binding_hash):
    f = work.split("\t")
    if len(work) > 2048 or len(f) != 14 or f[0] != "connected-observation/1":
        raise ValueError("NATIVE_OBSERVATION_SCHEMA")
    if str(UUID(f[1])) != f[1] or f[3] != scope or f[12] != binding_hash or not hex64(f[4]):
        raise ValueError("NATIVE_OBSERVATION_BINDING")
    sequence, measured, expires, error, tick = (integer(f[i]) for i in (2, 5, 6, 7, 10))
    if (
        sequence < 1
        or measured < 1
        or not 0 < expires - measured <= 60000
        or error > 100
        or tick < 1
        or f[8] not in {"EURUSD", "USDJPY"}
        or not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", f[9])
        or ".." in f[9]
        or len(f[11]) > 1024
        or not re.fullmatch("[A-Z0-9_,]*", f[11])
        or abs(_signed(f[13])) > 50400000
    ):
        raise ValueError("NATIVE_OBSERVATION_VALUES")
    return f


def _receipt(receipt, work, scope, binding_hash):
    f = _observation(work, scope, binding_hash)
    r = receipt.split("\t")
    if len(r) != 12 or r[0] != "connected-hold/1" or r[11] != "0":
        raise ValueError("NATIVE_RECEIPT_SCHEMA")
    now, error, tick = (integer(r[i]) for i in (4, 5, 7))
    if now < int(f[5]) or error > 100:
        raise ValueError("NATIVE_RECEIPT_CLOCK")
    source_error = max(error, int(f[7]))
    source_age = now - int(f[10]) + source_error
    native_age = now - tick + error if tick else -1
    reason = "REQUIRED_INPUTS"
    if now + source_error >= int(f[6]):
        reason = "EXPIRED"
    elif not tick:
        reason = "NATIVE_DATA_UNAVAILABLE"
    elif (
        now - int(f[10]) - source_error < 0
        or source_age > 2000
        or now - tick - error < 0
        or native_age > 2000
    ):
        reason = "QUOTE_STALE"
    expected = "\t".join(
        map(
            str,
            (
                "connected-hold/1",
                f[1],
                f[2],
                f[4],
                now,
                error,
                source_age,
                tick,
                native_age,
                reason,
                f[11],
                0,
            ),
        )
    )
    if receipt != expected:
        raise ValueError("NATIVE_RECEIPT_SEMANTICS")
    return f


def verify_native_journal(
    journal_bytes,
    checkpoint_bytes,
    *,
    scope,
    client,
    incarnation,
    epoch,
    binding_hash,
    key,
    expected_journal_hash=None,
    minimum_sequence=None,
):
    """Return immutable evidence; all caller pins are independent of file contents."""
    if (
        not all(isinstance(v, str) and hex64(v) for v in (scope, client, incarnation, binding_hash))
        or type(epoch) is not int
        or not 1 <= epoch < 10**15
        or type(key) is not bytes
        or not 32 <= len(key) <= 64
        or any(c < 33 or c > 126 for c in key)
        or (
            expected_journal_hash is not None
            and (not isinstance(expected_journal_hash, str) or not hex64(expected_journal_hash))
        )
        or (
            minimum_sequence is not None
            and (type(minimum_sequence) is not int or minimum_sequence < 0)
        )
    ):
        raise ValueError("NATIVE_EXPECTED_BINDING")
    raw, checkpoint = _ascii(journal_bytes, MAX_JOURNAL), _ascii(checkpoint_bytes, 8192)
    journal_hash = hashlib.sha256(journal_bytes).hexdigest()
    if expected_journal_hash is not None and not hmac.compare_digest(
        journal_hash, expected_journal_hash
    ):
        raise ValueError("NATIVE_RETAINED_CHECKPOINT_MISMATCH")
    if not raw.endswith("\r\n") or not checkpoint.endswith("\r\n"):
        raise ValueError("NATIVE_TRUNCATED_OR_NONCANONICAL_FILE")
    cp = checkpoint[:-2].split("\t")
    if (
        len(cp) != 8
        or cp[:4] != ["connected-checkpoint/1", scope, incarnation, str(epoch)]
        or cp[4] != journal_hash
    ):
        raise ValueError("NATIVE_CHECKPOINT_BINDING_OR_HASH")
    expected_binding = "\t".join(
        ("BIND", scope, client, incarnation, str(epoch), binding_hash, digest(key.hex()))
    )
    rows = raw[:-2].split("\r\n")
    if len(rows) > 4096:
        raise ValueError("NATIVE_JOURNAL_CAPACITY")
    previous, acknowledged = "GENESIS", 0
    observations, receipts, ids = [], [], set()
    for sequence, line in enumerate(rows, 1):
        row = line.split("|")
        if (
            len(line) > 8192
            or len(row) != 4
            or row[0] != str(sequence)
            or row[1] != previous
            or digest("|".join(row[:3])) != row[3]
        ):
            raise ValueError("NATIVE_JOURNAL_INTEGRITY")
        previous = row[3]
        if sequence == 1:
            if not hmac.compare_digest(row[2], expected_binding):
                raise ValueError("NATIVE_JOURNAL_BINDING")
            continue
        record = row[2].split("\t")
        if len(record) == 3 and record[0] == "RECEIPT":
            if acknowledged != len(receipts):
                raise ValueError("NATIVE_PENDING_SEQUENCE")
            work, receipt = _unhex(record[1]), _unhex(record[2])
            f = _receipt(receipt, work, scope, binding_hash)
            if f[1] in ids or int(f[2]) != len(receipts) + 1:
                raise ValueError("NATIVE_RECEIPT_SEQUENCE")
            ids.add(f[1])
            observations.append(work)
            receipts.append(receipt)
        elif len(record) == 2 and record[0] == "ACK":
            if acknowledged == len(receipts) or record[1] != digest(receipts[acknowledged]):
                raise ValueError("NATIVE_ACK_MISMATCH")
            acknowledged += 1
        else:
            raise ValueError("NATIVE_RECORD_SCHEMA")
    receipt_hash = digest(receipts[-1]) if receipts else "0" * 64
    if cp[5:] != [str(len(receipts)), receipt_hash, "1" if acknowledged == len(receipts) else "0"]:
        raise ValueError("NATIVE_CHECKPOINT_STATE")
    if minimum_sequence is not None and len(receipts) < minimum_sequence:
        raise ValueError("NATIVE_CHECKPOINT_ROLLBACK")
    peer = PeerCheckpoint(
        scope, journal_hash, len(receipts), receipt_hash, acknowledged == len(receipts)
    )
    return VerifiedNativeJournal(
        peer,
        client,
        incarnation,
        epoch,
        binding_hash,
        previous,
        tuple(observations),
        tuple(receipts),
    )


def _bounded_read(path, limit):
    with Path(path).open("rb") as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise ValueError("NATIVE_FILE_SIZE_OR_TYPE")
    return data


def read_native_checkpoint(journal_path, checkpoint_path, **pins):
    """Read a stopped inbox or consistent copies, returning its PairCheckpoint input.

    Re-reading the checkpoint detects a concurrent checkpoint publication. A
    matching result describes the captured files, not proof the writer is stopped.
    Retirement requires an independent stopped-writer check by the caller.
    """
    first = _bounded_read(checkpoint_path, 8192)
    journal = _bounded_read(journal_path, MAX_JOURNAL)
    if _bounded_read(checkpoint_path, 8192) != first:
        raise ValueError("NATIVE_FILES_CHANGED_DURING_READ")
    return verify_native_journal(journal, first, **pins).peer
