"""Canonical demo-only request codec. Encoding grants no execution authority."""

import re

from fx_talanta.domain.ea_protocol import Envelope, ExecutionRequest, canonical_bytes


def encode_request(envelope: Envelope) -> str:
    envelope = Envelope.model_validate_json(envelope.model_dump_json())
    p = envelope.payload
    if not isinstance(p, ExecutionRequest):
        raise ValueError("execution request required")
    if p.account.venue != "BROKER_DEMO" or p.account.environment.value != "PAPER":
        raise ValueError("file transport is confined to PAPER/BROKER_DEMO")
    data = p.model_dump(mode="json")
    a = data["account"]
    fields = [
        "ea-demo/1",
        envelope.digest,
        data["message_id"],
        a["environment"],
        a["broker"],
        a["server"],
        a["login"],
        a["venue"],
        data["sequence"],
        data["created_at"],
        data["expires_at"],
        data["release_hash"],
        data["policy_hash"],
        data["intent_hash"],
        data["reservation_id"],
        data["snapshot_hash"],
        data["action"],
        data["symbol"],
        data["broker_symbol"],
        data["currency"],
        data["max_volume"],
        data["max_risk"],
        data["side"],
        data["stop"],
        data["target"],
        data["position_id"],
        data["order_id"],
        data["expected_state_version"],
    ]
    for field in fields:
        if field is not None and (
            not re.fullmatch(r"[\x20-\x7e]{1,160}", str(field))
            or any(c in str(field) for c in ('"', "\\", "|", "~"))
        ):
            raise ValueError("unsupported text in restricted native codec")
    for key in ("max_volume", "max_risk", "stop", "target"):
        if data[key] is not None and not re.fullmatch(
            r"(?:0|[1-9][0-9]{0,7})(?:\.[0-9]{0,7}[1-9])?", data[key]
        ):
            raise ValueError("native amount requires at most eight whole/fractional digits")
    for key in ("position_id", "order_id"):
        if data[key] is not None and not re.fullmatch(r"[1-9][0-9]{0,14}", data[key]):
            raise ValueError("native broker tickets must be positive bounded decimal identifiers")
    for key in ("sequence", "expected_state_version"):
        if data[key] is not None and data[key] > 999_999_999_999_999:
            raise ValueError("native sequence exceeds exact integer bound")
    # This is the canonical payload hashed independently by the native decoder.
    if len(canonical_bytes(p)) > 4096:
        raise ValueError("request too large")
    return "\t".join("~" if f is None else str(f) for f in fields)


def decode_request(frame: str) -> Envelope:
    """Validate an archived native frame with the independent Python schema/hash."""
    f = frame.split("\t")
    if len(f) != 28 or f[0] != "ea-demo/1":
        raise ValueError("invalid native frame")

    def nullable(value):
        return None if value == "~" else value

    request = ExecutionRequest.model_validate(
        dict(
            message_id=f[2],
            account=dict(environment=f[3], broker=f[4], server=f[5], login=f[6], venue=f[7]),
            sequence=int(f[8]),
            created_at=f[9],
            expires_at=f[10],
            release_hash=f[11],
            policy_hash=f[12],
            intent_hash=f[13],
            reservation_id=f[14],
            snapshot_hash=f[15],
            action=f[16],
            symbol=f[17],
            broker_symbol=f[18],
            currency=f[19],
            max_volume=f[20],
            max_risk=f[21],
            side=nullable(f[22]),
            stop=nullable(f[23]),
            target=nullable(f[24]),
            position_id=nullable(f[25]),
            order_id=nullable(f[26]),
            expected_state_version=None if f[27] == "~" else int(f[27]),
        )
    )
    envelope = Envelope(payload=request, digest=f[1])
    if encode_request(envelope) != frame:
        raise ValueError("noncanonical native frame")
    return envelope
