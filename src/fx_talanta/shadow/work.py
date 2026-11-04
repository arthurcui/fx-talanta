"""Shadow projections preserve the complete original M2A request in the backend."""

import json
from decimal import Decimal

from fx_talanta.domain.ea_protocol import Envelope, ExecutionRequest
from fx_talanta.safety.risk import SafetyInput, evaluate
from fx_talanta.shadow.wire import digest, hex64, integer

FIELDS = tuple(SafetyInput.model_fields)


def scope_for(account):
    return digest(
        json.dumps(account.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    )


def snapshot_hash(snapshot):
    return digest(
        json.dumps(snapshot.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    )


def project(envelope, snapshot):
    envelope = Envelope.model_validate_json(envelope.model_dump_json())
    snapshot = SafetyInput.model_validate_json(snapshot.model_dump_json())
    p = envelope.payload
    if not isinstance(p, ExecutionRequest) or p.account.environment.value != "PAPER":
        raise ValueError("PAPER_REQUEST_REQUIRED")
    if p.action != "ENTER":
        raise ValueError("SHADOW_ENTRIES_ONLY")
    if p.snapshot_hash != snapshot_hash(snapshot) or (
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


def parse_work(text):
    from uuid import UUID

    f = text.split("\t")
    if len(f) != 9 + len(FIELDS) or f[0] != "shadow-work/1" or len(text) > 4096:
        raise ValueError("INVALID_WORK")
    if str(UUID(f[1])) != f[1] or not all(hex64(x) for x in f[2:6]):
        raise ValueError("INVALID_WORK")
    seq, created, expires = map(integer, f[6:9])
    if seq < 1 or expires <= created:
        raise ValueError("INVALID_WORK")
    values = dict(zip(FIELDS, f[9:], strict=True))
    # Decimal parsing is exact; native protocol limits are explicit.
    for value in f[9:]:
        if len(value) > 32 or any(c in value for c in "\n\r| "):
            raise ValueError("INVALID_SNAPSHOT")
    snapshot = SafetyInput.model_validate(values)
    if snapshot.measured_at_ms > created:
        raise ValueError("FUTURE_SNAPSHOT")
    return f, snapshot


def assess(work, now, local_clock_error_ms=0):
    f, snapshot = parse_work(work)
    if not 0 <= local_clock_error_ms <= 100000000:
        raise ValueError("CLOCK_UNVERIFIED")
    clock_error = max(snapshot.clock_error_ms, local_clock_error_ms)
    elapsed = now - snapshot.measured_at_ms
    if now < int(f[7]) or elapsed < 0:
        reason, volume = "FUTURE_MESSAGE", "0"
    elif now + clock_error >= int(f[8]):
        reason, volume = "EXPIRED", "0"
    else:
        values = snapshot.model_dump()
        values["clock_error_ms"] = clock_error
        values.update(
            quote_age_ms=snapshot.quote_age_ms + elapsed,
            conversion_age_ms=snapshot.conversion_age_ms + elapsed,
            expires_in_ms=min(snapshot.expires_in_ms - elapsed, int(f[8]) - now),
        )
        try:
            result = evaluate(SafetyInput.model_validate(values))
            reason, volume = result["reason"], str(result.get("volume", "0"))
        except ValueError:
            reason, volume = "STALE_SNAPSHOT", "0"
    age = snapshot.quote_age_ms + elapsed + clock_error
    return "\t".join(
        [
            "shadow-receipt/1",
            f[1],
            digest(work),
            f[6],
            reason,
            str(now),
            str(age),
            volume,
            str(local_clock_error_ms),
            "0",
        ]
    )


def parse_receipt(text, work):
    f, _ = parse_work(work)
    r = text.split("\t")
    if (
        len(r) != 10
        or r[:4] != ["shadow-receipt/1", f[1], digest(work), f[6]]
        or r[9] != "0"
        or len(r[4]) > 64
        or not r[4].replace("_", "").isalnum()
    ):
        raise ValueError("RECEIPT_MISMATCH")
    integer(r[5])
    age = int(r[6])
    volume = Decimal(r[7])
    if not volume.is_finite() or volume < 0 or abs(age) > 10**15:
        raise ValueError("INVALID_RECEIPT")
    # Independent backend recomputation: an EA cannot broaden a verdict.
    expected = assess(work, int(r[5]), integer(r[8])).split("\t")
    if r[4] != expected[4] or age != int(expected[6]) or volume != Decimal(expected[7]):
        raise ValueError("NATIVE_VERDICT_MISMATCH")
    return r
