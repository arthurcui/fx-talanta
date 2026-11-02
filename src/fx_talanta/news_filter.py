"""Offline, point-in-time calendar/news restrictions. No retrieval or execution authority."""

from datetime import timedelta
from hashlib import sha256
from typing import Annotated, Literal

from pydantic import Field, model_validator

from fx_talanta.domain.models import FrozenModel, Identifier, NewsRevision, Text, Timestamp, utc

Currency = Literal["USD", "EUR", "JPY"]
Seconds = Annotated[int, Field(ge=0, le=86400)]


class SourceRule(FrozenModel):
    source: Identifier
    role: Literal["CALENDAR", "NEWS"]
    required: bool
    currencies: tuple[Currency, ...] = ("USD", "EUR", "JPY")
    max_age_seconds: Annotated[int, Field(ge=1, le=86400)] = 120


class FilterPolicy(FrozenModel):
    version: Identifier
    sources: tuple[SourceRule, ...]
    blackout_before_seconds: Seconds = 1800
    blackout_after_seconds: Seconds = 1800
    release_lateness_seconds: Seconds = 120
    news_relevance_seconds: Annotated[int, Field(ge=1, le=86400)] = 3600

    @model_validator(mode="after")
    def complete(self):
        if len({s.source for s in self.sources}) != len(self.sources):
            raise ValueError("source IDs must be unique")
        for role in ("CALENDAR", "NEWS"):
            covered = {
                c for s in self.sources if s.required and s.role == role for c in s.currencies
            }
            if covered != {"USD", "EUR", "JPY"}:
                raise ValueError("required calendar and news coverage must include USD/EUR/JPY")
        return self


class FeedCheck(FrozenModel):
    source: Identifier
    checked_at: Timestamp
    available_at: Timestamp
    connection: Literal["OK", "FAILED", "THROTTLED", "UNKNOWN"]
    complete: bool
    verified_through: Timestamp | None = None
    coverage_from: Timestamp
    coverage_until: Timestamp
    currencies: tuple[Currency, ...]
    verification: Text

    @model_validator(mode="after")
    def ordered(self):
        if self.checked_at > self.available_at or self.coverage_from >= self.coverage_until:
            raise ValueError("invalid check availability or coverage interval")
        if self.verified_through and self.verified_through > self.checked_at:
            raise ValueError("verification cannot be from the future")
        return self


class CalendarRevision(FrozenModel):
    source: Identifier
    event_id: Identifier
    revision: Annotated[int, Field(ge=1)]
    currency: Currency
    impact: Literal["HIGH", "MEDIUM", "LOW", "UNKNOWN"]
    scheduled_at: Timestamp
    available_at: Timestamp
    status: Literal["SCHEDULED", "CANCELLED"] = "SCHEDULED"
    expects_release: bool = True


class NewsEvidence(FrozenModel):
    item: NewsRevision
    # Qualified adapter links an actual release to its calendar source/event ID.
    releases: tuple[tuple[Identifier, Identifier], ...] = ()


class FilterInputs(FrozenModel):
    provenance: Literal["FIXTURE"] = "FIXTURE"
    checks: tuple[FeedCheck, ...] = Field(default=(), max_length=10000)
    calendar: tuple[CalendarRevision, ...] = Field(default=(), max_length=10000)
    news: tuple[NewsEvidence, ...] = Field(default=(), max_length=10000)


class FilterResult(FrozenModel):
    policy_version: Identifier
    policy_hash: str
    input_hash: str
    cutoff: Timestamp
    symbol: Literal["EURUSD", "USDJPY"]
    provenance: Literal["FIXTURE"] = "FIXTURE"
    calendar_ok: bool
    news_ok: bool
    event_blackout: bool
    reasons: tuple[str, ...]
    optional_degradations: tuple[str, ...]
    calendar_refs: tuple[tuple[str, str, int], ...]
    news_refs: tuple[tuple[str, str, int], ...]
    execution_enabled: Literal[False] = False


def _latest(rows, key, version, available, cutoff):
    """Identical duplicates collapse; conflicting evidence fails closed."""
    seen, selected = {}, {}
    for row in rows:
        if available(row) > cutoff:
            continue
        identity = key(row)
        revision = version(row)
        slot = (identity, revision)
        if slot in seen and seen[slot] != row:
            raise ValueError("conflicting immutable evidence version")
        seen[slot] = row
        if identity not in selected or revision > version(selected[identity]):
            selected[identity] = row
    return list(selected.values())


def assess(policy: FilterPolicy, inputs: FilterInputs, symbol: str, cutoff) -> FilterResult:
    policy = FilterPolicy.model_validate(policy.model_dump(mode="json"))
    inputs = FilterInputs.model_validate(inputs.model_dump(mode="json"))
    cutoff = utc(cutoff)
    if symbol not in {"EURUSD", "USDJPY"}:
        raise ValueError("use an explicitly normalized supported currency pair")
    currencies = {symbol[:3], symbol[3:]}
    rules = {s.source: s for s in policy.sources}
    for row, role in [(e, "CALENDAR") for e in inputs.calendar] + [
        (e.item, "NEWS") for e in inputs.news
    ]:
        if row.source not in rules or rules[row.source].role != role:
            raise ValueError("evidence source is not approved for this role")
    if any(c.source not in rules for c in inputs.checks):
        raise ValueError("unapproved health source")

    checks = _latest(
        inputs.checks, lambda c: c.source, lambda c: c.checked_at, lambda c: c.available_at, cutoff
    )
    events = _latest(
        inputs.calendar,
        lambda e: (e.source, e.event_id),
        lambda e: e.revision,
        lambda e: e.available_at,
        cutoff,
    )
    news = _latest(
        inputs.news,
        lambda e: (e.item.source, e.item.item_id),
        lambda e: e.item.revision,
        lambda e: e.item.available_at,
        cutoff,
    )
    publications = {}
    for evidence in inputs.news:
        item = evidence.item
        if item.available_at > cutoff:
            continue
        key = (item.source, item.item_id)
        if key in publications and publications[key] != item.published_at:
            raise ValueError("revisions cannot reset original publication time")
        publications[key] = item.published_at
    checks = {c.source: c for c in checks}
    reasons, optional = [], []
    health = {"CALENDAR": True, "NEWS": True}
    healthy_sources = set()
    before = timedelta(seconds=policy.blackout_before_seconds)
    after = timedelta(seconds=policy.blackout_after_seconds)
    for source, rule in rules.items():
        relevant = currencies.intersection(rule.currencies)
        if not relevant:
            continue
        check = checks.get(source)
        valid = check is not None and (
            check.connection == "OK"
            and check.complete
            and check.verified_through is not None
            and 0 <= (cutoff - check.checked_at).total_seconds() <= rule.max_age_seconds
            and 0 <= (cutoff - check.verified_through).total_seconds() <= rule.max_age_seconds
            and relevant <= set(check.currencies)
            and check.coverage_from <= cutoff < check.coverage_until
        )
        if valid and rule.role == "CALENDAR":
            valid = check.coverage_from <= cutoff - after and check.coverage_until > cutoff + before
        if valid:
            healthy_sources.add(source)
        elif rule.required:
            health[rule.role] = False
            reasons.append(f"REQUIRED_COVERAGE:{source}")
        else:
            optional.append(f"OPTIONAL_COVERAGE:{source}")

    blackout = False
    refs = []
    for event in sorted(events, key=lambda e: (e.source, e.event_id)):
        if event.currency not in currencies or event.status == "CANCELLED":
            continue
        refs.append((event.source, event.event_id, event.revision))
        released = any(
            n.item.source in healthy_sources
            and event.currency in n.item.currencies
            and n.item.published_at >= event.scheduled_at
            and (event.source, event.event_id) in n.releases
            for n in news
        )
        if event.impact in {"HIGH", "UNKNOWN"}:
            if event.scheduled_at - before <= cutoff <= event.scheduled_at + after:
                blackout = True
                reasons.append(f"EVENT_BLACKOUT:{event.source}:{event.event_id}")
            if (
                event.expects_release
                and rules[event.source].required
                and cutoff
                >= event.scheduled_at + timedelta(seconds=policy.release_lateness_seconds)
                and not released
            ):
                health["NEWS"] = False
                reasons.append(f"MISSING_RELEASE:{event.source}:{event.event_id}")

    # Revisions do not refresh the story's publication-based relevance clock.
    news_refs = tuple(
        sorted(
            (n.item.source, n.item.item_id, n.item.revision)
            for n in news
            if n.item.source in healthy_sources
            and currencies.intersection(n.item.currencies)
            and 0 <= (cutoff - n.item.published_at).total_seconds() <= policy.news_relevance_seconds
        )
    )
    return FilterResult(
        policy_version=policy.version,
        policy_hash=sha256(policy.model_dump_json().encode()).hexdigest(),
        input_hash=sha256(inputs.model_dump_json().encode()).hexdigest(),
        cutoff=cutoff,
        symbol=symbol,
        calendar_ok=health["CALENDAR"],
        news_ok=health["NEWS"],
        event_blackout=blackout,
        reasons=tuple(sorted(reasons)),
        optional_degradations=tuple(sorted(optional)),
        calendar_refs=tuple(refs),
        news_refs=news_refs,
    )


def restrict_market(market, policy, inputs, cutoff):
    """Apply fixture restrictions conservatively across all quoted instruments.

    The offline Market has global health flags, so one affected pair blocks all
    entries in this snapshot. Existing restrictions can never be relaxed here.
    """
    from fx_talanta.domain.offline import Market

    market = Market.model_validate(market.model_dump(mode="json"))
    if market.at != utc(cutoff):
        raise ValueError("market snapshot and filter cutoff must match")
    results = tuple(assess(policy, inputs, q.symbol, cutoff) for q in market.quotes)
    data = market.model_dump(mode="json")
    data.update(
        calendar_ok=market.calendar_ok and all(r.calendar_ok for r in results),
        news_ok=market.news_ok and all(r.news_ok for r in results),
        event_blackout=market.event_blackout or any(r.event_blackout for r in results),
    )
    return Market.model_validate(data), results


def main():
    import argparse
    from datetime import datetime
    from pathlib import Path

    parser = argparse.ArgumentParser(description="Evaluate fixture calendar/news restrictions")
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--symbol", choices=("EURUSD", "USDJPY"), required=True)
    parser.add_argument("--cutoff", required=True)
    parser.add_argument("--output", type=Path, help="create a new report; never overwrite")
    args = parser.parse_args()
    try:
        # Bound file reads before JSON/model construction.
        def read(path):
            with path.open("rb") as stream:
                data = stream.read(8 * 1024 * 1024 + 1)
            if len(data) > 8 * 1024 * 1024:
                raise ValueError("input exceeds size limit")
            return data

        result = assess(
            FilterPolicy.model_validate_json(read(args.policy)),
            FilterInputs.model_validate_json(read(args.inputs)),
            args.symbol,
            datetime.fromisoformat(args.cutoff),
        )
        if args.output:
            with args.output.open("x", encoding="utf-8") as stream:
                stream.write(result.model_dump_json(indent=2) + "\n")
        else:
            print(result.model_dump_json(indent=2))
    except (ValueError, OSError):
        parser.exit(2, "Invalid fixture evidence/configuration or inaccessible report path.\n")


if __name__ == "__main__":
    main()
