"""Write synthetic M2B test inputs; never connect to a terminal or broker."""

import argparse
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

from fx_talanta.domain.ea_protocol import Envelope, ExecutionRequest
from fx_talanta.domain.models import AccountIdentity, Environment
from fx_talanta.execution_contracts.ea_file import encode_request

NOW = datetime(2026, 1, 5, 0, 0, tzinfo=UTC)
SCOPE = AccountIdentity(
    environment=Environment.PAPER, broker="fixture", server="offline", login="42", venue="SIMULATOR"
)
DIGEST = "a" * 64


def fixture_requests():
    fields = dict(
        account=SCOPE,
        sequence=1,
        created_at=NOW,
        expires_at=NOW + timedelta(hours=1),
        release_hash=DIGEST,
        policy_hash=DIGEST,
        intent_hash=DIGEST,
        snapshot_hash=DIGEST,
        message_id=UUID(int=1),
        reservation_id=UUID(int=101),
        action="ENTER",
        symbol="EURUSD",
        broker_symbol="FXT_EURUSD",
        currency="USD",
        max_volume="0.09",
        max_risk="30",
        side="BUY",
        stop="1.098",
        target="1.1046",
    )
    cases = [
        fields,
        fields | {"max_risk": "31"},
        fields | {"message_id": UUID(int=2), "reservation_id": UUID(int=102), "sequence": 2},
        fields
        | {
            "message_id": UUID(int=3),
            "reservation_id": UUID(int=103),
            "sequence": 3,
            "action": "CLOSE",
            "max_risk": "0",
            "position_id": "101",
            "expected_state_version": 3,
            "stop": None,
            "target": None,
        },
        fields
        | {
            "message_id": UUID(int=4),
            "reservation_id": UUID(int=104),
            "sequence": 4,
            "action": "TIGHTEN_STOP",
            "max_risk": "0",
            "position_id": "101",
            "expected_state_version": 3,
            "stop": "1.099",
            "target": None,
        },
        fields
        | {
            "message_id": UUID(int=5),
            "reservation_id": UUID(int=105),
            "sequence": 5,
            "action": "CANCEL",
            "max_risk": "0",
            "order_id": "202",
            "expected_state_version": 3,
            "stop": None,
            "target": None,
        },
        fields
        | {
            "message_id": UUID(int=6),
            "reservation_id": UUID(int=106),
            "sequence": 6,
            "side": "SELL",
            "stop": "1.102",
            "target": "1.096",
        },
        fields
        | {
            "message_id": UUID(int=7),
            "reservation_id": UUID(int=107),
            "sequence": 7,
            "symbol": "USDJPY",
            "broker_symbol": "FXT_USDJPY",
            "side": "SELL",
            "stop": "150.2",
            "target": "149.6",
        },
    ]
    return [Envelope.seal(ExecutionRequest(**c)) for c in cases]


def export(output):
    output.mkdir(parents=True, exist_ok=True)
    requests = fixture_requests()
    (output / "m2b-requests.tsv").write_text(
        "\n".join(encode_request(r) for r in requests) + "\n", encoding="ascii", newline="\n"
    )
    (output / "requests.json").write_text(
        json.dumps([r.model_dump(mode="json") for r in requests], indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return len(requests)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(".local/m2b-fixtures"))
    args = parser.parse_args()
    print(json.dumps({"synthetic_requests": export(args.output)}))
