"""Reproduce the offline M4 engineering suite and write a source-bound report.

No OpenAI credential, terminal or broker is used. Integration uses a fresh
namespace on the explicitly configured local/CI PostgreSQL service.
"""

import argparse
import hashlib
import json
import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
TESTS = tuple(sorted(ROOT.glob("tests/test_advisor*.py"))) + (
    ROOT / "tests/test_m4_consolidated.py",
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--integration", action="store_true")
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    # Unique evidence files; never replace a previous acceptance result.
    if args.output.exists():
        raise ValueError("acceptance output already exists")
    run = args.output.parent / ("m4-run-" + uuid4().hex)
    run.mkdir()
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "src") + os.pathsep + str(ROOT)
    env["FX_DB_NAMESPACE"] = "m4_eval_" + uuid4().hex[:12]
    command = [
        sys.executable,
        "-m",
        "pytest",
        *map(str, TESTS),
        "-q",
        "--junitxml=" + str(run / "results.xml"),
        "--basetemp=" + str(run / "tmp"),
    ]
    if args.integration:
        command.append("--integration")
    completed = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True)
    # Keep captured details private; public report carries case names/verdicts only.
    (run / "pytest.log").write_text(completed.stdout + completed.stderr, encoding="utf-8")
    cases = []
    if (run / "results.xml").exists():
        for case in ET.parse(run / "results.xml").iter("testcase"):
            status = (
                "FAIL"
                if case.find("failure") is not None or case.find("error") is not None
                else "SKIP"
                if case.find("skipped") is not None
                else "PASS"
            )
            cases.append(
                {"name": case.attrib["classname"] + "::" + case.attrib["name"], "status": status}
            )
    files = [
        *ROOT.glob("src/fx_talanta/advisor/*.py"),
        *TESTS,
        ROOT / "src/fx_talanta/gateway/offline.py",
        ROOT / "src/fx_talanta/risk/governor.py",
        ROOT / "src/fx_talanta/brokers/simulator.py",
        Path(__file__),
        *ROOT.glob("tests/fixtures/m4/*"),
    ]
    report = {
        "schema": "m4-engineering-acceptance/1",
        "scope": "OFFLINE_SIMULATOR_ONLY",
        "result": "PASS"
        if completed.returncode == 0
        and cases
        and args.integration
        and all(c["status"] == "PASS" for c in cases)
        else "INCOMPLETE_OR_FAILED",
        "integration": args.integration,
        "passed": sum(c["status"] == "PASS" for c in cases),
        "skipped": sum(c["status"] == "SKIP" for c in cases),
        "cases": cases,
        "source_sha256": {
            str(p.relative_to(ROOT)).replace("\\", "/"): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in files
        },
        "external_model_calls": 0,
        "broker_calls": 0,
        "trading_enabled": False,
        "economic_acceptance": False,
        "B01": "REJECT_FOR_PROMOTION",
        "M1_gaps_cleared": False,
    }
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("result", "passed", "skipped", "integration")}))
    return completed.returncode or (0 if report["result"] == "PASS" else 2)


if __name__ == "__main__":
    raise SystemExit(main())
