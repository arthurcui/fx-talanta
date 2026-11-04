"""Reference risk projection; management authority comes from native ownership checks."""

from fx_talanta.domain.ea_protocol import Envelope, ExecutionRequest
from fx_talanta.safety.risk import SafetyInput
from fx_talanta.shadow.work import FIELDS, parse_work, scope_for, snapshot_hash


def project(envelope, snapshot):
    envelope = Envelope.model_validate_json(envelope.model_dump_json())
    snapshot = SafetyInput.model_validate_json(snapshot.model_dump_json())
    p = envelope.payload
    if not isinstance(p, ExecutionRequest) or p.account.environment.value != "PAPER":
        raise ValueError("PAPER_REQUEST_REQUIRED")
    if p.account.venue != "BROKER_DEMO":
        raise ValueError("DEMO_ACCOUNT_REQUIRED")
    if (
        p.snapshot_hash != snapshot_hash(snapshot)
        or p.symbol != snapshot.symbol
        or p.currency != snapshot.currency
    ):
        raise ValueError("SNAPSHOT_REQUEST_MISMATCH")
    if p.action == "ENTER" and (
        p.symbol,
        p.side,
        p.currency,
        p.stop,
        p.max_volume,
        p.max_risk,
    ) != (
        snapshot.symbol,
        snapshot.side,
        snapshot.currency,
        snapshot.stop,
        snapshot.request_volume,
        snapshot.request_risk,
    ):
        raise ValueError("SNAPSHOT_REQUEST_MISMATCH")
    values = snapshot.model_dump(mode="json")
    fields = [
        "shadow-work/1",
        str(p.message_id),
        envelope.digest,
        scope_for(p.account),
        p.release_hash,
        p.policy_hash,
        str(p.sequence),
        str(int(p.created_at.timestamp() * 1000)),
        str(int(p.expires_at.timestamp() * 1000)),
    ]
    fields += [
        str(int(values[k])) if isinstance(values[k], bool) else str(values[k]) for k in FIELDS
    ]
    result = "\t".join(fields)
    parse_work(result)
    return result
