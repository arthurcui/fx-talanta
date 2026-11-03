"""One immutable calendar refresh attempt; no broker or trading integration."""

import argparse
import json
from datetime import UTC, date, datetime
from hashlib import sha256
from pathlib import Path

from dotenv import dotenv_values

from fx_talanta import bls_calendar as bls
from fx_talanta import fred_calendar as fred
from fx_talanta import fred_calendar_html as html


def attempt(key, start, end, reference, *, previous=None):
    """Keep attempt lineage and last successful comparison as separate evidence.

    A failed fetch is never reused as current evidence. Its incomplete schedule
    also must not replace the baseline used to detect changes on recovery.
    """
    baseline = previous["comparison_baseline"] if previous else None
    prior_dates = fred.Snapshot.model_validate(previous["fred"]) if previous else None
    dates = fred.collect(key, start, end, previous=prior_dates)
    static = bls.import_calendar(reference)
    comparison = html.qualify(dates, static, previous=baseline)
    refreshed, error = bls.refresh()
    direct = bls.reconcile(refreshed, dates, datetime.now(UTC)) if refreshed is not None else None
    return {
        "schema_version": 1,
        "available_at": datetime.now(UTC).isoformat(),
        "previous_attempt_hash": sha256(json.dumps(previous, sort_keys=True).encode()).hexdigest()
        if previous
        else None,
        "fred": dates.model_dump(mode="json"),
        "reference": {"sha256": static.source_hash, "provenance": "MANUAL_FILE"},
        "comparison": comparison,
        "comparison_baseline": comparison if comparison["comparison_passed"] else baseline,
        "bls_refresh": {
            "error": error,
            "snapshot": refreshed.model_dump(mode="json") if refreshed else None,
            "assessment": direct,
        },
        "block_entries": True,
        "qualified_for_trading": False,
        "execution_enabled": False,
        "limitation": "Bounded refresh evidence, not release latency or complete news coverage",
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--bls-reference", type=Path, required=True)
    parser.add_argument("--start", type=date.fromisoformat, required=True)
    parser.add_argument("--end", type=date.fromisoformat, required=True)
    parser.add_argument("--previous", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:

        def read(path):
            with path.open("rb") as stream:
                raw = stream.read(2 * 1024 * 1024 + 1)
            if len(raw) > 2 * 1024 * 1024:
                raise ValueError("input limit")
            return raw

        reference = read(args.bls_reference)
        previous = json.loads(read(args.previous)) if args.previous else None
        key = dotenv_values(args.env_file).get("FRED_API_KEY", "")
        # Exclusive creation precedes network requests: existing evidence is immutable.
        with args.output.open("x", encoding="utf-8") as stream:
            result = attempt(key, args.start, args.end, reference, previous=previous)
            json.dump(result, stream, indent=2)
        print(
            json.dumps(
                {
                    "comparison_passed": result["comparison"]["comparison_passed"],
                    "bls_refresh_error": result["bls_refresh"]["error"],
                    "qualified_for_trading": False,
                }
            )
        )
        return 0 if result["comparison"]["comparison_passed"] else 2
    except (OSError, ValueError, TypeError, KeyError, fred.FredError):
        print("Qualification failed; inputs or transport unavailable. Trading remains disabled.")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
