"""Consume bounded MT5 calendar exports; never connects to or controls a terminal."""

import argparse
import json
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

from pydantic import Field, model_validator

from fx_talanta.domain.models import FrozenModel, Timestamp
from fx_talanta.mt5_calendar import LIMIT, ClockPolicy, import_file, parse
from fx_talanta.provider_pipeline import Journal, status_lock


class Deployment(FrozenModel):
    schema_version: int = Field(default=1, ge=1, le=1)
    inbox: Path
    installed_at: Timestamp
    expires_at: Timestamp
    server_from: int
    server_until: int
    clock_policy: ClockPolicy
    execution_enabled: bool = False

    @model_validator(mode="after")
    def bounded(self):
        clock = self.clock_policy
        start, end = clock.decode(self.server_from), clock.decode(self.server_until)
        if (
            self.execution_enabled
            or clock.evidence_type != "INDEPENDENT_CALENDAR_CHECK"
            or not clock.verified_at <= self.installed_at < self.expires_at <= end
            or not start <= self.installed_at
        ):
            raise ValueError("invalid deployment scope or clock verification")
        return self


def atomic_json(path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def failure(journal, now, code, digest=None):
    attempt = journal.begin("mt5_calendar", now)
    journal.finish(attempt, {"status": "FAILED", "error": code, "source_hash": digest}, now)


def collect(root, now=None):
    """One bounded scan. Immutable outcomes are the restart cursor; tmp files are ignored."""
    now = now or datetime.now(UTC)
    root = Path(root).resolve()
    config = Deployment.model_validate_json((root / "deployment.json").read_bytes())
    config_hash = sha256(config.model_dump_json().encode()).hexdigest()
    with status_lock(root / "journal.collector"):
        journal = Journal(root / "journal.sqlite", create=True)
        try:
            pinned = journal.conn.execute(
                "SELECT value FROM metadata WHERE id='deployment_hash'"
            ).fetchone()
            if pinned and pinned[0] != config_hash:
                raise ValueError("deployment changed; use a separate deployment journal")
            with journal.conn:
                journal.conn.execute(
                    "INSERT OR IGNORE INTO metadata VALUES ('deployment_hash', ?)", (config_hash,)
                )
            archive = root / "archive"
            archive.mkdir(exist_ok=True)
            state, imported = None, 0
            if now < config.installed_at:
                state = "CLOCK_ROLLBACK"
            elif now >= config.expires_at:
                state = "EXPIRED"
            elif (root / "STOP").exists() or (config.inbox / "STOP").exists():
                state = "STOPPED"
            elif not config.inbox.is_dir():
                state = "INBOX_UNAVAILABLE"
            else:
                seen = set()
                for (payload,) in journal.conn.execute("SELECT payload FROM outcomes"):
                    data = json.loads(payload)
                    seen.add(data.get("source_hash") or data.get("payload", {}).get("source_hash"))
                files = sorted(
                    config.inbox.glob(f"fx-calendar-{config.clock_policy.bridge_id}-*.json")
                )
                if len(files) > 2000:
                    state = "ARCHIVE_LIMIT"
                else:
                    # A bounded window permits at most 2,000 files; never silently drop evidence.
                    for file in files:
                        if file.is_symlink() or file.stat().st_size > LIMIT:
                            state = "INVALID_FILE"
                            break
                        with file.open("rb") as stream:
                            raw = stream.read(LIMIT + 1)
                        digest = sha256(raw).hexdigest()
                        if digest in seen:
                            continue
                        target = archive / (digest + ".json")
                        if not target.exists():
                            with target.open("xb") as stream:
                                stream.write(raw)
                        elif target.read_bytes() != raw:
                            raise ValueError("archive integrity failure")
                        seen.add(digest)
                        try:
                            snapshot = parse(raw)
                            if (
                                snapshot.server_from != config.server_from
                                or snapshot.server_until != config.server_until
                                or datetime.fromtimestamp(snapshot.started_utc, UTC)
                                < config.installed_at
                            ):
                                raise ValueError("unexpected window or pre-deployment export")
                        except ValueError:
                            failure(journal, now, "INVALID_EXPORT", digest)
                            continue
                        try:
                            import_file(journal, raw, config.clock_policy, now)
                            imported += 1
                        except ValueError:
                            pass  # The importer preserved a failed immutable attempt.
            latest = journal.conn.execute(
                "SELECT o.status, o.payload FROM attempts a LEFT JOIN outcomes o ON o.attempt=a.id "
                "WHERE a.source='mt5_calendar' ORDER BY a.rowid DESC LIMIT 1"
            ).fetchone()
            age, exported_at = None, None
            if state is None:
                if not latest:
                    state = "WAITING"
                elif latest[0] != "OK":
                    state = "FAILED"
                else:
                    payload = json.loads(latest[1])["payload"]
                    exported_at = payload["exported_at"]
                    age = (now - datetime.fromisoformat(exported_at)).total_seconds()
                    state = "FRESH" if 0 <= age <= 120 else "STALE"
            status = dict(
                state=state,
                checked_at=now.isoformat(),
                exported_at=exported_at,
                export_age_seconds=age,
                imported_snapshots=imported,
                expires_at=config.expires_at.isoformat(),
                deployment_hash=config_hash,
                qualified_for_trading=False,
                execution_enabled=False,
            )
            atomic_json(root / "status.json", status)
            return status
        finally:
            journal.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--deployment", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        status = collect(args.deployment)
        print(json.dumps(status))
        return 0 if status["state"] in {"FRESH", "EXPIRED", "STOPPED"} else 2
    except Exception:
        # Never leave a prior FRESH status looking current after unexpected failure.
        atomic_json(
            args.deployment / "status.json",
            dict(state="ERROR", checked_at=datetime.now(UTC).isoformat(), execution_enabled=False),
        )
        print("Calendar collection failed; entries remain blocked.")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
