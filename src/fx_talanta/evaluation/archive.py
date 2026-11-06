"""Stopped simulation evidence bundles: portable verification, never activation."""

import argparse
import hashlib
import json
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path

from fx_talanta.clock import FakeClock, SystemClock
from fx_talanta.evaluation.ledger import canonical, digest
from fx_talanta.evaluation.operations import Operations
from fx_talanta.evaluation.runner import engine_hash
from fx_talanta.provider_pipeline import status_lock

FILES = ("source.sqlite", "runner.sqlite")
LIMIT = 128 * 1024 * 1024


def file_hash(path):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > LIMIT:
        raise ValueError("invalid bounded archive file")
    return hashlib.sha256(path.read_bytes()).hexdigest()


class _Inspection(Operations):
    """Relocation is used only for report reconstruction; stored bindings never change."""

    def target(self, binding, rows, acks):
        return super().target(
            binding.model_copy(update={"runner": str(self.path.parent / "runner.sqlite")}),
            rows,
            acks,
        )


def verify(directory, expected):
    directory = Path(directory)
    path = directory / "manifest.json"
    if path.is_symlink() or path.stat().st_size > 1024 * 1024:
        raise ValueError("invalid manifest size")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if digest(manifest) != expected or manifest.get("schema") != "simulation-archive/1":
        raise ValueError("archive manifest mismatch")
    if manifest["engine_hash"] != engine_hash() or set(manifest["files"]) != set(FILES):
        raise ValueError("archive engine or file set mismatch")
    for name in FILES:
        if file_hash(directory / name) != manifest["files"][name]:
            raise ValueError("archive file mismatch")
        if any((directory / (name + suffix)).exists() for suffix in ("-wal", "-shm", "-journal")):
            raise ValueError("archive must be standalone")
    clock = FakeClock(datetime.fromisoformat(manifest["captured_at"]))
    report = _Inspection(directory / "source.sqlite", clock).report(manifest["binding_hash"])
    if report["status"] != "SEALED" or report["runner"]["status"] != "STOPPED":
        raise ValueError("only sealed stopped evidence is portable")
    if report != manifest["report"]:
        raise ValueError("archive reconstruction mismatch")
    return dict(
        schema="simulation-archive-verification/1",
        result="VERIFIED",
        manifest_hash=expected,
        captured_at=manifest["captured_at"],
        inspection_only=True,
        current_readiness=False,
        execution_enabled=False,
        full_M5_complete=False,
        report=report,
    )


def capture(queue, binding_hash, destination, clock=None):
    queue, destination = Path(queue), Path(destination)
    clock = clock or SystemClock()
    # Fixed inspection time prevents receipt ages changing while copying immutable evidence.
    frozen = FakeClock(clock.now())
    operations = Operations(queue, frozen)
    with status_lock(queue.with_suffix(".consumer.lock")):
        report = operations.report(binding_hash)
        if report["status"] != "SEALED" or report["runner"]["status"] != "STOPPED":
            raise ValueError("stop source and runner before backup")
        with closing(operations.connect()) as conn:
            binding, _, _, _ = operations.load(conn, binding_hash)
        destination.mkdir(parents=True, exist_ok=False)
        for source, name in ((queue, FILES[0]), (Path(binding.runner), FILES[1])):
            file_hash(source)
            with closing(sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True)) as src:
                with closing(sqlite3.connect(destination / name)) as dst:
                    src.backup(dst)
        manifest = dict(
            schema="simulation-archive/1",
            engine_hash=engine_hash(),
            binding_hash=binding_hash,
            captured_at=frozen.now().isoformat(),
            files={name: file_hash(destination / name) for name in FILES},
            report=report,
        )
        (destination / "manifest.json").write_text(canonical(manifest), encoding="utf-8")
        expected = digest(manifest)
        verify(destination, expected)
        return dict(manifest_hash=expected, inspection_only=True, execution_enabled=False)


def restore(source, expected, destination):
    """Create a new inspection copy, never rewrite paths, budgets or deadlines."""
    source, destination = Path(source), Path(destination)
    verify(source, expected)
    destination.mkdir(parents=True, exist_ok=False)
    for name in (*FILES, "manifest.json"):
        with (destination / name).open("xb") as output:
            output.write((source / name).read_bytes())
    return verify(destination, expected)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("capture", "verify", "restore"))
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--destination", type=Path)
    parser.add_argument("--hash", required=True)
    args = parser.parse_args()
    if args.action != "verify" and not args.destination:
        parser.error("new destination required")
    result = (
        capture(args.source, args.hash, args.destination)
        if args.action == "capture"
        else restore(args.source, args.hash, args.destination)
        if args.action == "restore"
        else verify(args.source, args.hash)
    )
    print(canonical(result))


if __name__ == "__main__":
    main()
