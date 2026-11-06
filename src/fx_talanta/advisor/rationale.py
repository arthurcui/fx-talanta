"""Original recorded rationale, explicitly separated from later model interpretation."""

from uuid import UUID

from fx_talanta.domain.models import AccountIdentity, FrozenModel, Timestamp


class RecordedRationale(FrozenModel):
    account: AccountIdentity
    record_id: UUID
    record_sha256: str
    as_of: Timestamp
    original_recorded_rationale: str
    recorded_validation_reason: str
    label: str = "ORIGINAL_RECORDED_TEXT_UNTRUSTED_QUOTATION"


def from_receipt(repository, evidence, record_id):
    citation = next(
        (c for c in evidence.citations if c.record_id == record_id and c.kind == "decision"), None
    )
    if citation is None:
        raise ValueError("decision unavailable at requested cutoff")
    import hashlib

    record = repository.get(record_id)
    if (
        record.account != evidence.account
        or hashlib.sha256(record.model_dump_json().encode()).hexdigest() != citation.sha256
    ):
        raise ValueError("rationale source mismatch")
    return RecordedRationale(
        account=evidence.account,
        record_id=record_id,
        record_sha256=citation.sha256,
        as_of=evidence.as_of,
        original_recorded_rationale=record.body.decision.rationale
        if record.body.decision
        else "UNAVAILABLE",
        recorded_validation_reason=record.body.reason,
    )
