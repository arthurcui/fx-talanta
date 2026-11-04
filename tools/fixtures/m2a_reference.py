"""Offline reference report and deterministic native-input export. No terminal access."""

import argparse
import csv
import hashlib
import json
from pathlib import Path

from fx_talanta.domain.ea_protocol import ChannelTelemetry, Envelope
from fx_talanta.execution_contracts.reference import RiskVector, calculate

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests/fixtures/ea_protocol"


def replay_cases(cases):
    seen, results = {}, []
    for c in cases:
        if c["version"] != "ea-protocol/1":
            result = "UNSUPPORTED"
        elif c["account"] != "fixture-usd":
            result = "ACCOUNT_MISMATCH"
        elif c["request"] in seen:
            digest, original = seen[c["request"]]
            result = (
                ("REPLAY" if original == "ACCEPTED" else "REPLAY_" + original)
                if digest == c["hash"]
                else "HASH_CONFLICT"
            )
        elif c["sequence"] != len(seen) + 1:
            result = "SEQUENCE_GAP"
        elif c["expires"] <= c["now"]:
            result = "EXPIRED"
            seen[c["request"]] = (c["hash"], result)
        else:
            result = "ACCEPTED"
            seen[c["request"]] = (c["hash"], result)
        results.append(
            {
                "id": c["id"],
                "actual": result,
                "expected": c["expected"],
                "pass": result == c["expected"],
            }
        )
    return results


def run(output):
    output.mkdir(parents=True, exist_ok=True)
    for schema in (Envelope, ChannelTelemetry):
        (output / (schema.__name__ + ".schema.json")).write_text(
            json.dumps(schema.model_json_schema(), indent=2) + "\n", encoding="utf-8"
        )
    vectors = json.loads((FIXTURES / "risk.json").read_text(encoding="utf-8"))
    risk_results = []
    with (output / "risk.tsv").open("w", newline="", encoding="ascii") as handle:
        writer = csv.writer(handle, delimiter="\t")
        writer.writerow(["id", *RiskVector.model_fields])
        for case in vectors["cases"]:
            v = RiskVector.model_validate(vectors["defaults"] | case["input"])
            actual = calculate(v)
            risk_results.append(
                {
                    "id": case["id"],
                    "actual": actual,
                    "expected": case["expected"],
                    "pass": actual == case["expected"],
                }
            )
            writer.writerow(
                [
                    case["id"],
                    *[
                        "" if x is None else int(x) if isinstance(x, bool) else x
                        for x in v.model_dump(mode="json").values()
                    ],
                ]
            )
    replay = json.loads((FIXTURES / "replay.json").read_text(encoding="utf-8"))["cases"]
    with (output / "replay.tsv").open("w", newline="", encoding="ascii") as handle:
        writer = csv.writer(handle, delimiter="\t")
        fields = ["id", "request", "hash", "sequence", "account", "version", "expires", "now"]
        writer.writerow(fields)
        writer.writerows([[c[f] for f in fields] for c in replay])
    results = risk_results + replay_cases(replay)
    sources = sorted((ROOT / "src/fx_talanta/execution_contracts").glob("*.py")) + [
        ROOT / "src/fx_talanta/domain/ea_protocol.py",
        Path(__file__),
        ROOT / "tests/native/offline/ProtocolReference.mq5",
        *sorted(FIXTURES.glob("*.json")),
    ]
    report = {
        "version": "m2a-reference-report/1",
        "native_compiler": "NOT_RUN",
        "native_parity": "NOT_QUALIFIED",
        "all_pass": all(r["pass"] for r in results),
        "results": results,
        "sha256": {
            p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sources
        },
    }
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / ".local/m2a-reference")
    args = parser.parse_args()
    report = run(args.output)
    print(
        json.dumps(
            {
                "all_pass": report["all_pass"],
                "cases": len(report["results"]),
                "native": report["native_compiler"],
            }
        )
    )
    raise SystemExit(0 if report["all_pass"] else 1)
