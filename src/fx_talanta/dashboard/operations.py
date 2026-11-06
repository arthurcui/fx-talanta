"""Historical operating summary, deliberately not an account balance or trade ledger."""

from collections import Counter

GATES = (
    ("M1", "Broker and USD/EUR/JPY provider qualification", "OPEN"),
    ("M2", "Complete connected execution fault matrix", "OPEN"),
    ("M3", "Cost/source qualification and promoted strategy", "OPEN; B01 REJECT_FOR_PROMOTION"),
    ("M5-CONNECTED", "Connected collectors and account-scoped administration", "NOT ENABLED"),
    ("M5-REMOTE", "Remote authentication/TLS and deployment acceptance", "NOT IMPLEMENTED"),
    ("M5-EVALUATION", "Prospective matched AI/no-AI and news/no-news evidence", "NOT QUALIFIED"),
    ("M5-DURATION", "At least eight weeks AND 100 closed trades per candidate", "NOT QUALIFIED"),
)


def summary(snapshot):
    records = snapshot.records
    decisions = [r for r in records if r.body.kind == "decision"]
    cases = [r for r in records if r.body.kind == "experience"]
    # Record versions are audit evidence, not independent economic samples.
    known = [
        r
        for r in cases
        if r.body.outcome_known_at is not None and r.body.outcome_known_at <= snapshot.captured_at
    ]
    unknown = [r for r in cases if r not in known]
    requests = {}
    conflicts = set()
    for r in decisions:
        trace = r.body.trace
        key = trace.request_id
        if key in requests and requests[key] != trace:
            conflicts.add(key)
        requests[key] = trace
    usage = [value for key, value in requests.items() if key not in conflicts]
    return dict(
        scope="RECORD_VERSIONS_AT_CUTOFF_NOT_TRADE_PERFORMANCE",
        cutoff=snapshot.captured_at.isoformat(),
        record_versions=len(records),
        corrections=sum(r.supersedes is not None for r in records),
        decisions=dict(Counter(r.body.result for r in decisions)),
        operational_outcomes=dict(Counter(r.body.operational_result for r in cases)),
        compliance=dict(Counter(r.body.policy_compliance for r in cases)),
        known_economic_labels=dict(Counter(r.body.economic_outcome for r in known)),
        economics_unavailable=len(unknown),
        model_usage=dict(
            distinct_requests=len(requests),
            conflicting_requests=len(conflicts),
            counted_requests=len(usage),
            input_tokens=sum(t.input_tokens for t in usage),
            output_tokens=sum(t.output_tokens for t in usage),
            max_latency_ms=max((t.latency_ms for t in usage), default=None),
            scope="RECORDED_TRACES_INCLUDING_FIXTURES_NOT_BILLING",
        ),
        account_metrics={
            k: None for k in ("equity", "net_pnl", "drawdown", "exposure", "open_positions")
        },
        account_metrics_reason=(
            "No authoritative current account reconciliation or complete cash-flow ledger"
        ),
        gates=[
            dict(id=code, requirement=requirement, status=status)
            for code, requirement, status in GATES
        ],
        qualified_for_unattended_paper=False,
        execution_enabled=False,
    )
