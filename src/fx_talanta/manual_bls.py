"""Manual BLS upload and on-demand review reminders; no scheduled or network work."""

import argparse
import json
import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

from fx_talanta import bls_calendar as bls
from fx_talanta.domain.models import utc
from fx_talanta.provider_pipeline import Journal, status_lock

REVIEW_INTERVAL = timedelta(days=7)


def latest(journal):
    row = journal.conn.execute(
        "SELECT o.payload FROM attempts a JOIN outcomes o ON o.attempt=a.id "
        "WHERE a.source='bls' AND o.status='OK' ORDER BY a.rowid DESC LIMIT 1"
    ).fetchone()
    return bls.BlsSnapshot.model_validate(json.loads(row[0])["payload"]) if row else None


def report(root, journal, now):
    snapshot = latest(journal) if journal else None
    reasons = []
    result = dict(
        source_url=bls.URL,
        checked_at=now.isoformat(),
        provenance="MANUAL_FILE",
        qualified_for_trading=False,
        execution_enabled=False,
        calendar_coverage_complete=False,
        reminder_due=True,
        reasons=reasons,
        message="Download the latest BLS calendar and upload the .ics file.",
    )
    if not snapshot:
        reasons.append("NO_UPLOAD")
        return result
    with (root / "archive" / (snapshot.source_hash + ".ics")).open("rb") as stream:
        raw = stream.read(bls.LIMIT + 1)
    if len(raw) > bls.LIMIT or sha256(raw).hexdigest() != snapshot.source_hash:
        raise ValueError("archive integrity")
    due = snapshot.imported_at + REVIEW_INTERVAL
    upcoming = [e for e in snapshot.events if e.scheduled_at >= now and e.status != "CANCELLED"]
    horizon = max((e.scheduled_at for e in upcoming), default=None)
    if now < snapshot.imported_at:
        reasons.append("CLOCK_ROLLBACK")
    if now >= due:
        reasons.append("REVIEW_OVERDUE")
    if horizon is None or horizon <= now + REVIEW_INTERVAL:
        reasons.append("SCHEDULE_RUNNING_OUT")
    row = journal.conn.execute(
        "SELECT o.status FROM attempts a LEFT JOIN outcomes o ON o.attempt=a.id "
        "WHERE a.source='bls' ORDER BY a.rowid DESC LIMIT 1"
    ).fetchone()
    if row and row[0] != "OK":
        reasons.append("LAST_UPLOAD_FAILED_OR_INTERRUPTED")
    result.update(
        last_reviewed_at=snapshot.imported_at.isoformat(),
        review_due_at=due.isoformat(),
        last_scheduled_event=horizon.isoformat() if horizon else None,
        event_count=len(snapshot.events),
        upcoming_event_count=len(upcoming),
        source_hash=snapshot.source_hash,
        reminder_due=bool(reasons),
        message=(
            "Download the latest BLS calendar and upload it; this is a manual review reminder."
            if reasons
            else "Saved for development. Review by the due date; source freshness is unverified."
        ),
    )
    return result


def status(root, *, clock=lambda: datetime.now(UTC)):
    root = Path(root).resolve()
    if not (root / "journal.sqlite").exists():
        return report(root, None, utc(clock()))
    with (
        status_lock(root / "journal.collector"),
        closing(Journal(root / "journal.sqlite")) as journal,
    ):
        return report(root, journal, utc(clock()))


def upload(root, path, *, reviewed_latest=False, clock=lambda: datetime.now(UTC)):
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    with (
        status_lock(root / "journal.collector"),
        closing(Journal(root / "journal.sqlite", create=True)) as journal,
    ):
        previous = latest(journal)
        attempt = journal.begin("bls", utc(clock()))
        try:
            with Path(path).open("rb") as stream:
                raw = stream.read(bls.LIMIT + 1)
            if len(raw) > bls.LIMIT:
                raise ValueError("upload size limit")
            snapshot = bls.import_calendar(raw, previous=previous)
            unchanged = previous is not None and previous.source_hash == snapshot.source_hash
            # A duplicate upload is still auditable, but cannot silently postpone review.
            imported = previous.imported_at if unchanged and not reviewed_latest else utc(clock())
            snapshot = snapshot.model_copy(update={"imported_at": imported})
            archive = root / "archive"
            archive.mkdir(exist_ok=True)
            target = archive / (snapshot.source_hash + ".ics")
            if target.exists():
                if target.read_bytes() != raw:
                    raise ValueError("archive integrity")
            else:
                temporary = archive / (uuid4().hex + ".tmp")
                with temporary.open("xb") as stream:
                    stream.write(raw)
                    stream.flush()
                temporary.replace(target)
            journal.finish(
                attempt,
                dict(
                    status="OK",
                    payload=snapshot.model_dump(mode="json"),
                    provenance="MANUAL_FILE",
                    user_confirmed_latest=reviewed_latest,
                ),
                utc(clock()),
            )
        except (OSError, ValueError):
            journal.finish(
                attempt, dict(status="FAILED", error="MANUAL_UPLOAD_REJECTED"), utc(clock())
            )
            raise ValueError(
                "Upload rejected; previous calendar and failure evidence preserved"
            ) from None
        result = report(root, journal, utc(clock()))
        result["upload_result"] = "UNCHANGED" if unchanged else "IMPORTED"
        return result


def choose_file():
    import tkinter
    from tkinter import filedialog

    try:
        window = tkinter.Tk()
    except tkinter.TclError as exc:
        raise ValueError("Desktop chooser unavailable; use --file") from exc
    window.withdraw()
    try:
        return filedialog.askopenfilename(
            title="Upload BLS calendar", filetypes=[("Calendar", "*.ics")]
        )
    finally:
        window.destroy()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", type=Path, default=Path(".local/manual-bls"))
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status", help="show saved calendar and any review reminder")
    add = sub.add_parser("upload", help="validate and archive a manually downloaded calendar")
    source = add.add_mutually_exclusive_group(required=True)
    source.add_argument("--file", type=Path)
    source.add_argument(
        "--choose", action="store_true", help="open the desktop file chooser (Tk required)"
    )
    add.add_argument(
        "--reviewed-latest",
        action="store_true",
        help="confirm you checked the latest official download, even if unchanged",
    )
    args = parser.parse_args(argv)
    try:
        if args.command == "upload":
            selected = choose_file() if args.choose else args.file
            if not selected:
                print("Upload cancelled; saved calendar unchanged.")
                return 0
            result = upload(args.store, selected, reviewed_latest=args.reviewed_latest)
        else:
            result = status(args.store)
        print(json.dumps(result, indent=2))
        return 0
    except (OSError, ValueError, sqlite3.Error, ImportError):
        print(
            json.dumps(
                dict(
                    reminder_due=True,
                    execution_enabled=False,
                    error=(
                        "Calendar unavailable or upload rejected. Check the file/store; "
                        "use --file if the desktop chooser is unavailable."
                    ),
                )
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
