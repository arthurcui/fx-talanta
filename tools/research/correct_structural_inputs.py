"""Prepare one separately identified correction of the retained June comparison.

No download, broker, model or run. Original history and evidence are opened
read-only. Only warmup/development quotes are selected from the parent index.
"""

import argparse
import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from fx_talanta.dashboard.indexed_research import IndexedBundle
from fx_talanta.dashboard.research import indexed_engine_hash
from fx_talanta.research.input_calendar import InputCalendar, WeekendClosure
from fx_talanta.research.replay import digest
from fx_talanta.research.spool import file_hash
from fx_talanta.research.tick_index import bars_from_ticks, milliseconds
from tools.research.diagnose_structural_confirmation import PINNED_INDEX, PINNED_MANIFEST
from tools.research.structural_study import END, SOURCE_HASH, START, save


def require(value, message):
    if not value:
        raise ValueError(message)


def inventory(directory):
    return {
        p.relative_to(directory).as_posix(): file_hash(p)
        for p in sorted(directory.rglob("*"))
        if p.is_file()
    }


def readonly(path):
    return sqlite3.connect(path.resolve().as_uri() + "?mode=ro&immutable=1", uri=True)


def review_weekends(db, bars):
    # Pinned before this rerun. Not inferred from the largest gaps or trade outcomes.
    closures = [
        WeekendClosure(start=f"2026-{day}T22:00:00Z", end=f"2026-{end}T22:00:00Z")
        for day, end in (("05-29", "05-31"), ("06-05", "06-07"))
    ]
    seen = {(b["timeframe"], datetime.fromisoformat(b["close_at"])) for b in bars}
    checks = []
    for closure in closures:
        start, end = milliseconds(closure.start), milliseconds(closure.end)
        absent = db.execute(
            "SELECT count(*) FROM ticks WHERE at_ms>=? AND at_ms<?", (start, end)
        ).fetchone()[0]
        before = db.execute(
            "SELECT max(at_ms) FROM ticks WHERE at_ms>=? AND at_ms<?", (start - 900_000, start)
        ).fetchone()[0]
        after = db.execute(
            "SELECT min(at_ms) FROM ticks WHERE at_ms>=? AND at_ms<?", (end, end + 900_000)
        ).fetchone()[0]
        require(
            absent == 0 and before is not None and after is not None,
            "source contradicts pinned weekend or lacks a flanking M15 observation",
        )
        require(
            all(
                (tf, closure.start) in seen
                and (tf, closure.end + timedelta(minutes=minutes)) in seen
                for tf, minutes in (("H1", 60), ("M15", 15))
            ),
            "missing flanking bar",
        )
        checks.append(
            dict(
                start=closure.start.isoformat(),
                end=closure.end.isoformat(),
                quotes_inside_closure=absent,
                last_quote_before_ms=before,
                first_quote_after_ms=after,
                exact_flanking_h1_and_m15=True,
            )
        )
    return closures, dict(
        schema="histdata-weekend-reconciliation/1",
        source_index_sha256=SOURCE_HASH,
        source_timezone="UTC-05:00_NO_DST",
        checks=checks,
        basis="RECONCILED_ARCHIVE_CONVENTION_NOT_PROVIDER_CERTIFIED",
        limitation="Provider documents timestamps, not an authoritative session calendar; "
        "no broker-clock remapping, holiday exemption or delivery qualification",
        source_urls=[
            "https://www.histdata.com/f-a-q/",
            "https://www.histdata.com/f-a-q/data-files-detailed-specification/",
        ],
        execution_enabled=False,
    )


def prepare(source, original, output):
    require(not output.exists(), "correction directory already exists; never overwrite")
    old_files = inventory(original)
    old_manifest = json.loads((original / "manifest.json").read_text())
    require(digest(old_manifest) == PINNED_MANIFEST, "wrong original manifest")
    old_bundle = json.loads((original / "datasets/structural-index.json").read_text())
    require(file_hash(original / "datasets/ticks.sqlite") == PINNED_INDEX, "original index changed")
    parent = IndexedBundle.model_validate_json((source / "acquired-index.json").read_bytes())
    parent_index = source / parent.index_file
    require(parent.index_sha256 == file_hash(parent_index) == SOURCE_HASH, "parent source changed")
    warm_start = parent.experiment.start
    require(warm_start <= START < END <= parent.experiment.training_end, "outside exposed training")
    output.mkdir(parents=True)
    (output / "datasets").mkdir()
    src, old = readonly(parent_index), readonly(original / "datasets/ticks.sqlite")
    target = output / "datasets/ticks.sqlite"
    dst = sqlite3.connect(target)
    try:
        bars, assembly = bars_from_ticks(src, "EURUSD", warm_start, END)
        metadata = json.loads(old.execute("SELECT value FROM metadata").fetchone()[0])
        old_bars = {(b["timeframe"], b["close_at"]): b for b in metadata["bars"]}
        new_bars = {(b["timeframe"], b["close_at"]): b for b in bars}
        require(
            all(k in new_bars and b == new_bars[k] for k, b in old_bars.items()),
            "an original retained bar changed or disappeared",
        )
        added = sorted(set(new_bars) - set(old_bars))
        expected = [
            ("H1", "2026-06-01T05:00:00Z"),
            ("H1", "2026-06-01T06:00:00Z"),
            ("M15", "2026-06-01T05:00:00Z"),
            ("M15", "2026-06-01T05:15:00Z"),
        ]
        require(added == expected, "unexpected bar reconstruction delta; inspect before running")
        closures, calendar_receipt = review_weekends(src, bars)
        save(output / "weekend-reconciliation.json", calendar_receipt)
        dst.execute("CREATE TABLE ticks(seq INTEGER PRIMARY KEY,at_ms INTEGER,bid TEXT,ask TEXT)")
        dst.execute("CREATE TABLE metadata(value TEXT NOT NULL)")
        cursor = old.execute("SELECT seq,at_ms,bid,ask FROM ticks ORDER BY at_ms,seq")
        while batch := cursor.fetchmany(5000):
            dst.executemany("INSERT INTO ticks VALUES(?,?,?,?)", batch)
        dst.execute("CREATE INDEX ticks_time ON ticks(at_ms,seq)")
        count = dst.execute("SELECT count(*) FROM ticks").fetchone()[0]
        metadata.update(
            bars=bars,
            rows=count,
            bar_assembly=assembly,
            original_development_index_sha256=PINNED_INDEX,
        )
        dst.execute("INSERT INTO metadata VALUES(?)", (json.dumps(metadata),))
        dst.commit()
        require(
            all(
                a == b
                for a, b in zip(
                    old.execute("SELECT seq,at_ms,bid,ask FROM ticks ORDER BY at_ms,seq"),
                    dst.execute("SELECT seq,at_ms,bid,ask FROM ticks ORDER BY at_ms,seq"),
                    strict=True,
                )
            ),
            "original quote rows changed",
        )
    finally:
        src.close()
        old.close()
        dst.close()
    calendar = InputCalendar(
        symbol="EURUSD",
        index_sha256=file_hash(target),
        evidence_sha256=file_hash(output / "weekend-reconciliation.json"),
        valid_from=warm_start,
        valid_to=END,
        closures=tuple(closures),
    )
    bundle = IndexedBundle.model_validate(
        dict(
            old_bundle,
            index_sha256=file_hash(target),
            input_calendar=calendar.model_dump(mode="json"),
        )
    )
    require(
        bundle.experiment.model_dump(mode="json") == old_bundle["experiment"],
        "experiment, costs or risk policy changed",
    )
    save(output / "datasets/structural-index.json", bundle.model_dump(mode="json"))
    manifest = dict(
        old_manifest,
        schema="structural-comparison/2",
        parent_manifest_sha256=PINNED_MANIFEST,
        parent_index_sha256=PINNED_INDEX,
        bundle_sha256=file_hash(output / "datasets/structural-index.json"),
        engine_sha256=indexed_engine_hash(),
        input_calendar=calendar.model_dump(mode="json"),
        authorized_changes=["RESTORE_FOUR_MONTH_JOIN_BARS", "TWO_REVIEWED_WEEKEND_CLOSURES"],
    )
    save(output / "manifest.json", manifest)
    quality = json.loads((original / "quality.json").read_text())
    quality.update(
        bars=len(bars),
        prepared_index_sha256=file_hash(target),
        preserved_original_bars=len(old_bars),
        added_bars=[list(k) for k in added],
        identical_original_quote_rows=count,
        bar_assembly=assembly,
        input_calendar=calendar.model_dump(mode="json"),
    )
    save(output / "quality.json", quality)
    require(old_files == inventory(original), "original evidence modified")
    require(file_hash(parent_index) == SOURCE_HASH, "parent modified")
    save(output / "original-evidence-fingerprints.json", old_files)
    print(
        json.dumps(
            dict(
                stage="PREPARED",
                restored_bars=len(added),
                unchanged_quote_rows=count,
                original_files_unchanged=len(old_files),
                closures=len(closures),
                manifest_sha256=digest(manifest),
            )
        ),
        flush=True,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--original", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    prepare(args.source, args.original, args.output)
