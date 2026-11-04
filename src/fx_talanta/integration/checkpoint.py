"""Independent native DG journal verification and paired checkpoint construction.

Integrity alone does not prove TLS authentication or broker execution. The input
must be a stopped/consistent copy; retain the resulting checkpoint independently.
"""

from datetime import UTC, datetime
from decimal import Decimal

from fx_talanta.connected_shadow.authority import PairCheckpoint, PeerCheckpoint, backend_checkpoint
from fx_talanta.safety.control import LossState
from fx_talanta.shadow.wire import digest
from fx_talanta.shadow.work import parse_receipt, parse_work


def verify_native(data, *, scope, client, release, policy, key, expected_tip=None):
    if type(data) is not bytes or not 0 < len(data) <= 8_000_000:
        raise ValueError("NATIVE_JOURNAL_SIZE")
    text = data.decode("ascii")
    if not text.endswith("\n"):
        raise ValueError("NATIVE_JOURNAL_INCOMPLETE")
    lines = text.splitlines()
    tip = digest("".join(line + "\n" for line in lines))
    if expected_tip is not None and expected_tip != tip:
        raise ValueError("NATIVE_CHECKPOINT_CONFLICT")
    previous, records = "GENESIS", []
    for sequence, line in enumerate(lines, 1):
        parts = line.split("|")
        if (
            len(parts) != 4
            or parts[0] != str(sequence)
            or parts[1] != previous
            or digest("|".join(parts[:3])) != parts[3]
            or len(line) > 8192
        ):
            raise ValueError("NATIVE_JOURNAL_INTEGRITY")
        previous = parts[3]
        records.append(parts[2].split("\t"))
    expected = ["DGBIND", scope, client, release, policy, digest(key.hex())]
    if records[0] != expected:
        raise ValueError("NATIVE_BINDING_CONFLICT")
    sequence, receipt_hash, acked, ledger = 0, "0" * 64, True, None
    ids = set()
    for row in records[1:]:
        if row[0] == "DGACK":
            if len(row) != 2 or acked or row[1] != receipt_hash:
                raise ValueError("NATIVE_ACK_CONFLICT")
            acked = True
            continue
        if len(row) != 3 or row[0] != "DGRECEIPT" or not acked:
            raise ValueError("NATIVE_RECORD_SEQUENCE")
        packet, receipt = (bytes.fromhex(v).decode("ascii") for v in row[1:])
        fields = packet.split("\t")
        if (
            len(fields) != 11
            or fields[0] != "disabled-work/1"
            or any(v not in {"0", "1"} for v in fields[8:])
        ):
            raise ValueError("NATIVE_PACKET")
        work = bytes.fromhex(fields[1]).decode("ascii")
        f, snapshot = parse_work(work)
        r = parse_receipt(receipt, work)
        if f[3:6] != [scope, release, policy] or f[1] in ids or int(r[3]) != sequence + 1:
            raise ValueError("NATIVE_WORK_BINDING")
        next_state = LossState(
            day=datetime.strptime(fields[2], "%Y%m%d").date(),
            start=Decimal(fields[3]),
            day_flows=Decimal(fields[4]),
            units=Decimal(fields[5]),
            high_nav=Decimal(fields[6]),
            daily_loss=Decimal(fields[7]),
            loss_pause=fields[8] == "1",
            hard_halt=fields[9] == "1",
            owner_pause=fields[10] == "1",
        )
        if next_state.day != datetime.fromtimestamp(int(r[5]) / 1000, UTC).date():
            raise ValueError("NATIVE_LEDGER_DAY")
        if ledger and (
            next_state.day < ledger.day
            or next_state.high_nav < ledger.high_nav
            or (ledger.hard_halt and not next_state.hard_halt)
            or (ledger.owner_pause and not next_state.owner_pause)
            or (
                next_state.day == ledger.day
                and (
                    next_state.start != ledger.start
                    or (ledger.loss_pause and not next_state.loss_pause)
                )
            )
        ):
            raise ValueError("NATIVE_LOSS_ROLLBACK")
        required = (
            (1 if next_state.hard_halt else 0)
            | (2 if next_state.loss_pause else 0)
            | (64 if next_state.owner_pause else 0)
        )
        if (
            snapshot.day_start != next_state.start
            or snapshot.day_loss != next_state.daily_loss
            or snapshot.flags & required != required
        ):
            raise ValueError("NATIVE_LEDGER_SNAPSHOT_CONFLICT")
        ids.add(f[1])
        ledger = next_state
        sequence += 1
        receipt_hash = digest(receipt)
        acked = False
    return PeerCheckpoint(scope, tip, sequence, receipt_hash, acked)


def paired_checkpoint(store, native_bytes, **pins):
    native = verify_native(native_bytes, **pins)
    return PairCheckpoint.match(backend_checkpoint(store, pins["scope"]), native)
