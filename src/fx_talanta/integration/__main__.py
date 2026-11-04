"""Private-file readiness check. Does not connect to MT5, start a host or publish work."""

import argparse
import json
from pathlib import Path

from fx_talanta.integration.inputs import assemble


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture", type=Path, required=True)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--references", type=Path, required=True)
    args = parser.parse_args()
    import time

    try:
        capture = json.loads(args.capture.read_text())
        references = json.loads(args.references.read_text())
        results = []
        for symbol in ("EURUSD", "USDJPY"):
            for side in ("BUY", "SELL"):
                result, missing = assemble(
                    capture,
                    args.artifacts,
                    references,
                    symbol=symbol,
                    side=side,
                    now_ms=time.time_ns() // 1000000,
                )
                results.append(
                    dict(
                        symbol=symbol,
                        side=side,
                        inputs_complete=result.snapshot is not None,
                        missing=sorted(set(result.missing + missing)),
                    )
                )
        print(
            json.dumps(
                dict(
                    execution_enabled=False,
                    provider_qualified=False,
                    demo_order_acceptance=False,
                    results=results,
                ),
                indent=2,
            )
        )
    except (ValueError, OSError, KeyError, TypeError):
        # Do not echo malformed private captures, filenames containing IDs or DSNs.
        print(json.dumps(dict(execution_enabled=False, status="INPUT_VALIDATION_FAILED")))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
