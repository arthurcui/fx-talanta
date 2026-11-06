"""Convert an existing offline `fx-talanta history` JSON export without database access."""

import argparse
import json
from pathlib import Path

from fx_talanta.dashboard.models import Snapshot
from fx_talanta.domain.models import Record


def convert(raw, label):
    if len(raw) > 8 * 1024 * 1024:
        raise ValueError("history export exceeds 8 MiB")
    data = json.loads(raw)
    if not isinstance(data, list) or not 1 <= len(data) <= 1000:
        raise ValueError("select 1–1000 exported records; no silent truncation")
    records = tuple(Record.model_validate(r) for r in data)
    return Snapshot(
        label=label,
        source="RECORDED_SIMULATOR",
        account=records[0].account,
        captured_at=max(r.recorded_at for r in records),
        records=records,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--records", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--label", default="Recorded offline journal")
    args = parser.parse_args()
    with args.records.open("rb") as f:
        raw = f.read(8 * 1024 * 1024 + 1)
    snapshot = convert(raw, args.label)
    with args.output.open("x", encoding="utf-8") as f:
        f.write(snapshot.model_dump_json(indent=2) + "\n")
    print("Offline snapshot written; channels remain unknown without telemetry evidence.")


if __name__ == "__main__":
    main()
