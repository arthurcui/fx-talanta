"""Background numerical comparison with an independent JavaScript rational oracle."""

import argparse
import json
import shutil
import subprocess
from datetime import UTC, datetime, timedelta
from decimal import Decimal, localcontext
from hashlib import sha256
from pathlib import Path

from fx_talanta.research.baseline import Bar, ema, evaluate

AT = datetime(2025, 2, 18, 12, tzinfo=UTC)
TOLERANCE = Decimal("1e-26")  # Numerical values only; side/rounded distances must match exactly.


def vectors():
    for symbol, base, step in (
        ("EURUSD", Decimal("1.2"), Decimal("0.00001")),
        ("USDJPY", Decimal("150"), Decimal("0.001")),
    ):
        for length in (200, 201, 260):
            for direction in (-1, 0, 1):
                for equality in (False, True):
                    closes = [
                        base + step * (direction * i + (i % 7 if direction else 0))
                        for i in range(length)
                    ]
                    m15 = []
                    for i in range(35):
                        price = base + step * ((i * 11) % 17)
                        m15.append(
                            {
                                "open": price,
                                "high": price + 4 * step,
                                "low": price - 3 * step,
                                "close": price + step,
                            }
                        )
                    boundary = (
                        min(b["low"] for b in m15[-21:-1])
                        if direction < 0
                        else max(b["high"] for b in m15[-21:-1])
                    )
                    close = boundary + (0 if equality else (-1 if direction < 0 else 1)) * step
                    m15[-1] = {
                        "open": close,
                        "high": close + step,
                        "low": close - step,
                        "close": close,
                    }
                    yield {
                        "name": f"{symbol}-{length}-{direction}-{equality}",
                        "symbol": symbol,
                        "quantum": format(step, "f"),
                        "h1": [format(v, "f") for v in closes],
                        "m15": [{k: format(v, "f") for k, v in b.items()} for b in m15],
                    }


def bars(case):
    result = []
    for i, close in enumerate(case["h1"]):
        at = AT - timedelta(hours=len(case["h1"]) - i - 1)
        result.append(
            Bar(
                symbol=case["symbol"],
                timeframe="H1",
                close_at=at,
                available_at=at,
                revision=1,
                open=close,
                high=close,
                low=close,
                close=close,
            )
        )
    for i, values in enumerate(case["m15"]):
        at = AT - timedelta(minutes=15 * (len(case["m15"]) - i - 1))
        result.append(
            Bar(
                symbol=case["symbol"],
                timeframe="M15",
                close_at=at,
                available_at=at,
                revision=1,
                **values,
            )
        )
    return result


def rational(value):
    with localcontext() as context:
        context.prec = 80
        return Decimal(value["numerator"]) / Decimal(value["denominator"])


def qualify():
    node = shutil.which("node")
    if node is None:
        raise RuntimeError("Node.js is required for independent cross-language evidence")
    reference = Path(__file__).with_name("b01_reference.mjs")
    cases = list(vectors())
    raw = json.dumps(cases, sort_keys=True).encode()
    completed = subprocess.run(
        [node, str(reference)], input=raw, capture_output=True, check=True, timeout=60
    )
    expected = json.loads(completed.stdout)
    if len(expected) != len(cases):
        raise ValueError("reference case count mismatch")
    results = []
    for case, target in zip(cases, expected, strict=True):
        if case["name"] != target["name"]:
            raise ValueError("reference ordering mismatch")
        decision = evaluate(bars(case), case["symbol"], AT, history_complete=True)
        if decision.get("side") != target["side"]:
            raise ValueError(f"side mismatch: {case['name']}")
        with localcontext() as context:
            context.prec = 34
            values = list(map(Decimal, case["h1"]))
            actual = {"ema50": ema(values, 50), "ema200": ema(values, 200)}
        if decision["action"] == "CANDIDATE":
            actual["atr14"] = Decimal(decision["atr14"])
            for key in ("stop_distance", "target_distance"):
                if Decimal(decision[key]) != rational(target[key]):
                    raise ValueError(f"rounded risk distance mismatch: {case['name']} {key}")
        errors = {key: abs(value - rational(target[key])) for key, value in actual.items()}
        if any(error > TOLERANCE for error in errors.values()):
            raise ValueError(f"numerical tolerance exceeded: {case['name']}")
        results.append(
            {
                "case": case["name"],
                "action": decision["action"],
                "maximum_absolute_error": str(max(errors.values())),
                "passed": True,
            }
        )
    return {
        "schema": "b01-independent-numerical-parity/1",
        "cases": results,
        "passed": True,
        "vectors_sha256": sha256(raw).hexdigest(),
        "reference_sha256": sha256(reference.read_bytes().replace(b"\r\n", b"\n")).hexdigest(),
        "baseline_sha256": sha256(
            (Path(__file__).parents[2] / "src/fx_talanta/research/baseline.py")
            .read_bytes()
            .replace(b"\r\n", b"\n")
        ).hexdigest(),
        "numerical_absolute_tolerance": str(TOLERANCE),
        "side_and_rounded_distances": "EXACT",
        "node_version": subprocess.check_output([node, "--version"], text=True).strip(),
        "execution_enabled": False,
        "mql5_native_parity": False,
        "scope": "Synthetic numerical kernel only; no terminal, cost or economic qualification",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    from fx_talanta.research.session_study import background_priority

    background_priority()
    result = qualify()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"cases": len(result["cases"]), "passed": result["passed"]}))


if __name__ == "__main__":
    main()
