"""Validate and compare frozen matched offline arms; never qualify or launch PAPER."""

import argparse
import hashlib
import json
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, model_validator

from fx_talanta.domain.models import Amount, FrozenModel, Hash, Identifier, NonNegative, Timestamp

ARM_NAMES = ("NO_AI", "AI_NO_NEWS", "AI_NEWS")


class Arm(FrozenModel):
    name: Literal["NO_AI", "AI_NO_NEWS", "AI_NEWS"]
    ledger: Identifier
    policy_hash: Hash
    safety_hash: Hash
    model_hash: Hash | None = None
    prompt_hash: Hash | None = None
    news_content: bool


class Sample(FrozenModel):
    snapshot_hash: Hash
    snapshot_at: Timestamp
    arm: Literal["NO_AI", "AI_NO_NEWS", "AI_NEWS"]
    decision_id: UUID
    decision_at: Timestamp
    outcome_at: Timestamp | None = None
    gross_pnl: Amount | None = None
    cost: NonNegative | None = None
    latency_ms: Annotated[int, Field(strict=True, ge=0)]
    missed_entry: bool
    currency: Literal["USD"] = "USD"

    @model_validator(mode="after")
    def timing(self):
        if self.decision_at < self.snapshot_at:
            raise ValueError("decision before snapshot")
        if self.outcome_at is not None and self.outcome_at <= self.decision_at:
            raise ValueError("outcome must follow decision")
        if self.gross_pnl is not None and self.outcome_at is None:
            raise ValueError("P&L requires outcome time")
        return self


class Study(FrozenModel):
    schema_version: Literal["matched-offline-study/1"] = "matched-offline-study/1"
    provenance: Literal["SYNTHETIC", "RECORDED_OFFLINE"]
    candidate_hash: Hash
    dataset_hash: Hash
    criteria_hash: Hash
    feature_hash: Hash
    lessons_hash: Hash
    news_interpretation_hash: Hash
    frozen_at: Timestamp
    cutoff: Timestamp
    arms: Annotated[tuple[Arm, ...], Field(min_length=3, max_length=3)]
    samples: Annotated[tuple[Sample, ...], Field(min_length=1, max_length=30000)]
    execution_enabled: Literal[False] = False

    @model_validator(mode="after")
    def matched(self):
        if self.frozen_at > self.cutoff:
            raise ValueError("future freeze")
        index = {a.name: a for a in self.arms}
        if set(index) != set(ARM_NAMES) or len({a.ledger for a in self.arms}) != 3:
            raise ValueError("three separate named arm ledgers required")
        if len({a.safety_hash for a in self.arms}) != 1:
            raise ValueError("all arms must preserve common safety inputs")
        baseline, no_news, news = (index[name] for name in ARM_NAMES)
        if baseline.model_hash or baseline.prompt_hash or baseline.news_content:
            raise ValueError("baseline must not use AI or news content")
        if no_news.news_content or not news.news_content:
            raise ValueError("news-content contrast invalid")
        if (
            not no_news.model_hash
            or not no_news.prompt_hash
            or (no_news.policy_hash, no_news.model_hash, no_news.prompt_hash)
            != (news.policy_hash, news.model_hash, news.prompt_hash)
        ):
            raise ValueError("AI arms must share frozen policy/model/prompt")
        ids, keys, times = set(), set(), {}
        for s in self.samples:
            key = (s.snapshot_hash, s.arm)
            if key in keys or s.decision_id in ids:
                raise ValueError("duplicate arm sample or decision")
            keys.add(key)
            ids.add(s.decision_id)
            if not self.frozen_at <= s.snapshot_at <= s.decision_at <= self.cutoff:
                raise ValueError("sample outside frozen study cutoff")
            if s.snapshot_hash in times and times[s.snapshot_hash] != s.snapshot_at:
                raise ValueError("same snapshot has conflicting observation time")
            times[s.snapshot_hash] = s.snapshot_at
        groups = {}
        for sample in self.samples:
            groups.setdefault(sample.snapshot_hash, []).append(sample)
        for group in groups.values():
            outcomes = [s.outcome_at for s in group if s.outcome_at is not None]
            if outcomes and max(s.decision_at for s in group) >= min(outcomes):
                raise ValueError("all matched decisions must precede every known outcome")
        return self


def evaluate(study):
    study = Study.model_validate(study.model_dump(mode="json"))
    groups = {}
    for s in study.samples:
        groups.setdefault(s.snapshot_hash, {})[s.arm] = s

    def net(s):
        if s is None or s.outcome_at is None or s.outcome_at > study.cutoff:
            return None
        if s.gross_pnl is None or s.cost is None:
            return None
        return s.gross_pnl - s.cost

    comparisons = []
    for left, right in (("AI_NO_NEWS", "NO_AI"), ("AI_NEWS", "AI_NO_NEWS")):
        pairs = []
        for group in groups.values():
            a, b = net(group.get(left)), net(group.get(right))
            if a is not None and b is not None:
                pairs.append(a - b)
        n = len(pairs)
        mean = sum(pairs, Decimal(0)) / n if n else None
        comparisons.append(
            dict(
                left=left,
                right=right,
                complete_pairs=n,
                excluded_pairs=len(groups) - n,
                mean_net_difference_usd=str(mean) if mean is not None else None,
                minimum_difference_usd=str(min(pairs)) if n else None,
                maximum_difference_usd=str(max(pairs)) if n else None,
                uncertainty=(
                    "NOT_ESTIMATED; dependence and small samples require predeclared analysis"
                ),
            )
        )
    return dict(
        schema_version="matched-offline-report/1",
        provenance=study.provenance,
        study_sha256=hashlib.sha256(study.model_dump_json().encode()).hexdigest(),
        candidate_hash=study.candidate_hash,
        cutoff=study.cutoff.isoformat(),
        snapshots=len(groups),
        samples=len(study.samples),
        comparisons=comparisons,
        arms=[
            dict(
                name=name,
                observations=sum(s.arm == name for s in study.samples),
                missed_entries=sum(s.arm == name and s.missed_entry for s in study.samples),
                unknown_net_outcomes=sum(s.arm == name and net(s) is None for s in study.samples),
                max_latency_ms=max(
                    (s.latency_ms for s in study.samples if s.arm == name), default=None
                ),
            )
            for name in ARM_NAMES
        ],
        result="DESCRIPTIVE_OFFLINE_ONLY",
        execution_enabled=False,
        prospective_evidence_verified=False,
        qualified_for_unattended_paper=False,
        minimum_paper_weeks=8,
        minimum_closed_trades=100,
        limitations=[
            "Input metadata is not independently verified delivery evidence",
            "No broker closed-trade count or sustained coverage inferred",
            "Missing costs/outcomes excluded, never imputed as zero",
            "M1-M3 gaps and B01 rejection remain unchanged",
        ],
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    with args.input.open("rb") as stream:
        raw = stream.read(16 * 1024 * 1024 + 1)
    if len(raw) > 16 * 1024 * 1024:
        raise ValueError("study exceeds 16 MiB")
    result = evaluate(Study.model_validate_json(raw))
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2)
        stream.write("\n")
    print("DESCRIPTIVE_OFFLINE_ONLY; trading disabled; no qualification inferred")


if __name__ == "__main__":
    main()
