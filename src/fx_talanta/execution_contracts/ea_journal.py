"""Read-only verification of the native Tester journal; never a dispatch service."""

import hashlib
from dataclasses import dataclass
from decimal import Decimal

from fx_talanta.domain.ea_protocol import Envelope
from fx_talanta.execution_contracts.ea_file import decode_request

STATES = frozenset(
    {
        "READY",
        "REJECTED",
        "SUBMITTING",
        "ACKNOWLEDGED",
        "OUTCOME_UNKNOWN",
        "PROTECTION_PENDING",
        "PROTECTED",
        "CLOSED",
    }
)


@dataclass(frozen=True)
class NativeRecord:
    envelope: Envelope
    state: str
    reason: str
    version: int
    filled_units: int
    open_units: int
    remaining_units: int
    order: int
    position: int
    accepted_stop: Decimal
    record_hash: str


def read_journal(data: bytes) -> list[NativeRecord]:
    """Verify a stable copy. A partial tail is an error, never a valid prefix."""
    if data and not data.endswith(b"\r\n"):
        raise ValueError("incomplete journal tail")
    previous = "GENESIS"
    latest = {}
    request_sequence = 0
    result = []
    for sequence, line in enumerate(data.decode("ascii").splitlines(), 1):
        parts = line.split("|")
        if len(parts) != 4 or parts[:2] != [str(sequence), previous]:
            raise ValueError("journal sequence/hash-chain mismatch")
        digest = hashlib.sha256("|".join(parts[:3]).encode("ascii")).hexdigest()
        if digest != parts[3]:
            raise ValueError("journal record digest mismatch")
        f = parts[2].split("\t")
        if len(f) != 37 or f[0] not in STATES:
            raise ValueError("invalid native record")
        envelope = decode_request("\t".join(f[9:]))
        numbers = [int(x) for x in f[2:8]]
        if any(str(n) != value or n < 0 for n, value in zip(numbers, f[2:8], strict=True)):
            raise ValueError("invalid native quantities")
        version, filled, opened, remaining, order, position = numbers
        stop = Decimal(f[8])
        if not stop.is_finite() or stop < 0 or not version:
            raise ValueError("invalid stop/version")
        allowance = envelope.payload.max_volume * Decimal(100_000_000)
        if opened > filled or filled + remaining > allowance or (opened and not position):
            raise ValueError("quantity conservation violation")
        old = latest.get(envelope.payload.message_id)
        if old is None:
            if version != 1 or envelope.payload.sequence != request_sequence + 1:
                raise ValueError("request sequence/version mismatch")
            request_sequence += 1
        elif envelope.digest != old.envelope.digest or version != old.version + 1:
            raise ValueError("request digest/version mismatch")
        elif filled < old.filled_units:
            raise ValueError("filled quantity regressed")
        record = NativeRecord(
            envelope, f[0], f[1], version, filled, opened, remaining, order, position, stop, digest
        )
        latest[envelope.payload.message_id] = record
        result.append(record)
        previous = digest
    return result
