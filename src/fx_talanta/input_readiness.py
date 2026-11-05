"""Read-only M1 evidence summary. No fetches, SDK, database or trading authority."""

import argparse
import json
from hashlib import sha256
from pathlib import Path


def report(repository):
    root = Path(repository)
    hashes = {}

    def read(relative):
        raw = (root / relative).read_bytes()
        if len(raw) > 2 * 1024 * 1024:
            raise ValueError("evidence size bound")
        hashes[relative] = sha256(raw).hexdigest()
        return json.loads(raw)

    inventory = read("docs/provider-inventory.json")
    brokers = read("docs/evidence/broker-campaign-final-20261103.json")
    providers = read("docs/evidence/provider-campaign-final-20261103.json")
    closeout = read("docs/evidence/m2-one-entry-closeout-20261105-02.json")
    requirements = inventory["requirements"]
    if len({r["id"] for r in requirements}) != len(requirements):
        raise ValueError("duplicate required group")
    if set(inventory["currencies"]) != {"USD", "EUR", "JPY"}:
        raise ValueError("required currency scope changed")
    return {
        "schema": "m1-evidence-summary/1",
        "basis": "Committed historical evidence; not a live terminal or feed status",
        "evidence_hashes": hashes,
        "brokers": {
            name: {
                "run_id": row["run_id"],
                "phase": row["phase"],
                "collector_accepted": row["evidence"]["collector_accepted"],
                "quote_readiness_accepted": row["evidence"]["quote_readiness_accepted"],
                "completion_receipt_present": row["completion_receipt_present"],
            }
            for name, row in brokers.items()
            if name in {"cmc", "forex"}
        },
        "provider_campaign": {
            "phase": providers["phase"],
            "sources": providers["sources"],
            "scheduled_release_checks": providers["independent_scheduled_release_checks"],
            "coverage_qualified": providers["coverage_qualified"],
        },
        "required_groups": [
            {
                "id": row["id"],
                "families": row["families"],
                "remaining_gap": row["gap"],
                "qualified": False,
            }
            for row in requirements
        ],
        "bounded_m2_closeout_verified": closeout["bounded_closeout_passed"],
        "restrictions": [
            "Strategy trading remains disabled; this report cannot authorize entry.",
            "Connection health does not establish quote freshness or clock validity.",
            "Two-second entry ceiling and five-second observer ceiling are unchanged.",
            "A calendar import does not qualify release delivery or source coverage.",
            "Missing/stale/uncertain required inputs block strategy readiness.",
            "M2 closeout success does not change historical M1 verdicts.",
        ],
        "m1_qualified": False,
        "execution_enabled": False,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        result = report(args.repository)
        text = json.dumps(result, indent=2) + "\n"
        if args.output:
            with args.output.open("x", encoding="utf-8") as stream:
                stream.write(text)
        print(text)
        return 0  # Successful report generation, explicitly not acceptance.
    except (OSError, ValueError, KeyError, TypeError):
        print("M1 evidence unavailable or invalid; readiness cannot be established.")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
