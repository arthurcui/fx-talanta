"""Explicit one-call OpenAI smoke using constructed evidence only; no broker access."""

import argparse
import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

from dotenv import dotenv_values

from fx_talanta.advisor.evidence import EvidenceQuery, ReadGrant, project
from fx_talanta.advisor.provider import OpenAITransport, run_once
from fx_talanta.domain.models import AccountIdentity, Record, RiskEvaluation


def fixture(now):
    account = AccountIdentity(
        environment="PAPER",
        broker="synthetic",
        server="offline",
        login="no-broker",
        venue="SIMULATOR",
    )
    record = Record(
        record_id=UUID("00000000-0000-0000-0000-000000000001"),
        account=account,
        recorded_at=now,
        correlation_id=UUID("00000000-0000-0000-0000-000000000002"),
        body=RiskEvaluation(
            approved=False,
            reasons=("Synthetic fixture; no orders",),
            checked_limits=("trading-disabled",),
            proposed_volume="0",
            planned_loss="0",
        ),
    )
    return project(
        (record,),
        ReadGrant(actor_id="offline-smoke", account=account, expires_at=now + timedelta(minutes=1)),
        EvidenceQuery(account=account, as_of=now, record_ids=(record.record_id,)),
        now=now,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--key-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    key = dotenv_values(args.key_file).get("OPENAI_API_KEY", "")
    transport = OpenAITransport(key)
    # Refuse to reuse a run directory: interrupted/reserved attempts are not refunded.
    args.output.mkdir(parents=True, exist_ok=False)
    now = datetime.now(UTC)
    result = run_once(
        fixture(now),
        "Which supplied record shows the recorded risk-check result?",
        args.output / "reservation.json",
        transport,
        expires_at=now + timedelta(seconds=30),
    )
    report = {
        "schema": "m4-provider-smoke/1",
        "source": "CONSTRUCTED_FIXTURE_ONLY",
        "adapter_sha256": hashlib.sha256(
            (Path(__file__).parents[2] / "src/fx_talanta/advisor/provider.py").read_bytes()
        ).hexdigest(),
        "result": result.model_dump(mode="json"),
        "max_external_calls": 1,
        "broker_calls": 0,
        "execution_enabled": False,
        "economic_acceptance": False,
        "m1_qualified": False,
        "b01_verdict": "REJECT_FOR_PROMOTION_UNCHANGED",
    }
    with (args.output / "result.json").open("x", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2)
        handle.write("\n")
    print(
        json.dumps(
            {
                "status": result.status,
                "reason": result.reason,
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
                "latency_ms": result.latency_ms,
                "execution_enabled": False,
            }
        )
    )


if __name__ == "__main__":
    main()
