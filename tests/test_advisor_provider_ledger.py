import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest

from fx_talanta.advisor.provider import MODEL
from fx_talanta.advisor.provider_ledger import ProviderBudget, ProviderLedger, explain
from fx_talanta.storage.repository import RecordConflict
from tools.qualification.provider_smoke import fixture

NOW = datetime(2026, 11, 6, tzinfo=UTC)
BUDGET = ProviderBudget(
    max_calls=3,
    reserve_per_call_usd="0.01",
    total_reserved_usd="0.03",
    basis="Test reserve, not billing",
)


def raw(e):
    return json.dumps(
        {
            "status": "completed",
            "model": MODEL,
            "usage": {"input_tokens": 200, "output_tokens": 50},
            "output": [
                {
                    "type": "message",
                    "content": [
                        {
                            "type": "output_text",
                            "text": json.dumps(
                                {
                                    "decision": "EXPLAIN",
                                    "reason": "EVIDENCE_SELECTED",
                                    "citation_ids": [str(e.citations[0].record_id)],
                                }
                            ),
                        }
                    ],
                }
            ],
        }
    ).encode()


class MemoryLedger:
    def __init__(self, evidence):
        self.repository = SimpleNamespace(account=evidence.account)
        self.started = False
        self.result = None
        self.fail_commit = False

    def begin(self, *args):
        if self.started:
            return False, self.result, "OUTCOME_UNKNOWN_NO_RESEND"
        self.started = True
        return True, None, "RESERVED"

    def finish(self, request_id, identity, result):
        if self.fail_commit:
            raise OSError("commit failed")
        self.result = result.model_dump(mode="json")


def invoke(ledger, evidence, transport, request_id=None, **kwargs):
    return explain(
        ledger,
        evidence,
        "Which record?",
        request_id or uuid4(),
        BUDGET,
        transport,
        expires_at=NOW + timedelta(seconds=10),
        now=lambda: NOW,
        **kwargs,
    )


def test_commit_failure_and_restart_never_resend():
    e = fixture(NOW)
    ledger = MemoryLedger(e)
    ledger.fail_commit = True
    calls = []

    def transport(payload):
        calls.append(payload)
        return raw(e)

    with pytest.raises(OSError):
        invoke(ledger, e, transport)
    ledger.fail_commit = False
    assert invoke(ledger, e, transport).reason == "OUTCOME_UNKNOWN_NO_RESEND"
    assert len(calls) == 1


@pytest.mark.parametrize("failure", [OSError("secret"), ValueError("secret")])
def test_provider_failure_is_sanitized_and_retained(failure):
    e = fixture(NOW)
    ledger = MemoryLedger(e)

    def transport(payload):
        raise failure

    result = invoke(ledger, e, transport)
    assert result.reason == "PROVIDER_FAILURE_HOLD"
    assert "secret" not in result.model_dump_json()
    assert invoke(ledger, e, transport) == result


def test_expired_and_cross_account_never_reserve():
    e = fixture(NOW + timedelta(seconds=1))
    ledger = MemoryLedger(e)
    assert invoke(ledger, e, lambda _: pytest.fail("network")).reason == "EXPIRED"
    assert not ledger.started
    ledger.repository.account = None
    with pytest.raises(PermissionError):
        invoke(ledger, e, lambda _: pytest.fail("network"))


def test_late_response_is_not_explanation():
    e = fixture(NOW)
    times = iter([0, 16])
    result = invoke(MemoryLedger(e), e, lambda _: raw(e), monotonic=lambda: next(times))
    assert result.status == "HOLD" and result.reason == "EXPIRED"


@pytest.mark.parametrize(
    "changes", [{"max_calls": True}, {"reserve_per_call_usd": "0"}, {"total_reserved_usd": "-1"}]
)
def test_invalid_budget(changes):
    with pytest.raises(ValueError):
        ProviderBudget.model_validate(BUDGET.model_dump() | changes)


@pytest.mark.integration
def test_postgres_budget_concurrency_restarts_and_immutability(repo):
    e = fixture(NOW).model_copy(update={"account": repo.account})
    ledger = ProviderLedger(repo)
    rid = uuid4()
    calls = []

    def transport(payload):
        calls.append(payload)
        return raw(e)

    first = invoke(ledger, e, transport, rid)
    assert first.status == "EXPLAIN"
    assert invoke(ProviderLedger(repo), e, transport, rid) == first
    assert len(calls) == 1
    with pytest.raises(RecordConflict):
        explain(
            ledger,
            e,
            "Changed question",
            rid,
            BUDGET,
            transport,
            expires_at=NOW + timedelta(seconds=10),
            now=lambda: NOW,
        )
    identity = {
        "request_sha256": "a" * 64,
        "evidence_sha256": "b" * 64,
        "expires_at": (NOW + timedelta(seconds=10)).isoformat(),
    }
    crashed = uuid4()
    assert ledger.begin(crashed, identity, BUDGET, NOW)[0]
    assert ProviderLedger(repo).begin(crashed, identity, BUDGET, NOW) == (
        False,
        None,
        "OUTCOME_UNKNOWN_NO_RESEND",
    )
    # Two independent connections compete for the last reserved call.
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _: invoke(ProviderLedger(repo), e, transport), range(2)))
    assert sorted(r.status for r in outcomes) == ["EXPLAIN", "HOLD"]
    assert next(r for r in outcomes if r.status == "HOLD").reason == "BUDGET_EXHAUSTED"
    assert len(calls) == 2
    assert invoke(ledger, e, transport).reason == "BUDGET_EXHAUSTED"
    with pytest.raises(RecordConflict):
        ledger.begin(uuid4(), identity, BUDGET.model_copy(update={"max_calls": 4}), NOW)
