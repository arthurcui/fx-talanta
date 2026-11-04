"""Export fixture inputs, then independently compare actual native outputs."""

import argparse
import csv
import hashlib
import hmac
import json
from decimal import Decimal
from pathlib import Path

from fx_talanta.safety.risk import SafetyInput, evaluate

ROOT = Path(__file__).resolve().parents[2]


def cases():
    source = json.loads((ROOT / "tests/fixtures/safety/risk.json").read_text())
    return [
        (c, SafetyInput.model_validate(source["defaults"] | c["input"])) for c in source["cases"]
    ]


def export(destination):
    with destination.open("w", newline="", encoding="ascii") as f:
        writer = csv.writer(f, delimiter="\t")
        writer.writerow(["id", *SafetyInput.model_fields])
        for case, value in cases():
            writer.writerow(
                [
                    case["id"],
                    *[
                        int(v) if isinstance(v, bool) else v
                        for v in value.model_dump(mode="json").values()
                    ],
                ]
            )


def compare(native, auth):
    with native.open() as f:
        rows = list(csv.DictReader(f, delimiter="\t"))
    vectors = cases()
    if [r["id"] for r in rows] != [c["id"] for c, _ in vectors]:
        raise ValueError("missing/reordered/duplicated native cases")
    results = []
    for row, (case, value) in zip(rows, vectors, strict=True):
        py = evaluate(value)
        expected = case["expected"]
        ok = py["reason"] == row["reason"] == expected["reason"]
        if py["reason"] == "ACCEPTED":
            ok &= Decimal(py["volume"]) == Decimal(row["volume"]) == Decimal(expected["volume"])
            ok &= all(Decimal(py[k]) == Decimal(row[k]) for k in ("risk", "gross", "margin"))
        results.append(
            {
                "id": case["id"],
                "pass": ok,
                "python": py,
                "native": {k: row[k] for k in ("reason", "volume", "risk", "gross", "margin")},
                "duration_us": int(row["duration_us"]),
            }
        )
    signature_ok = (
        auth.read_text().strip() == hmac.new(b"k" * 32, b"fixture", hashlib.sha256).hexdigest()
    )
    return {
        "version": "m2c-parity/1",
        "all_pass": all(r["pass"] for r in results) and signature_ok,
        "hmac_parity": signature_ok,
        "results": results,
        "timing_scope": (
            "One native pure-calculation pass per synthetic snapshot; "
            "excludes broker/transport/OS scheduling latency"
        ),
        "shadow_compute_budget_us": 20000,
        "shadow_compute_max_us": max(r["duration_us"] for r in results),
        "shadow_compute_pass": all(r["duration_us"] <= 20000 for r in results),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--export", type=Path)
    parser.add_argument("--native", type=Path)
    parser.add_argument("--hmac", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.export:
        export(args.export)
    else:
        report = compare(args.native, args.hmac)
        args.output.write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps({k: v for k, v in report.items() if k != "results"}))
        raise SystemExit(0 if report["all_pass"] and report["shadow_compute_pass"] else 1)
