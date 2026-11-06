"""Stopped-workspace backup/restore; restored copies never inherit active authority."""

import argparse
import hashlib
import json
import shutil
import sqlite3
from pathlib import Path, PurePosixPath

from fx_talanta.provider_pipeline import status_lock


def allowed(name):
    p = PurePosixPath(name)
    return (
        not p.is_absolute()
        and ".." not in p.parts
        and "\\" not in name
        and (
            name == "inspection.sqlite"
            or (p.parts[0] in ("calendar", "notifications") and len(p.parts) > 1)
        )
        and not name.endswith((".lock", "-wal", "-shm"))
    )


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify(directory):
    directory = Path(directory).resolve()
    manifest = json.loads((directory / "manifest.json").read_text())
    if (
        manifest.get("version") != "dashboard-backup/1"
        or not isinstance(manifest.get("files"), dict)
        or "inspection.sqlite" not in manifest["files"]
    ):
        raise ValueError("invalid backup")
    if len(manifest["files"]) > 10000:
        raise ValueError("too many files")
    for name, expected in manifest["files"].items():
        path = directory / name
        if (
            not allowed(name)
            or path.is_symlink()
            or directory not in path.resolve().parents
            or not path.is_file()
            or digest(path) != expected
        ):
            raise ValueError("backup hash/path mismatch")
        if path.suffix == ".sqlite":
            with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as conn:
                if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise ValueError("SQLite integrity failure")
    return manifest


def backup(source, destination):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if source == destination or source in destination.parents or destination in source.parents:
        raise ValueError("backup must be outside source")
    if not (source / "inspection.sqlite").is_file():
        raise ValueError("inspection journal missing")
    with status_lock(source / "dashboard.lock"):
        files = [source / "inspection.sqlite"]
        for folder in ("calendar", "notifications"):
            if (source / folder).exists():
                files += [p for p in (source / folder).rglob("*") if p.is_file()]
        destination.mkdir(parents=True, exist_ok=False)
        hashes = {}
        for path in files:
            name = path.relative_to(source).as_posix()
            if not allowed(name):
                continue
            if path.is_symlink() or source not in path.resolve().parents:
                raise ValueError("source symlink refused")
            target = destination / name
            target.parent.mkdir(parents=True, exist_ok=True)
            if path.suffix == ".sqlite":
                with (
                    sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as src,
                    sqlite3.connect(target) as dst,
                ):
                    src.backup(dst)
            else:
                shutil.copyfile(path, target)
            hashes[name] = digest(target)
        (destination / "manifest.json").write_text(
            json.dumps(
                dict(version="dashboard-backup/1", files=hashes, contains_private_evidence=True),
                sort_keys=True,
                indent=2,
            )
        )
        verify(destination)
    return dict(files=len(hashes), verified=True, execution_enabled=False)


def restore(source, destination):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    manifest = verify(source)
    if source == destination or source in destination.parents or destination in source.parents:
        raise ValueError("restore must be outside backup")
    destination.mkdir(parents=True, exist_ok=False)
    marker = destination / "restored-inspection-only.json"
    marker.write_text(json.dumps(dict(status="INCOMPLETE", execution_enabled=False)))
    for name in manifest["files"]:
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / name, target)
        if digest(target) != manifest["files"][name]:
            raise ValueError("restore copy changed")
    marker.write_text(
        json.dumps(
            dict(
                status="VERIFIED_INSPECTION_ONLY",
                execution_enabled=False,
                model_calls_enabled=False,
                operator_enabled=False,
            )
        )
    )
    return dict(
        files=len(manifest["files"]),
        verified=True,
        execution_enabled=False,
        authority_restored=False,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("backup", "verify", "restore"))
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--destination", type=Path)
    args = parser.parse_args()
    if args.operation == "verify":
        result = dict(files=len(verify(args.source)["files"]), verified=True)
    else:
        if not args.destination:
            parser.error("destination required")
        result = globals()[args.operation](args.source, args.destination)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
