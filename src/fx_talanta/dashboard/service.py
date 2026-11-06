"""Browser-independent inspection sampler and local durable notification spool.

No broker/EA actions, external messages, model calls or qualification claims.
"""

import hashlib
import json
import threading
from datetime import datetime


class Notifications:
    def __init__(self, app):
        self.app = app
        with app.repo.lock, app.repo.conn:
            app.repo.conn.execute(
                "CREATE TABLE IF NOT EXISTS notifications (id INTEGER PRIMARY KEY, "
                "payload TEXT NOT NULL, digest TEXT NOT NULL, "
                "delivered INTEGER NOT NULL DEFAULT 0, attempts INTEGER NOT NULL DEFAULT 0, "
                "acknowledged TEXT)"
            )
        self.directory = app.state / "notifications"
        self.directory.mkdir(exist_ok=True)
        if self.directory.is_symlink() or self.directory.resolve().parent != app.state.resolve():
            raise ValueError("notification spool must stay inside workspace")

    def pump(self):
        repo = self.app.repo
        with repo.lock, repo.conn:
            rows = repo.conn.execute(
                "SELECT seq,kind,state,at,evidence FROM incidents WHERE seq NOT IN "
                "(SELECT id FROM notifications) ORDER BY seq LIMIT 100"
            ).fetchall()
            for row in rows:
                event = dict(zip(("id", "kind", "state", "at", "evidence"), row, strict=True))
                event.update(version="dashboard-notification/1", execution_enabled=False)
                payload = json.dumps(event, sort_keys=True, separators=(",", ":"))
                repo.conn.execute(
                    "INSERT INTO notifications(id,payload,digest) VALUES (?,?,?)",
                    (row[0], payload, hashlib.sha256(payload.encode()).hexdigest()),
                )
            rows = repo.conn.execute(
                "SELECT id,payload,digest FROM notifications WHERE delivered=0 "
                "ORDER BY attempts ASC,id ASC LIMIT 100"
            ).fetchall()
        # Files are immutable per incident. Matching receipts are safe across crash/restart.
        for ident, payload, digest in rows:
            path = self.directory / f"incident-{ident}.json"
            try:
                if path.exists():
                    if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                        raise ValueError("notification conflict")
                else:
                    with path.open("x", encoding="utf-8", newline="") as stream:
                        stream.write(payload)
                        stream.flush()
                        import os

                        os.fsync(stream.fileno())
                delivered = 1
            except (OSError, ValueError):
                delivered = 0
            with repo.lock, repo.conn:
                repo.conn.execute(
                    "UPDATE notifications SET delivered=?,attempts=attempts+1 WHERE id=?",
                    (delivered, ident),
                )

    def summary(self):
        with self.app.repo.lock:
            counts = self.app.repo.conn.execute(
                "SELECT "
                "count(*),coalesce(sum(delivered=0),0),"
                "coalesce(sum(acknowledged IS NULL),0) FROM notifications"
            ).fetchone()
            rows = self.app.repo.conn.execute(
                "SELECT payload,delivered,acknowledged FROM notifications ORDER BY id "
                "DESC LIMIT 100"
            ).fetchall()
        return dict(
            total=counts[0],
            undelivered=counts[1],
            unacknowledged=counts[2],
            scope="LOCAL_FILES_NOT_EXTERNAL_DELIVERY",
            events=[
                dict(event=json.loads(p), delivered=bool(d), acknowledged=a) for p, d, a in rows
            ],
        )

    def acknowledge(self, data):
        if (
            not isinstance(data, dict)
            or set(data) != {"id"}
            or type(data["id"]) is not int
            or data["id"] < 1
        ):
            raise ValueError("invalid notification")
        with self.app.repo.lock, self.app.repo.conn:
            row = self.app.repo.conn.execute(
                "SELECT delivered,digest FROM notifications WHERE id=?", (data["id"],)
            ).fetchone()
            path = self.directory / f"incident-{data['id']}.json"
            if (
                not row
                or not row[0]
                or not path.is_file()
                or path.is_symlink()
                or hashlib.sha256(path.read_bytes()).hexdigest() != row[1]
            ):
                raise ValueError("notification not delivered or changed")
            self.app.repo.conn.execute(
                "UPDATE notifications SET acknowledged=coalesce(acknowledged,?) WHERE id=?",
                (self.app.clock.now().isoformat(), data["id"]),
            )
        return dict(acknowledged=True, execution_enabled=False)


class InspectionService:
    def __init__(self, app, interval=5):
        if type(interval) is not int or not 1 <= interval <= 60:
            raise ValueError("invalid interval")
        self.app, self.interval = app, interval
        self._stop = threading.Event()
        self.thread = None
        self.last_success = None
        self.failed = False
        with app.repo.lock, app.repo.conn:
            app.repo.conn.execute(
                "CREATE TABLE IF NOT EXISTS service_heartbeat (singleton INTEGER "
                "PRIMARY KEY CHECK(singleton=1), at TEXT NOT NULL)"
            )

    def sample(self):
        self.app.overview()
        if self.app.broker_view:
            try:
                result = self.app.broker()
                sample = result.get("snapshot")
                state = (
                    sample["display_status"]
                    if sample
                    else result.get("reason", result.get("status", "UNKNOWN"))
                )
                states = {
                    "broker-journal": state,
                    "broker-transport-at-capture": result.get("transport_at_capture", "UNKNOWN"),
                    "broker-clock-policy": result.get("recorded_clock_policy", "UNKNOWN"),
                    "broker-quote-freshness": result.get("quote_freshness", "UNVERIFIED"),
                }
            except Exception:
                states = {
                    "broker-journal": "UNAVAILABLE",
                    "broker-transport-at-capture": "UNKNOWN",
                    "broker-clock-policy": "UNKNOWN",
                    "broker-quote-freshness": "UNVERIFIED",
                }
            with self.app.repo.lock:
                self.app.monitor.transitions(
                    states,
                    self.app.clock.now(),
                    {"default": "BROKER_JOURNAL_SAMPLE"},
                )
        self.app.notifications.pump()
        with self.app.repo.lock, self.app.repo.conn:
            now = self.app.clock.now()
            self.app.monitor.read(now)
            self.app.repo.conn.execute(
                "INSERT INTO service_heartbeat VALUES (1,?) ON CONFLICT(singleton) DO "
                "UPDATE SET at=excluded.at",
                (now.isoformat(),),
            )
            self.last_success = now
            self.failed = False

    def status(self):
        with self.app.repo.lock:
            row = self.app.repo.conn.execute(
                "SELECT at FROM service_heartbeat WHERE singleton=1"
            ).fetchone()
        age = (
            (self.app.clock.now() - datetime.fromisoformat(row[0])).total_seconds() if row else None
        )
        alive = self.thread is not None and self.thread.is_alive()
        status = (
            "RECENT"
            if alive
            and self.last_success is not None
            and not self.failed
            and age is not None
            and 0 <= age <= 3 * self.interval
            else "UNAVAILABLE"
        )
        return dict(
            status=status,
            worker_running=alive,
            last_sample_at=row[0] if row else None,
            interval_seconds=self.interval,
            sustained_qualification=False,
        )

    def start(self):
        if self.thread is not None:
            raise ValueError("worker already started")

        def run():
            while not self._stop.is_set():
                try:
                    self.sample()
                except Exception:
                    self.failed = True
                self._stop.wait(self.interval)

        self.thread = threading.Thread(target=run, name="dashboard-inspection", daemon=True)
        self.thread.start()

    def stop(self):
        self._stop.set()
        if self.thread:
            self.thread.join(15)
            if self.thread.is_alive():
                raise RuntimeError("inspection worker did not stop")
