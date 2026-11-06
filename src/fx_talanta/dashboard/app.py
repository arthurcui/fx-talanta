"""Read-only presentation service; journal receipts/calendar uploads are isolated writes."""

import hashlib
import json
from datetime import timedelta
from pathlib import Path
from uuid import UUID, uuid4

from fx_talanta import bls_calendar, manual_bls
from fx_talanta.advisor.access import AccessControl, AdvisorAPI, Principal, token_digest
from fx_talanta.advisor.evidence import FIELDS, EvidenceQuery
from fx_talanta.advisor.rationale import from_receipt
from fx_talanta.dashboard.models import Channel
from fx_talanta.dashboard.store import InspectionJournal

BLOCKERS = [
    "Read-only dashboard: no execution capability is installed in this service.",
    "M1 broker and USD/EUR/JPY provider qualification gaps remain open.",
    "M2 connected fault-matrix and M3 cost/source qualification remain open.",
    "B01 remains REJECT_FOR_PROMOTION; unattended PAPER is not qualified.",
]


class Dashboard:
    def __init__(self, snapshot, state, token, clock):
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

    def authorize(self, token):
        self.access.verify(token, self.snapshot.account, "read", self.clock.now())

    def overview(self):
        now = self.clock.now()
        channels = {c.name: c for c in self.snapshot.channels}
        records = []
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
            channels=[
                channels.get(n, Channel(name=n)).metrics(now) for n in ("EA", "Python", "MCP")
            ],
            calendar=manual_bls.status(self.state / "calendar", clock=self.clock.now),
            advisor_mode="M4_EVIDENCE_READER_NO_MODEL",
            session_expires_at=self.expires_at.isoformat(),
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
