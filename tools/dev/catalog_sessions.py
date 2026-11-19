"""Copy pinned tick indexes into an explicit offline dashboard catalog; never overwrite."""

import argparse
import json
import shutil
from pathlib import Path

from fx_talanta.dashboard.indexed_research import IndexedBundle, describe
from fx_talanta.research.session_study import Plan
from fx_talanta.research.spool import file_hash


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument(
        "--index", action="append", required=True, help="SYMBOL=path/to/ticks.sqlite"
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    plan = Plan.model_validate_json(args.plan.read_bytes())
    indexes = dict(value.split("=", 1) for value in args.index)
    args.output.mkdir(parents=True, exist_ok=True)
    for experiment in plan.experiments:
        source = Path(indexes[experiment.symbol])
        sha = file_hash(source)
        name = experiment.symbol.lower() + "-history.sqlite"
        target = args.output / name
        if target.exists():
            if file_hash(target) != sha:
                raise ValueError("refusing to overwrite different index")
        else:
            shutil.copyfile(source, target)
        e = experiment.model_copy(update={"name": experiment.symbol.lower() + "-three-full-days"})
        bundle = IndexedBundle(
            index_file=name,
            index_sha256=sha,
            experiment=e,
            latency_ms=plan.latency_ms,
            assume_research_inputs=plan.assume_research_inputs,
            minimum_closed_trades=20,
        )
        manifest = args.output / (experiment.symbol.lower() + "-index.json")
        raw = bundle.model_dump_json(indent=2) + "\n"
        if manifest.exists():
            if manifest.read_text() != raw:
                raise ValueError("refusing to overwrite different manifest")
        else:
            manifest.write_text(raw, encoding="utf-8")
        metadata = describe(args.output, bundle, file_hash(manifest))
        print(
            json.dumps(
                {
                    k: metadata[k]
                    for k in ("symbol", "start", "end", "events", "warmup_bars", "windows")
                }
            )
        )


if __name__ == "__main__":
    main()
