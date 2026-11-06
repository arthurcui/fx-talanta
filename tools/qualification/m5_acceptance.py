"""Reproduce the M5 offline inspection/evaluation acceptance; no broker or model calls."""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
TESTS = sorted(ROOT.glob("tests/test_dashboard*.py")) + [ROOT / "tests/test_m5_engineering.py"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.output.exists():
        raise ValueError("output already exists")
    run = args.output.parent.resolve() / ("m5-run-" + uuid4().hex)
    run.mkdir()
    env = dict(
        os.environ,
        PYTHONPATH=str(ROOT / "src") + os.pathsep + str(ROOT),
        FX_TEST_PYTHON=sys.executable,
        FX_DASHBOARD_REPORT=str(run / "browser.json"),
    )
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            *map(str, TESTS),
            "-q",
            "--junitxml=" + str(run / "pytest.xml"),
            "--basetemp=" + str(run / "tmp"),
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    (run / "pytest.log").write_text(result.stdout + result.stderr, encoding="utf-8")
    cases = []
    if (run / "pytest.xml").exists():
        for c in ET.parse(run / "pytest.xml").iter("testcase"):
            cases.append(
                dict(
                    name=c.attrib["classname"] + "::" + c.attrib["name"],
                    result="FAIL"
                    if c.find("failure") is not None or c.find("error") is not None
                    else "SKIP"
                    if c.find("skipped") is not None
                    else "PASS",
                )
            )
    browser_dir = ROOT / "tools/dashboard-tests"
    node = shutil.which("node")
    cli = browser_dir / "node_modules/@playwright/test/cli.js"
    browser_code = None
    if node and cli.exists():
        browser = subprocess.run(
            [node, str(cli), "test"], cwd=browser_dir, env=env, capture_output=True, text=True
        )
        browser_code = browser.returncode
        (run / "browser.log").write_text(browser.stdout + browser.stderr, encoding="utf-8")
    stats = {}
    if (run / "browser.json").exists():
        stats = json.loads((run / "browser.json").read_text(encoding="utf-8")).get("stats", {})
    passed = (
        result.returncode == 0
        and cases
        and all(c["result"] == "PASS" for c in cases)
        and browser_code == 0
        and stats.get("expected", 0) >= 2
        and all(stats.get(k) == 0 for k in ("unexpected", "skipped", "flaky"))
    )
    files = [
        *ROOT.glob("src/fx_talanta/**/*.py"),
        *ROOT.glob("src/fx_talanta/dashboard/static/*"),
        *TESTS,
        *browser_dir.glob("*.js"),
        *browser_dir.glob("*.py"),
        browser_dir / "package.json",
        browser_dir / "package-lock.json",
        ROOT / "tests/test_bls_calendar.py",
        ROOT / "tests/test_mt5.py",
        ROOT / "tools/qualification/current_broker_capture.py",
        ROOT / "tools/qualification/inspection_quote_clock.py",
        ROOT / "tools/qualification/verified_quote_acceptance.py",
        ROOT / "tools/qualification/paper_runner_acceptance.py",
        ROOT / "tools/qualification/runner_operations_acceptance.py",
        ROOT / "tools/qualification/runner_recovery_acceptance.py",
        ROOT / "tools/fixtures/b01_replay.py",
        ROOT / "src/fx_talanta/advisor/evidence.py",
        Path(__file__),
    ]
    report = dict(
        schema="m5-offline-acceptance/1",
        scope="LOCAL_INSPECTION_AND_OFFLINE_EVALUATION",
        result="PASS" if passed else "INCOMPLETE_OR_FAILED",
        cases=cases,
        backend_passed=sum(c["result"] == "PASS" for c in cases),
        browser_stats=stats,
        source_sha256={
            p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in files
        },
        broker_calls=0,
        external_model_calls=0,
        trading_enabled=False,
        full_M5_complete=False,
        unattended_paper_qualified=False,
        B01="REJECT_FOR_PROMOTION",
        remaining=[
            "Complete connected fault and broker administrative acceptance",
            "Actual remote deployment, certificate lifecycle and external alert delivery",
            "M1-M3 prerequisites and prospective matched candidate evaluation",
            "At least eight weeks AND 100 closed trades per candidate",
        ],
    )
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2)
        stream.write("\n")
    print(
        json.dumps(
            {
                k: report[k]
                for k in ("result", "backend_passed", "browser_stats", "full_M5_complete")
            }
        )
    )
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
