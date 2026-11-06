"""Read-only presentation service; journal receipts/calendar uploads are isolated writes."""

import hashlib
import json
from contextlib import closing
from datetime import timedelta
from pathlib import Path
from uuid import UUID, uuid4

from fx_talanta import bls_calendar, manual_bls
from fx_talanta.advisor.access import AccessControl, AdvisorAPI, Principal, token_digest
from fx_talanta.advisor.evidence import FIELDS, EvidenceQuery, ReadGrant, project
from fx_talanta.advisor.rationale import from_receipt
from fx_talanta.dashboard.models import Channel
from fx_talanta.dashboard.monitor import Monitor
from fx_talanta.dashboard.store import InspectionJournal
from fx_talanta.dashboard.trace import trace
from fx_talanta.provider_pipeline import Journal

BLOCKERS = [
    "Read-only dashboard: no execution capability is installed in this service.",
    "M1 broker and USD/EUR/JPY provider qualification gaps remain open.",
    "M2 connected fault-matrix and M3 cost/source qualification remain open.",
    "B01 remains REJECT_FOR_PROMOTION; unattended PAPER is not qualified.",
]


class Dashboard:
    def __init__(self, snapshot, state, token, clock, *, telemetry=None, telemetry_run=None):
        self.snapshot, self.state, self.clock = snapshot, Path(state), clock
        self.state.mkdir(parents=True, exist_ok=True)
        if snapshot.captured_at > clock.now():
            raise ValueError("future snapshot")
        self.repo = InspectionJournal(self.state / "inspection.sqlite", snapshot)
        self.token = token
        self.expires_at = clock.now() + timedelta(hours=8)
        self.access = AccessControl(
            (
                Principal(
                    actor_id="local-viewer",
                    account=snapshot.account,
                    expires_at=self.expires_at,
                    permissions=("read",),
                    token_sha256=token_digest(token),
                ),
            )
        )
        self.advisor = AdvisorAPI(self.access, self.repo, clock)  # No gateway or provider.
        self.repo.conn.execute(
            "CREATE TABLE IF NOT EXISTS chats (id TEXT PRIMARY KEY, fingerprint TEXT, result TEXT)"
        )
        self.repo.conn.commit()
        try:
            self.monitor = Monitor(self.repo, telemetry, telemetry_run)
        except Exception:
            self.repo.close()
            raise

    def authorize(self, token):
        self.access.verify(token, self.snapshot.account, "read", self.clock.now())

    def overview(self):
        now = self.clock.now()
        feed, observed = self.monitor.read(now)
        channels = {c.name: c for c in (self.snapshot.channels if observed is None else observed)}
        metrics = [channels.get(n, Channel(name=n)).metrics(now) for n in ("EA", "Python", "MCP")]
        if feed["status"] in {"MISSING", "INVALID", "STALE"}:
            for metric in metrics:
                metric["freshness"] = "SOURCE_UNAVAILABLE"
                metric["telemetry_status"] = feed["status"]
        calendar = manual_bls.status(self.state / "calendar", clock=self.clock.now)
        states = {
            "telemetry-source": feed["status"],
            "calendar-review": "DUE" if calendar["reminder_due"] else "NOT_DUE",
        }
        for metric in metrics:
            states[metric["name"] + "-quotes"] = metric["freshness"]
            states[metric["name"] + "-connection"] = metric["connection"]
            states[metric["name"] + "-telemetry"] = metric["telemetry_status"]
        incidents = self.monitor.transitions(
            states,
            now,
            {
                "default": feed.get("sha256")
                or hashlib.sha256(self.snapshot.model_dump_json().encode()).hexdigest(),
                "calendar-review": calendar.get("source_hash", "NO_UPLOAD"),
            },
        )
        records = []
        lessons = {}
        lesson_ids = [r.record_id for r in self.snapshot.records if r.body.kind == "lesson"]
        for i in range(0, len(lesson_ids), 32):
            receipt = project(
                self.snapshot.records,
                ReadGrant(
                    actor_id="dashboard-view",
                    account=self.snapshot.account,
                    expires_at=now + timedelta(seconds=1),
                ),
                EvidenceQuery(
                    account=self.snapshot.account,
                    as_of=self.snapshot.captured_at,
                    record_ids=tuple(lesson_ids[i : i + 32]),
                ),
                now=now,
            )
            lessons.update({str(c.record_id): c.memory_eligible for c in receipt.citations})
        for r in reversed(self.snapshot.records):
            if r.body.kind not in FIELDS:
                continue
            body = r.body.model_dump(mode="json")
            records.append(
                dict(
                    id=str(r.record_id),
                    kind=r.body.kind,
                    at=r.recorded_at.isoformat(),
                    provenance=r.provenance,
                    facts={k: body[k] for k in FIELDS[r.body.kind]},
                    sha256=hashlib.sha256(r.model_dump_json().encode()).hexdigest(),
                    supersedes=str(r.supersedes) if r.supersedes else None,
                    memory_eligible=lessons.get(str(r.record_id), False),
                )
            )
        return dict(
            label=self.snapshot.label,
            source=self.snapshot.source,
            captured_at=self.snapshot.captured_at.isoformat(),
            server_at=now.isoformat(),
            execution_enabled=False,
            entry_ceiling_ms=2000,
            observer_ceiling_ms=5000,
            blockers=BLOCKERS,
            records=records,
            positions_status="NOT_RECONCILED",
            channels=metrics,
            telemetry_source=feed,
            incidents=incidents,
            calendar=calendar,
            calendar_events=self.calendar_events(now),
            advisor_mode="M4_EVIDENCE_READER_NO_MODEL",
            session_expires_at=self.expires_at.isoformat(),
        )

    def trace(self, record_id):
        return trace(self.snapshot, record_id)

    def incidents(self, query="", before=None):
        if len(query) > 128 or (before is not None and before < 1):
            raise ValueError("invalid incident filter")
        with self.repo.lock:
            # instr uses literal matching: user '%' and '_' are not SQL wildcards.
            where = "instr(lower(kind || ' ' || state || ' ' || evidence), lower(?)) > 0"
            total = self.repo.conn.execute(
                "SELECT count(*) FROM incidents WHERE " + where, (query,)
            ).fetchone()[0]
            cursor = " AND seq < ?" if before is not None else ""
            args = (query, before) if before is not None else (query,)
            rows = self.repo.conn.execute(
                "SELECT seq,kind,state,at,evidence FROM incidents WHERE "
                + where
                + cursor
                + " ORDER BY seq DESC LIMIT 101",
                args,
            ).fetchall()
            shown = rows[:100]
            return dict(
                total=total,
                shown=len(shown),
                next_before=shown[-1][0] if len(rows) > 100 else None,
                events=[
                    dict(zip(("id", "kind", "state", "at", "evidence"), r, strict=True))
                    for r in shown
                ],
            )

    def report(self):
        overview = self.overview()
        overview.pop("session_expires_at")
        payload = dict(
            version="dashboard-inspection-report/1",
            scope="OFFLINE_INSPECTION_NOT_QUALIFICATION",
            snapshot_sha256=hashlib.sha256(self.snapshot.model_dump_json().encode()).hexdigest(),
            overview=overview,
            limits=dict(records=1000, incident_events=100, calendar_events=100),
            execution_enabled=False,
        )
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        return dict(
            payload=payload,
            sha256=hashlib.sha256(canonical.encode()).hexdigest(),
            hash_encoding="UTF-8 JSON sorted keys, compact separators, ensure_ascii=true",
        )

    def calendar_events(self, now):
        path = self.state / "calendar" / "journal.sqlite"
        if not path.exists():
            return dict(total=0, shown=0, events=[])
        with closing(Journal(path)) as journal:
            value = manual_bls.latest(journal)
            events = (
                sorted(
                    (e for e in value.events if e.scheduled_at >= now), key=lambda e: e.scheduled_at
                )
                if value
                else []
            )
            return dict(
                total=len(events),
                shown=min(100, len(events)),
                events=[
                    dict(
                        release=bls_calendar.RELEASES[e.release_id],
                        scheduled_at=e.scheduled_at.isoformat(),
                        status=e.status,
                        uid=e.uid,
                        source_hash=value.source_hash,
                    )
                    for e in events[:100]
                ],
            )

    def history(self):
        with self.repo.lock:
            rows = self.repo.conn.execute(
                "SELECT result FROM chats ORDER BY rowid DESC LIMIT 50"
            ).fetchall()
            total = self.repo.conn.execute("SELECT count(*) FROM chats").fetchone()[0]
            return dict(
                total=total, shown=len(rows), answers=[json.loads(r[0]) for r in reversed(rows)]
            )

    def chat(self, data):
        if not isinstance(data, dict) or set(data) != {
            "request_id",
            "question",
            "record_id",
            "language",
        }:
            raise ValueError("invalid chat request")
        rid = UUID(data["request_id"])
        question = data["question"]
        if not isinstance(question, str) or not 1 <= len(question.strip()) <= 512:
            raise ValueError("question length")
        if data["language"] not in ("en", "zh"):
            raise ValueError("unsupported language")
        fingerprint = hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()
        # Serialization and immutable receipts make a retry an inspection, not new work.
        with self.repo.lock:
            previous = self.repo.conn.execute(
                "SELECT fingerprint,result FROM chats WHERE id=?", (str(rid),)
            ).fetchone()
            if previous:
                if previous[0] != fingerprint:
                    raise ValueError("request id conflict")
                return json.loads(previous[1])
            result = self._answer(data, rid)
            self.repo.conn.execute(
                "INSERT INTO chats VALUES (?,?,?)", (str(rid), fingerprint, json.dumps(result))
            )
            self.repo.conn.commit()
            return result

    def _answer(self, data, rid):
        zh = data["language"] == "zh"
        text = data["question"].strip().lower()
        result = dict(
            mode="M4 evidence reader · no model calls",
            citations=[],
            execution_enabled=False,
            request_id=str(rid),
            answered_at=self.clock.now().isoformat(),
        )
        if data["record_id"]:
            record_id = UUID(data["record_id"])
            if record_id not in self.repo.sources:
                raise ValueError("record not in selected snapshot")
            query = EvidenceQuery(
                account=self.snapshot.account,
                as_of=self.snapshot.captured_at,
                record_ids=(record_id,),
            )
            receipt = self.advisor.read(
                self.token, query, conversation_id=rid, request_id=rid, language=data["language"]
            )
            result["citations"] = [c.model_dump(mode="json") for c in receipt.citations]
            result["text"] = (
                "以下仅为所选记录的证据，不推断当前账户状态。"
                if zh
                else "Evidence for the selected record only; "
                "this does not establish current account status."
            )
            if receipt.citations and receipt.citations[0].kind == "decision":
                original = from_receipt(self.repo, receipt, record_id)
                result["rationale"] = original.original_recorded_rationale
                result["rationale_label"] = original.label
                result["validation_reason"] = original.recorded_validation_reason
            if not receipt.citations:
                result["text"] = "No visible evidence at this cutoff."
        elif any(k in text for k in ("quote", "latency", "channel", "行情", "延迟", "通道")):
            result["text"] = (
                "报价年龄按原始报价时间计算；传输延迟是接收时间减报价时间。连接正常不代表报价新鲜。"
                if zh
                else "Quote age uses the original quote timestamp. "
                "Transport delay is receipt minus quote time. "
                "A connected channel does not prove a fresh quote."
            )
            result["channels"] = self.overview()["channels"]
        elif any(k in text for k in ("blocked", "disabled", "why", "为什么", "禁用", "risk")):
            result["text"] = (
                "交易已禁用。此界面没有下单功能；资格缺口仍然保留。"
                if zh
                else "Trading is disabled. This dashboard has no order route. "
                "Qualification gaps remain open."
            )
            result["blockers"] = BLOCKERS
        else:
            result["text"] = (
                "请选择一条记录查看证据，或询问报价延迟与交易阻止原因。此界面不执行交易指令。"
                if zh
                else "Select a journal record to inspect its evidence, "
                "or ask about quote latency or blocked trading. "
                "This evidence reader does not interpret trading advice or execute commands."
            )
        return result

    def upload_calendar(self, raw):
        # Browser supplies bytes, never a filesystem path. Existing importer validates and archives.
        if len(raw) > bls_calendar.LIMIT:
            raise ValueError("calendar too large")
        path = self.state / (uuid4().hex + ".ics")
        try:
            path.write_bytes(raw)
            return manual_bls.upload(self.state / "calendar", path, clock=self.clock.now)
        finally:
            path.unlink(missing_ok=True)

    def close(self):
        self.repo.close()
