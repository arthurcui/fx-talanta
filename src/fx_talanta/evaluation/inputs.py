"""Normalized local simulation inputs; asserted provenance is never qualification."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, model_validator

from fx_talanta.domain.models import FrozenModel, Hash, Timestamp
from fx_talanta.domain.offline import Market
from fx_talanta.evaluation.ledger import digest
from fx_talanta.research.baseline import Bar


class SafetyEvidence(FrozenModel):
    state: Literal["CLEAR", "BLOCKED", "UNAVAILABLE"]
    currencies: tuple[Literal["USD", "EUR", "JPY"], ...]
    available_at: Timestamp
    expires_at: Timestamp
    reference_hash: Hash

    @model_validator(mode="after")
    def ordered(self):
        if self.expires_at <= self.available_at or len(set(self.currencies)) != len(
            self.currencies
        ):
            raise ValueError("invalid safety window or duplicate coverage")
        return self


class InputIdentity(FrozenModel):
    source_id: UUID
    event_id: UUID
    sequence: Annotated[int, Field(strict=True, ge=1)]
    provenance: Literal["SYNTHETIC", "RECORDED_OFFLINE"]
    channel: Literal["FIXTURE", "EA", "PYTHON", "MCP"]
    received_at: Timestamp
    market: Market
    calendar: SafetyEvidence | None = None
    news: SafetyEvidence | None = None
    news_content: Literal["NEUTRAL", "ADVERSE", "UNAVAILABLE"] = "UNAVAILABLE"

    @model_validator(mode="after")
    def known_at_receipt(self):
        if self.market.at > self.received_at or any(
            evidence and evidence.available_at > self.received_at
            for evidence in (self.calendar, self.news)
        ):
            raise ValueError("input unavailable at claimed source receipt")
        return self


class Envelope(InputIdentity):
    bars: Annotated[tuple[Bar, ...], Field(max_length=1000)] = ()

    @model_validator(mode="after")
    def bars_known(self):
        if any(b.available_at > self.received_at for b in self.bars):
            raise ValueError("future source bars")
        return self


class SourceRecord(InputIdentity):
    bars_hash: Hash
    normalized_at: Timestamp

    @model_validator(mode="after")
    def chronological(self):
        if self.normalized_at < self.received_at:
            raise ValueError("source normalization precedes receipt")
        return self


def bars_hash(bars):
    return digest([b.model_dump(mode="json") for b in bars])


def project(record, at):
    """Only narrow original safety; never replace quote/conversion timestamps."""
    if at < record.normalized_at:
        raise ValueError("normalization is in the future")
    currencies = {c for i in record.market.instruments for c in (i.base, i.quote)}

    def clear(evidence):
        return bool(
            evidence
            and evidence.state == "CLEAR"
            and evidence.available_at <= at < evidence.expires_at
            and currencies <= set(evidence.currencies)
        )

    calendar_ok = clear(record.calendar)
    news_ok = clear(record.news) and record.news_content != "UNAVAILABLE"
    market = Market.model_validate(
        {
            **record.market.model_dump(),
            "calendar_ok": record.market.calendar_ok and calendar_ok,
            "news_ok": record.market.news_ok and news_ok,
            "event_blackout": record.market.event_blackout
            or bool(record.calendar and record.calendar.state == "BLOCKED"),
        }
    )
    return market, record.news_content if news_ok else "UNAVAILABLE"


def normalize(envelope, at):
    from fx_talanta.evaluation.runner import Tick

    envelope = Envelope.model_validate(
        envelope.model_dump() if isinstance(envelope, Envelope) else envelope
    )
    record = SourceRecord(
        **envelope.model_dump(exclude={"bars"}),
        bars_hash=bars_hash(envelope.bars),
        normalized_at=at,
    )
    market, news = project(record, at)
    return Tick(
        event_id=envelope.event_id,
        sequence=envelope.sequence,
        market=market,
        bars=envelope.bars,
        news=news,
        source_record=record,
    )
