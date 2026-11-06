"""Bounded synthetic backup/inspection recovery; no campaign or external calls."""

import argparse
import json
from datetime import datetime
from pathlib import Path

from fx_talanta.clock import FakeClock
from fx_talanta.evaluation.archive import capture, restore
from tools.qualification.runner_operations_acceptance import run


def exercise(destination):
    destination = Path(destination)
    baseline = run(destination / "simulation")
    report = baseline["report"]
    clock = FakeClock(datetime.fromisoformat(report["runner"]["last_input_at"]))
    receipt = capture(
        destination / "simulation/source.sqlite",
        report["binding_hash"],
        destination / "archive",
        clock,
    )
    verified = restore(
        destination / "archive", receipt["manifest_hash"], destination / "inspection"
    )
    result = dict(
        schema="runner-recovery-synthetic/1",
        result=baseline["result"],
        archive=verified,
        broker_calls=0,
        external_model_calls=0,
        trading_enabled=False,
        campaign_started=False,
        full_M5_complete=False,
    )
    (destination / "report.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    result = exercise(parser.parse_args().output)
    print(json.dumps(dict(result=result["result"], inspection_only=True, trading_enabled=False)))
    if result["result"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
