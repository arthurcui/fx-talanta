"""Repeatable M0A acceptance scenario, clearly labeled synthetic evidence."""

from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import UUID, uuid5

from fx_talanta.brokers.protocol import FixtureBroker
from fx_talanta.clock import FakeClock
from fx_talanta.domain.models import (
    Environment,
    EvidenceLink,
    ExecutionEvent,
    ExperienceCase,
    Lesson,
    NewsRevision,
    PromotionEvidence,
    Record,
    RiskEvaluation,
    SourceHealth,
    StrategyArtifact,
)
from fx_talanta.research.advisor import record_chat
from fx_talanta.research.decisions import ScriptedDecisionSource, record_attempt, response
from fx_talanta.storage.config import fixture_account
from fx_talanta.storage.repository import Repository

START = datetime(2026, 1, 5, 12, tzinfo=UTC)


def run_demo(repo: Repository, run_id: UUID) -> dict:
    if repo.account.environment != Environment.PAPER or repo.account.venue != "SIMULATOR":
        raise ValueError("demo accepts only the PAPER simulator binding")
    clock = FakeClock(START)

    def record(label, body, *, refs=(), supersedes=None):
        return Record(
            record_id=uuid5(run_id, label),
            account=repo.account,
            recorded_at=clock.now(),
            correlation_id=run_id,
            body=body,
            references=refs,
            supersedes=supersedes,
        )

    def news(label, *, revision=1, supersedes=None, observed=None):
        text = f"Synthetic {label} revision {revision}; no real market claim"
        observed = observed or clock.now()
        return record(
            label,
            NewsRevision(
                source="fixture-news",
                item_id=f"{run_id}/story",
                revision=revision,
                url="https://example.com/synthetic-news",
                headline=text,
                content_excerpt=text,
                content_hash=sha256(text.encode()).hexdigest(),
                story_cluster=str(run_id),
                currencies=("USD",),
                published_at=START - timedelta(days=1),
                first_observed_at=observed,
                ingested_at=observed,
                available_at=observed,
            ),
            supersedes=supersedes,
        )

    original = news("news-original")
    health = record(
        "health",
        SourceHealth(
            source="fixture-news",
            checked_at=START,
            last_success_at=START,
            connection="OK",
            coverage="CURRENT",
            required=True,
            reason="Scripted healthy fixture",
        ),
    )
    repo.append_batch((original, health))
    attempts = {}
    for label, raw in (
        ("valid", response(repo.account, START + timedelta(seconds=60))),
        ("hold", response(repo.account, START + timedelta(seconds=60), action="HOLD")),
        ("malformed", '{"action":"TRADE_EVERYTHING"}'),
        ("expired", response(repo.account, START)),
        (
            "wrong-account",
            response(fixture_account(Environment.LIVE), START + timedelta(seconds=60)),
        ),
    ):
        attempts[label] = record_attempt(
            repo, ScriptedDecisionSource((raw,)), clock, run_id, label, (original.record_id,)
        )

    decision_ref = EvidenceLink(record_id=attempts["valid"].record_id, relation="DECISION")
    repo.append(
        record(
            "risk",
            RiskEvaluation(
                approved=True,
                reasons=("Scripted approval; sizing/reservations wait for M0B",),
                checked_limits=("fixture-only",),
                proposed_volume="0.01",
                planned_loss="1.00",
            ),
            refs=(decision_ref,),
        )
    )
    request_id = uuid5(run_id, "broker-request")
    broker = FixtureBroker(
        repo.account,
        (
            ExecutionEvent(
                request_id=request_id,
                state="OUTCOME_UNKNOWN",
                evidence="Recorded lost-response fixture; no send was performed",
            ),
            ExecutionEvent(
                request_id=request_id,
                state="FILLED",
                order_id="fixture-order-1",
                deal_id="fixture-deal-1",
                position_id="fixture-position-1",
                filled_volume="0.01",
                fill_price="1.10000",
                evidence="Recorded reconciliation observation; synthetic fill, still open",
            ),
        ),
    )
    unknown = record("unknown", broker.observe(), refs=(decision_ref,))
    unresolved = record(
        "unknown-case",
        ExperienceCase(
            operational_result="UNKNOWN",
            policy_compliance="COMPLIANT",
            economic_outcome="UNKNOWN",
            summary="Unresolved synthetic execution; no failure or profit inferred",
        ),
        refs=(EvidenceLink(record_id=unknown.record_id, relation="EXECUTION"),),
    )
    repo.append_batch((unknown, unresolved))
    rejected = record(
        "execution-rejected",
        ExecutionEvent(
            request_id=uuid5(run_id, "rejected-request"),
            state="REJECTED",
            evidence="Scripted broker rejection; no send was performed",
        ),
        refs=(decision_ref,),
    )
    repo.append_batch(
        (
            rejected,
            record(
                "rejected-case",
                ExperienceCase(
                    operational_result="FAILED",
                    policy_compliance="COMPLIANT",
                    economic_outcome="NOT_APPLICABLE",
                    outcome_known_at=clock.now(),
                    summary="Synthetic rejected execution retained",
                ),
                refs=(EvidenceLink(record_id=rejected.record_id, relation="EXECUTION"),),
            ),
        )
    )
    for label, text, language in (
        ("chat-read", "What is PAPER status?", "en"),
        ("chat-ambiguous", "Pause entries", "en"),
        ("chat-negated", "Do not pause PAPER entries", "en"),
        ("chat-pause", "Pause PAPER entries", "en"),
        ("chat-zh", "暂停 PAPER 开仓", "zh"),
    ):
        record_chat(repo, clock, run_id, label, text, language=language)
    clock.advance(timedelta(seconds=5))
    # Old publication, later first observation: unavailable to START decisions.
    late = news("news-late", revision=2, supersedes=original.record_id)
    repo.append(late)
    clock.advance(timedelta(seconds=5))
    corrected = news("news-corrected", revision=3, supersedes=late.record_id)
    repo.append(corrected)
    clock.advance(timedelta(seconds=20))
    reconciled = record(
        "reconciled",
        broker.observe(),
        refs=(EvidenceLink(record_id=unknown.record_id, relation="EXECUTION"),),
    )
    recovered = record(
        "recovered-case",
        ExperienceCase(
            operational_result="RECOVERED",
            policy_compliance="COMPLIANT",
            economic_outcome="UNKNOWN",
            outcome_known_at=clock.now(),
            summary="Fill discovered in fixture; open position P&L remains unknown",
        ),
        supersedes=unresolved.record_id,
        refs=(EvidenceLink(record_id=reconciled.record_id, relation="EXECUTION"),),
    )
    repo.append_batch((reconciled, recovered))
    lesson = record(
        "lesson",
        Lesson(
            hypothesis="Reconcile an uncertain request before considering another attempt",
            status="PROPOSED",
            supporting_cases=(recovered.record_id,),
            sample_size=1,
            uncertainty="One scripted case is engineering evidence, not strategy qualification",
        ),
        refs=(EvidenceLink(record_id=recovered.record_id, relation="CASE"),),
    )
    digest = sha256(b"synthetic-artifact-v1").hexdigest()
    artifact = record(
        "artifact",
        StrategyArtifact(
            artifact_hash=digest,
            code_hash=digest,
            configuration_hash=digest,
            feature_version="fixture/1",
            news_policy_version="fixture/1",
            interpretation_version="fixture/1",
        ),
    )
    promotion = record(
        "promotion",
        PromotionEvidence(
            artifact_hash=digest,
            engineering_passed=False,
            strategy_evidence_passed=False,
            paper_observation_complete=False,
            result="RECORDED_ONLY",
            reason="M0A records the contract only; activation is disabled",
        ),
        refs=(EvidenceLink(record_id=artifact.record_id, relation="ARTIFACT"),),
    )
    repo.append_batch((lesson, artifact, promotion))
    history = repo.history(correlation_id=run_id)
    return {
        "run_id": str(run_id),
        "environment": "PAPER",
        "venue": "SIMULATOR",
        "records": len(history),
        "decision_results": [a.body.result for a in attempts.values()],
        "news_versions": [str(original.record_id), str(late.record_id), str(corrected.record_id)],
        "unknown_case": str(unresolved.record_id),
        "recovered_case": str(recovered.record_id),
        "commands_recorded": sum(r.body.kind == "command" for r in history),
        "broker_mutations": 0,
        "live_enabled": False,
    }
