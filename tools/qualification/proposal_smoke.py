"""Explicit one-call proposal schema smoke with constructed input, never an order."""

import argparse
import json
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

from dotenv import dotenv_values

from fx_talanta.advisor.evidence import EvidenceAnswer
from fx_talanta.advisor.proposal_contracts import Candidate, ProposalInput
from fx_talanta.advisor.proposals import digest, parse, payload_for
from fx_talanta.advisor.provider import MODEL, OpenAITransport
from fx_talanta.domain.models import Environment
from fx_talanta.storage.config import fixture_account


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--key-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    now = datetime.now(UTC)
    candidate = Candidate.model_validate(
        {
            "candidate_id": str(UUID(int=1)),
            "strategy": "M4-synthetic/1",
            "symbol": "EURUSD",
            "side": "BUY",
            "stop": "1.0980",
            "benchmark": "1.1002",
            "exits": [{"name": "FIXED", "target": "1.1040", "maximum_holding_seconds": 30}],
        }
    )
    account = fixture_account(Environment.PAPER)
    request = ProposalInput(
        account=account,
        cutoff=now,
        quote_at=now,
        expires_at=now + timedelta(seconds=15),
        candidates=(candidate,),
    )
    evidence = EvidenceAnswer(
        account=account,
        actor_id="synthetic-probe",
        as_of=now,
        generated_at=now,
        citations=(),
        unavailable=(),
    )
    payload = payload_for(request, evidence)
    (args.output / "reservation.json").write_text(
        json.dumps(
            {
                "request_sha256": digest(payload),
                "max_calls": 1,
                "reserved_at": now.isoformat(),
                "no_retry": True,
            }
        ),
        encoding="utf-8",
    )
    report = {
        "schema": "m4-proposal-smoke/1",
        "source": "CONSTRUCTED_INPUT_ONLY",
        "model": MODEL,
        "request_sha256": digest(payload),
        "status": "HOLD",
        "reason": "PROVIDER_FAILURE",
        "broker_calls": 0,
        "trading_enabled": False,
        "economic_acceptance": False,
    }
    start = time.monotonic()
    try:
        transport = OpenAITransport(dotenv_values(args.key_file).get("OPENAI_API_KEY", ""))
        raw = transport(payload)
        elapsed = int((time.monotonic() - start) * 1000)
        selection, usage = parse(raw, request)
        age = (datetime.now(UTC) - request.quote_at).total_seconds()
        report.update(
            schema_valid=True,
            response_sha256=digest(raw),
            latency_ms=elapsed,
            original_quote_age_ms=int(age * 1000),
            input_tokens=usage["input_tokens"],
            output_tokens=usage["output_tokens"],
            selection=selection.model_dump(mode="json"),
            status=selection.action if 0 <= age <= 2 else "HOLD",
            reason=selection.reason if 0 <= age <= 2 else "EXPIRED_OR_STALE",
        )
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        report["schema_valid"] = False
    report["completed_at"] = datetime.now(UTC).isoformat()
    report["source_sha256"] = {
        p: digest((Path(__file__).parents[2] / p).read_bytes())
        for p in (
            "src/fx_talanta/advisor/proposals.py",
            "src/fx_talanta/advisor/proposal_contracts.py",
            "src/fx_talanta/advisor/provider.py",
            "tools/qualification/proposal_smoke.py",
        )
    }
    (args.output / "result.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("status", "reason", "schema_valid")}))


if __name__ == "__main__":
    main()
