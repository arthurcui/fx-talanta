"""Export synthetic native cases and verify independently produced native receipts."""

import argparse
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

from fx_talanta.domain.ea_protocol import Envelope, ExecutionRequest
from fx_talanta.domain.models import Environment
from fx_talanta.safety.risk import SafetyInput
from fx_talanta.shadow.wire import Frame
from fx_talanta.shadow.work import assess, parse_receipt, project, scope_for, snapshot_hash
from fx_talanta.storage.config import fixture_account

ROOT = Path(__file__).resolve().parents[1]
KEY = b"s" * 32  # synthetic fixture key, not a credential
CLIENT, RELEASE, POLICY = "a" * 64, "b" * 64, "c" * 64
NOW = 1767614400000
ACCOUNT = fixture_account(Environment.PAPER)


def work(sequence=1, now=NOW, **changes):
    defaults = json.loads((ROOT / "tests/fixtures/safety/risk.json").read_text())["defaults"]
    snapshot = SafetyInput.model_validate(defaults | {"measured_at_ms": now} | changes)
    at = datetime.fromtimestamp(now / 1000, UTC)
    request = ExecutionRequest(
        message_id=UUID(int=sequence),
        account=ACCOUNT,
        sequence=sequence,
        created_at=at,
        expires_at=at + timedelta(seconds=60),
        release_hash=RELEASE,
        policy_hash=POLICY,
        intent_hash="d" * 64,
        reservation_id=UUID(int=sequence + 1000),
        snapshot_hash=snapshot_hash(snapshot),
        action="ENTER",
        symbol=snapshot.symbol,
        broker_symbol=snapshot.symbol,
        currency=snapshot.currency,
        max_volume=snapshot.request_volume,
        max_risk=snapshot.request_risk,
        side=snapshot.side,
        stop=snapshot.stop,
        target="1.1046",
    )
    return Envelope.seal(request), snapshot


def cases():
    source = json.loads((ROOT / "tests/fixtures/safety/risk.json").read_text())
    for case in source["cases"]:
        yield case["id"], project(*work(**case["input"])), NOW, 0
    for name, elapsed, clock_error in [
        ("age-boundary", 1490, 0),
        ("age-over", 1491, 0),
        ("expired", 60000, 0),
        ("unverified-local-clock", 0, 1000),
    ]:
        yield name, project(*work()), NOW + elapsed, clock_error


def export(folder):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "shadow-cases.tsv").write_text(
        "".join(
            f"{name}\t{now}\t{error}\t{value.encode('ascii').hex()}\n"
            for name, value, now, error in cases()
        ),
        encoding="ascii",
    )
    (folder / "shadow-auth.txt").write_bytes(
        Frame("C2S", scope_for(ACCOUNT), CLIENT, "d" * 64, NOW, NOW + 5000, "PULL", "").encode(KEY)
    )


def compare(folder):
    rows = [line.split("\t") for line in (folder / "shadow-results.tsv").read_text().splitlines()]
    expected = list(cases())
    if len(rows) != len(expected):
        raise ValueError("native case count differs")
    results = []
    for row, (name, value, now, error) in zip(rows, expected, strict=True):
        receipt = bytes.fromhex(row[1]).decode("ascii")
        native = parse_receipt(receipt, value)
        python = assess(value, now, error).split("\t")
        if row[0] != name or native[:7] != python[:7]:
            raise ValueError("native case mismatch")
        results.append(dict(id=name, reason=native[4], volume=native[7], passed=True))
    checks = dict(
        line.split("\t") for line in (folder / "shadow-checks.tsv").read_text().splitlines()
    )
    if not checks or any(v != "PASS" for v in checks.values()):
        raise ValueError("native control checks failed")
    return dict(
        scope="Synthetic native codec/risk/inbox; no broker or native HTTPS execution",
        parity=results,
        checks=checks,
        execution_enabled=False,
        connected_acceptance=False,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--export", type=Path)
    parser.add_argument("--compare", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.export:
        export(args.export)
    else:
        result = compare(args.compare)
        args.output.write_text(json.dumps(result, indent=2) + "\n")
        print(
            json.dumps(
                dict(
                    native_cases=len(result["parity"]),
                    checks=len(result["checks"]),
                    execution_enabled=False,
                )
            )
        )
