"""Credential-free FOREX.com demo planning and a durable local alert outbox.

This is administrative metadata, not a broker ledger or trading authority. It
never contacts a broker, switches an account, or clears campaign risk state.
"""

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated
from uuid import UUID, uuid4

from pydantic import Field, model_validator

from fx_talanta.domain.models import AccountIdentity, FrozenModel, Text, Timestamp, utc


class ExpiryEvidence(FrozenModel):
    expires_at: Timestamp
    observed_at: Timestamp
    source: Text


class DemoSchedule(FrozenModel):
    campaign_id: UUID
    account: AccountIdentity
    signup_at: Timestamp | None = None
    signup_at_estimated: bool = False
    signup_source: Text | None = None
    confirmed_expiries: Annotated[tuple[ExpiryEvidence, ...], Field(max_length=32)] = ()
    notice_days: Annotated[int, Field(ge=1, le=89)] = 14
    handoff_days: Annotated[int, Field(ge=1, le=88)] = 7
    replacement: AccountIdentity | None = None
    replacement_ready: bool = False
    replacement_evidence: Text | None = None

    @model_validator(mode="after")
    def validate_schedule(self):
        if self.signup_at_estimated and not (self.signup_at and self.signup_source):
            raise ValueError("estimated signup time requires a timestamp and source reference")
        if self.handoff_days >= self.notice_days:
            raise ValueError("replacement notice must precede the handoff cutoff")
        for account in (self.account, self.replacement):
            if account and (account.environment != "PAPER" or account.venue != "BROKER_DEMO"):
                raise ValueError("demo lifecycle accepts only PAPER/BROKER_DEMO identities")
        if self.account.broker != "FOREX.com Canada":
            raise ValueError("this expiry policy is specific to FOREX.com Canada")
        if self.replacement:
            if self.replacement.broker != self.account.broker or self.replacement == self.account:
                raise ValueError("replacement must be a distinct demo of the same broker")
        if self.replacement_ready and not (self.replacement and self.replacement_evidence):
            raise ValueError("replacement readiness requires an identity and evidence reference")
        if self.signup_at and any(e.expires_at <= self.signup_at for e in self.confirmed_expiries):
            raise ValueError("confirmed expiry must be after signup")
        return self

    def key(self):
        return digest(
            {"campaign_id": str(self.campaign_id), "account": self.account.model_dump(mode="json")}
        )


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def evaluate(schedule, now):
    schedule = DemoSchedule.model_validate(schedule.model_dump(mode="json"))
    now = utc(now)
    dates = {e.expires_at for e in schedule.confirmed_expiries}
    estimated = not dates and schedule.signup_at is not None
    expiry = min(dates) if dates else schedule.signup_at + timedelta(days=90) if estimated else None
    unverified = (schedule.signup_at is not None and schedule.signup_at > now) or any(
        e.observed_at > now for e in schedule.confirmed_expiries
    )
    notice = expiry - timedelta(days=schedule.notice_days) if expiry else None
    handoff = expiry - timedelta(days=schedule.handoff_days) if expiry else None
    if unverified:
        state = "INVALID_TIMELINE"
    elif len(dates) > 1:
        state = "CONFLICTING_EXPIRY"
    elif expiry is None:
        state = "UNKNOWN_EXPIRY"
    elif now >= expiry:
        state = "EXPIRED"
    elif now >= handoff:
        state = "HANDOFF_DUE"
    elif now >= notice:
        state = "REPLACEMENT_DUE"
    else:
        state = "ACTIVE"
    actions = {
        "INVALID_TIMELINE": "Resolve future-dated signup or evidence before using this schedule.",
        "CONFLICTING_EXPIRY": "Resolve conflicting expiry evidence; earliest date is provisional.",
        "UNKNOWN_EXPIRY": "Record signup time or confirmed expiry; no date has been invented.",
        "EXPIRED": "Pause the secondary deployment; retain history and resolve evidence gaps.",
        "HANDOFF_DUE": "Keep handoff blocked until retirement, backup and validation are complete.",
        "REPLACEMENT_DUE": "Provision and validate a separate replacement demo before the cutoff.",
        "ACTIVE": "Continue daily readiness checks; retain the signup and expiry evidence.",
    }
    return {
        "account_key": schedule.key(),
        "state": state,
        "signup_at_estimated": schedule.signup_at_estimated,
        "expiry_basis": "CONFLICTING"
        if len(dates) > 1
        else "ESTIMATED"
        if estimated
        else "CONFIRMED"
        if dates
        else "UNKNOWN",
        "effective_expiry": expiry.isoformat() if expiry else None,
        "notice_at": notice.isoformat() if notice else None,
        "handoff_at": handoff.isoformat() if handoff else None,
        "replacement_ready": schedule.replacement_ready,
        "action": actions[state],
        "secondary_pause_required": state
        in {"INVALID_TIMELINE", "CONFLICTING_EXPIRY", "UNKNOWN_EXPIRY", "EXPIRED", "HANDOFF_DUE"},
        "handoff_authorized": False,
        "execution_enabled": False,
        "cmc_affected": False,
    }


class LifecycleStore:
    """SQLite administrative sidecar, deliberately separate from broker/risk ledgers."""

    def __init__(self, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with self.connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS accounts (
                    account_key TEXT PRIMARY KEY, signature TEXT NOT NULL,
                    checked_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS events (
                    sequence INTEGER PRIMARY KEY, event_id TEXT UNIQUE NOT NULL,
                    account_key TEXT NOT NULL, checked_at TEXT NOT NULL,
                    schedule TEXT NOT NULL, assessment TEXT NOT NULL,
                    delivery TEXT NOT NULL
                        CHECK(delivery IN ('PENDING','ACKNOWLEDGED','SUPERSEDED','NONE'))
                );
                CREATE TABLE IF NOT EXISTS daily_checks (
                    account_key TEXT NOT NULL, day TEXT NOT NULL, signature TEXT NOT NULL,
                    checked_at TEXT NOT NULL, assessment TEXT NOT NULL,
                    PRIMARY KEY(account_key,day,signature)
                );
            """)

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.path, timeout=10)
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def check(self, schedule, now=None):
        now = utc(now or datetime.now(UTC))
        assessment = evaluate(schedule, now)
        key = schedule.key()
        # Include evidence/readiness changes, but not a ticking countdown or check time.
        signature = digest({"assessment": assessment, "schedule": schedule.model_dump(mode="json")})
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            previous = conn.execute(
                "SELECT signature,checked_at FROM accounts WHERE account_key=?", (key,)
            ).fetchone()
            if previous and now < datetime.fromisoformat(previous[1]):
                raise ValueError("lifecycle check clock moved backwards")
            if previous is None or previous[0] != signature:
                conn.execute(
                    "UPDATE events SET delivery='SUPERSEDED' "
                    "WHERE account_key=? AND delivery='PENDING'",
                    (key,),
                )
                alert = previous is not None or assessment["state"] != "ACTIVE"
                conn.execute(
                    "INSERT INTO events(event_id,account_key,checked_at,"
                    "schedule,assessment,delivery) "
                    "VALUES(?,?,?,?,?,?)",
                    (
                        str(uuid4()),
                        key,
                        now.isoformat(),
                        schedule.model_dump_json(),
                        json.dumps(assessment),
                        "PENDING" if alert else "NONE",
                    ),
                )
            conn.execute(
                "INSERT INTO accounts VALUES(?,?,?) ON CONFLICT(account_key) DO UPDATE SET "
                "signature=excluded.signature,checked_at=excluded.checked_at",
                (key, signature, now.isoformat()),
            )
            conn.execute(
                "INSERT OR IGNORE INTO daily_checks VALUES(?,?,?,?,?)",
                (key, now.date().isoformat(), signature, now.isoformat(), json.dumps(assessment)),
            )
            pending = conn.execute(
                "SELECT event_id FROM events WHERE account_key=? AND delivery='PENDING' "
                "ORDER BY sequence DESC",
                (key,),
            ).fetchall()
        return {
            "checked_at": now.isoformat(),
            **assessment,
            "pending_alert_ids": [row[0] for row in pending],
        }

    def acknowledge(self, schedule, event_id):
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT delivery FROM events WHERE account_key=? AND event_id=?",
                (schedule.key(), str(event_id)),
            ).fetchone()
            if row is None:
                raise ValueError("alert does not belong to this account/campaign")
            if row[0] == "PENDING":
                conn.execute(
                    "UPDATE events SET delivery='ACKNOWLEDGED' WHERE event_id=?", (str(event_id),)
                )
                return "ACKNOWLEDGED"
            return row[0]


def main():
    import argparse

    from pydantic import ValidationError

    parser = argparse.ArgumentParser(description="FOREX.com demo expiry planning; no broker access")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--state-db", type=Path, default=Path(".local/forex-lifecycle.sqlite3"))
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("check", help="record readiness and return stable pending alert IDs")
    sub.add_parser("preview", help="evaluate without writing state")
    ack = sub.add_parser("ack", help="acknowledge one delivered alert, scoped to this account")
    ack.add_argument("event_id", type=UUID)
    args = parser.parse_args()
    try:
        schedule = DemoSchedule.model_validate_json(args.config.read_text(encoding="utf-8-sig"))
        if args.command == "preview":
            result = evaluate(schedule, datetime.now(UTC))
        else:
            store = LifecycleStore(args.state_db)
            result = (
                store.check(schedule)
                if args.command == "check"
                else {"delivery": store.acknowledge(schedule, args.event_id)}
            )
        print(json.dumps(result, indent=2))
    except ValidationError:
        parser.exit(1, "Invalid lifecycle configuration; no secret/input values are echoed.\n")
    except (OSError, sqlite3.Error):
        parser.exit(1, "Local lifecycle state could not be read or written.\n")
    except ValueError as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
