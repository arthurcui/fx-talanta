"""Small constructed tour, never presented as live account or strategy performance."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid5

from fx_talanta.dashboard.models import Channel, Snapshot
from fx_talanta.domain.models import (
    AccountIdentity,
    Decision,
    DecisionAttempt,
    EvidenceLink,
    ExperienceCase,
    ModelTrace,
    Record,
    RiskEvaluation,
    SourceHealth,
)

AT = datetime(2026, 11, 5, 17, tzinfo=UTC)
SEED = UUID("af6bc59e-642c-428e-b0b7-ab3d91077d44")


def demo():
    account = AccountIdentity(
        environment="PAPER",
        venue="SIMULATOR",
        broker="fixture",
        server="offline",
        login="demo-view",
    )
    decision = Record(
        record_id=uuid5(SEED, "decision"),
        account=account,
        recorded_at=AT,
        correlation_id=SEED,
        body=DecisionAttempt(
            result="HOLD",
            action="HOLD",
            cutoff=AT,
            input_snapshot="a" * 64,
            candidates=(),
            response='{"action":"HOLD"}',
            decision=Decision(
                account=account,
                action="HOLD",
                expires_at=AT + timedelta(minutes=1),
                rationale="Constructed example: incomplete news coverage; no entry proposed.",
            ),
            reason="NEWS_COVERAGE_INCOMPLETE",
            trace=ModelTrace(
                provider="fixture",
                requested_model="none",
                returned_model="none",
                request_id=uuid5(SEED, "model"),
                latency_ms=0,
            ),
        ),
    )
    risk = Record(
        record_id=uuid5(SEED, "risk"),
        account=account,
        recorded_at=AT,
        correlation_id=SEED,
        references=(EvidenceLink(record_id=decision.record_id, relation="DECISION"),),
        body=RiskEvaluation(
            approved=False,
            reasons=("Trading disabled", "Required news coverage incomplete"),
            checked_limits=("two-second-entry", "read-only-mode"),
            proposed_volume="0",
            planned_loss="0",
        ),
    )
    case = Record(
        record_id=uuid5(SEED, "case"),
        account=account,
        recorded_at=AT,
        correlation_id=SEED,
        references=(EvidenceLink(record_id=decision.record_id, relation="DECISION"),),
        body=ExperienceCase(
            operational_result="HOLD",
            policy_compliance="COMPLIANT",
            economic_outcome="NOT_APPLICABLE",
            outcome_known_at=AT,
            summary="Constructed HOLD; no order or P&L.",
        ),
    )
    health = Record(
        record_id=uuid5(SEED, "health"),
        account=account,
        recorded_at=AT,
        correlation_id=SEED,
        body=SourceHealth(
            source="fixture-news",
            checked_at=AT,
            connection="OK",
            last_success_at=AT,
            coverage="INCOMPLETE",
            required=True,
            reason="Constructed coverage gap",
        ),
    )
    return Snapshot(
        label="Offline workspace",
        source="SYNTHETIC",
        captured_at=AT,
        account=account,
        records=(decision, risk, case, health),
        channels=(
            Channel(
                name="EA",
                connection="CONNECTED",
                observed_at=AT,
                quote_at=AT - timedelta(milliseconds=450),
                received_at=AT - timedelta(milliseconds=420),
                clock_uncertainty_ms=12,
                symbol="EURUSD",
            ),
            Channel(
                name="Python",
                connection="CONNECTED",
                observed_at=AT,
                quote_at=AT - timedelta(seconds=8),
                received_at=AT - timedelta(seconds=7.8),
                clock_uncertainty_ms=12,
                symbol="EURUSD",
            ),
            Channel(name="MCP"),
        ),
    )
