"""Opt-in alert outbox. Receiver acknowledgement is not human acknowledgement."""

import hashlib
import http.client
import json
import socket
import ssl
import threading
from datetime import datetime
from pathlib import Path
from typing import Annotated
from urllib.parse import urlsplit
from uuid import uuid4

from pydantic import Field, model_validator

from fx_talanta.domain.models import FrozenModel, Timestamp


class AlertConfig(FrozenModel):
    endpoint: str
    token_file: str
    ca_file: str | None = None
    expires_at: Timestamp
    max_messages: Annotated[int, Field(strict=True, ge=1, le=1000)] = 100

    @model_validator(mode="after")
    def exact_endpoint(self):
        url = urlsplit(self.endpoint)
        if (
            url.scheme != "https"
            or not url.hostname
            or url.username
            or url.password
            or url.query
            or url.fragment
            or self.endpoint.endswith("/")
            or url.netloc != url.netloc.lower()
            or any(c.isspace() for c in self.endpoint)
        ):
            raise ValueError("exact HTTPS endpoint required")
        if url.port is not None and not 1 <= url.port <= 65535:
            raise ValueError("invalid endpoint port")
        return self


class ReceiverHTTPError(ValueError):
    def __init__(self, status):
        self.status = status
        super().__init__("receiver did not confirm")


class HTTPSReceiver:
    def __init__(self, config):
        self.config = config
        with Path(config.token_file).open("rb") as stream:
            raw = stream.read(4097)
        self.token = raw.decode("ascii").strip()
        if (
            len(raw) > 4096
            or not 32 <= len(self.token) <= 4096
            or any(not 33 <= ord(c) <= 126 for c in self.token)
        ):
            raise ValueError("invalid private receiver token")
        context = ssl.create_default_context(cafile=config.ca_file)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        self.context = context

    def request(self, method, payload, digest):
        url = urlsplit(self.config.endpoint)
        path = url.path or "/"
        if method == "GET":
            path = path.rstrip("/") + "/receipts/" + payload["id"]
        conn = http.client.HTTPSConnection(
            url.hostname, url.port or 443, timeout=3, context=self.context
        )
        timer = None
        try:
            conn.connect()  # Default certificate/hostname verification; never follows redirects.
            sock = conn.sock

            def abort():
                try:
                    sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass

            timer = threading.Timer(4, abort)
            timer.daemon = True
            timer.start()
            conn.request(
                method,
                path,
                body=json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
                if method == "POST"
                else None,
                headers={
                    "Authorization": "Bearer " + self.token,
                    "Content-Type": "application/json",
                    "Idempotency-Key": payload["id"],
                    "X-FX-Content-SHA256": digest,
                },
            )
            response = conn.getresponse()
            if response.status != 200:
                raise ReceiverHTTPError(response.status)
            raw = response.read(4097)
            if len(raw) > 4096:
                raise ValueError("receiver reply too large")
            return json.loads(raw)
        finally:
            if timer:
                timer.cancel()
            conn.close()


class AlertDelivery:
    def __init__(self, app, config, transport=None):
        self.app, self.config = app, AlertConfig.model_validate(config)
        self.lock = threading.Lock()
        self.failed = False
        self.transport = transport or HTTPSReceiver(self.config)
        binding = self.config.model_dump(mode="json")
        binding["ca_sha256"] = (
            hashlib.sha256(Path(self.config.ca_file).read_bytes()).hexdigest()
            if self.config.ca_file
            else None
        )
        self.binding = hashlib.sha256(json.dumps(binding, sort_keys=True).encode()).hexdigest()
        repo = app.repo
        with repo.lock, repo.conn:
            repo.conn.executescript("""
                CREATE TABLE IF NOT EXISTS alert_binding(binding TEXT NOT NULL,
                    watermark INTEGER NOT NULL,
                    last_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS alert_delivery(incident INTEGER PRIMARY KEY,
                    id TEXT UNIQUE NOT NULL,
                    payload TEXT NOT NULL,digest TEXT NOT NULL,state TEXT NOT NULL,
                    checks INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS alert_events(seq INTEGER PRIMARY KEY,
                    incident INTEGER NOT NULL,at TEXT NOT NULL,state TEXT NOT NULL,
                    method TEXT NOT NULL,receipt_sha TEXT,reason TEXT NOT NULL);
                CREATE TRIGGER IF NOT EXISTS alert_events_no_update BEFORE UPDATE ON alert_events
                    BEGIN SELECT RAISE(ABORT,'immutable delivery history'); END;
                CREATE TRIGGER IF NOT EXISTS alert_events_no_delete BEFORE DELETE ON alert_events
                    BEGIN SELECT RAISE(ABORT,'immutable delivery history'); END;
            """)
            old = repo.conn.execute("SELECT binding,last_at FROM alert_binding").fetchone()
            if old and old[0] != self.binding:
                raise ValueError("alert destination or policy cannot rebind on resume")
            if old and app.clock.now() < datetime.fromisoformat(old[1]):
                raise ValueError("clock rollback; alert resume refused")
            if not old:
                if app.clock.now() >= self.config.expires_at:
                    raise ValueError("alert authority already expired")
                watermark = repo.conn.execute(
                    "SELECT coalesce(max(seq),0) FROM incidents"
                ).fetchone()[0]
                repo.conn.execute(
                    "INSERT INTO alert_binding VALUES (?,?,?)",
                    (self.binding, watermark, app.clock.now().isoformat()),
                )
            # A committed send reservation may have reached the receiver. Never repost it.
            for (ident,) in repo.conn.execute(
                "SELECT incident FROM alert_delivery WHERE state='SENDING'"
            ).fetchall():
                self.event(ident, "UNKNOWN", "RECOVERY")
            repo.conn.execute("UPDATE alert_delivery SET state='UNKNOWN' WHERE state='SENDING'")

    def event(self, ident, state, method, receipt_sha=None, reason="STATE_TRANSITION"):
        self.app.repo.conn.execute(
            "INSERT INTO alert_events(incident,at,state,method,receipt_sha,reason) "
            "VALUES (?,?,?,?,?,?)",
            (ident, self.app.clock.now().isoformat(), state, method, receipt_sha, reason),
        )

    def pump(self):
        if not self.lock.acquire(blocking=False):
            return
        try:
            self._pump()
            self.failed = False
        except Exception:
            self.failed = True
            raise
        finally:
            self.lock.release()

    def _pump(self):
        repo = self.app.repo
        now = self.app.clock.now()
        with repo.lock, repo.conn:
            watermark, last_at = repo.conn.execute(
                "SELECT watermark,last_at FROM alert_binding"
            ).fetchone()

            if now < datetime.fromisoformat(last_at):
                raise ValueError("clock rollback; delivery stopped")
            repo.conn.execute("UPDATE alert_binding SET last_at=?", (now.isoformat(),))
            rows = repo.conn.execute(
                "SELECT id,payload,digest FROM notifications WHERE id>? AND delivered=1 "
                "AND id NOT IN (SELECT incident FROM alert_delivery) ORDER BY id LIMIT 10",
                (watermark,),
            ).fetchall()
            used = repo.conn.execute(
                "SELECT count(*) FROM alert_delivery WHERE state!=?", ("LIMIT_REACHED",)
            ).fetchone()[0]
            for ident, original, original_digest in rows:
                if hashlib.sha256(original.encode()).hexdigest() != original_digest:
                    raise ValueError("local spool digest mismatch")
                event = json.loads(original)
                # Do not forward raw incident evidence, account identifiers, quotes, or free text.
                payload = dict(
                    version="fx-alert/1",
                    id=str(uuid4()),
                    incident_id=ident,
                    observed_at=event["at"],
                    message="Inspection state changed; review your dashboard.",
                    source_sha256=original_digest,
                    execution_enabled=False,
                )
                raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
                state = (
                    "EXPIRED"
                    if now >= self.config.expires_at
                    else "QUEUED"
                    if used < self.config.max_messages
                    else "LIMIT_REACHED"
                )
                repo.conn.execute(
                    "INSERT INTO alert_delivery(incident,id,payload,digest,state) "
                    "VALUES (?,?,?,?,?)",
                    (ident, payload["id"], raw, hashlib.sha256(raw.encode()).hexdigest(), state),
                )
                self.event(ident, state, "QUEUE")
                used += state != "LIMIT_REACHED"
            if now >= self.config.expires_at:
                for (ident,) in repo.conn.execute(
                    "SELECT incident FROM alert_delivery WHERE state='QUEUED'"
                ).fetchall():
                    self.event(ident, "EXPIRED", "EXPIRY")
                repo.conn.execute("UPDATE alert_delivery SET state='EXPIRED' WHERE state='QUEUED'")
                return
            # Reconcile only one uncertain receipt per cycle; no network POST retry.
            row = repo.conn.execute(
                "SELECT incident,payload,digest FROM alert_delivery WHERE "
                "state='UNKNOWN' AND checks<3 ORDER BY incident LIMIT 1"
            ).fetchone()
            method = "GET" if row else "POST"
            if not row:
                row = repo.conn.execute(
                    "SELECT incident,payload,digest FROM alert_delivery WHERE "
                    "state='QUEUED' ORDER BY incident LIMIT 1"
                ).fetchone()
            if not row:
                return
            repo.conn.execute(
                "UPDATE alert_delivery SET state=?,checks=checks+? WHERE incident=?",
                ("UNKNOWN" if method == "GET" else "SENDING", int(method == "GET"), row[0]),
            )
            self.event(row[0], "UNKNOWN" if method == "GET" else "SENDING", method)
        ident, raw, sha = row
        result, receipt_sha, reason = "UNKNOWN", None, "ACK_MISMATCH"
        try:
            payload = json.loads(raw)
            if hashlib.sha256(raw.encode()).hexdigest() != sha:
                raise ValueError("outbox digest mismatch")
            reply = self.transport.request(method, payload, sha)
            if (
                isinstance(reply, dict)
                and set(reply) == {"id", "digest", "status"}
                and reply["id"] == payload["id"]
                and reply["digest"] == sha
                and reply["status"] in ("ACCEPTED", "REJECTED")
            ):
                result = "DELIVERED" if reply["status"] == "ACCEPTED" else "REJECTED"
                reason = "RECEIVER_" + reply["status"]
                receipt_sha = hashlib.sha256(
                    json.dumps(reply, sort_keys=True, separators=(",", ":")).encode()
                ).hexdigest()
        except Exception as error:
            # Persist only stable categories, never raw error text or receiver content.
            reason = (
                f"HTTP_{error.status}"
                if isinstance(error, ReceiverHTTPError)
                else "TLS_ERROR"
                if isinstance(error, ssl.SSLError)
                else "TIMEOUT"
                if isinstance(error, TimeoutError)
                else "IO_ERROR"
                if isinstance(error, OSError)
                else "INVALID_REPLY"
                if isinstance(error, ValueError)
                else "TRANSPORT_ERROR"
            )
        if self.app.clock.now() < now:
            result, receipt_sha, reason = "UNKNOWN", None, "CLOCK_ROLLBACK"
        with repo.lock, repo.conn:
            repo.conn.execute("UPDATE alert_delivery SET state=? WHERE incident=?", (result, ident))
            self.event(ident, result, method, receipt_sha, reason)

    def summary(self):
        with self.app.repo.lock:
            rows = self.app.repo.conn.execute(
                "SELECT state,count(*) FROM alert_delivery GROUP BY state"
            ).fetchall()
            last = self.app.repo.conn.execute("SELECT last_at FROM alert_binding").fetchone()[0]
            events = self.app.repo.conn.execute(
                "SELECT seq,incident,at,state,method,receipt_sha,reason FROM alert_events "
                "ORDER BY seq DESC LIMIT 20"
            ).fetchall()
        now = self.app.clock.now()
        return dict(
            status="CLOCK_INVALID"
            if now < datetime.fromisoformat(last)
            else "EXPIRED"
            if now >= self.config.expires_at
            else "UNAVAILABLE"
            if self.failed
            else "ATTENTION_REQUIRED"
            if any(dict(rows).get(k, 0) for k in ("UNKNOWN", "REJECTED", "LIMIT_REACHED"))
            else "CONFIGURED",
            states=dict(rows),
            expires_at=self.config.expires_at.isoformat(),
            max_messages=self.config.max_messages,
            recent=[
                dict(
                    zip(
                        (
                            "sequence",
                            "incident_id",
                            "at",
                            "state",
                            "method",
                            "receipt_sha",
                            "reason",
                        ),
                        row,
                        strict=True,
                    )
                )
                for row in events
            ],
            scope="RECEIVER_ACK_NOT_HUMAN_ACK",
            execution_enabled=False,
        )


def load_config(path):
    with Path(path).open("rb") as stream:
        raw = stream.read(8193)
    if len(raw) > 8192:
        raise ValueError("alert config too large")
    return AlertConfig.model_validate_json(raw)
