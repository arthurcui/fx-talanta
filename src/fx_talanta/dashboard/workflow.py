"""Read-only, pinned matched-workflow view; never registers or advances a study."""

import json
from pathlib import Path
from typing import Literal

from pydantic import model_serializer

from fx_talanta.domain.models import FrozenModel, Hash
from fx_talanta.evaluation.ledger import Ledger
from fx_talanta.evaluation.operations import Operations
from fx_talanta.evaluation.runner import Runner


class WorkflowConfig(FrozenModel):
    journal: str
    plan_hash: Hash
    source_kind: Literal["RECEIPTS", "RUNNER", "OPERATIONS"] = "RECEIPTS"

    @model_serializer(mode="wrap")
    def compatible_binding(self, handler):
        data = handler(self)
        if self.source_kind == "RECEIPTS":
            data.pop("source_kind", None)
        return data


class WorkflowView:
    def __init__(self, config):
        self.config = WorkflowConfig.model_validate(config)
        self.repo = None

    def bind(self, repo):
        self.repo = repo
        identity = self.config.model_copy(
            update={"journal": str(Path(self.config.journal).resolve())}
        ).model_dump_json()
        with repo.lock, repo.conn:
            repo.conn.execute(
                "CREATE TABLE IF NOT EXISTS workflow_cursor "
                "(binding TEXT NOT NULL, seq INTEGER, sha TEXT)"
            )
            old = repo.conn.execute("SELECT binding FROM workflow_cursor").fetchone()
            if old and old[0] != identity:
                raise ValueError("workflow cannot rebind on resume")
            if not old:
                repo.conn.execute("INSERT INTO workflow_cursor VALUES (?,NULL,NULL)", (identity,))
            repo.conn.execute(
                "CREATE TABLE IF NOT EXISTS source_cursor "
                "(id INTEGER PRIMARY KEY CHECK(id=1), payload TEXT NOT NULL)"
            )

    def read(self, clock):
        try:
            with self.repo.lock:
                row = self.repo.conn.execute("SELECT seq,sha FROM workflow_cursor").fetchone()
                checkpoint = tuple(row) if row and row[0] is not None else None
                source_cursor = None
                if self.config.source_kind == "OPERATIONS":
                    saved = self.repo.conn.execute(
                        "SELECT payload FROM source_cursor WHERE id=1"
                    ).fetchone()
                    source = Operations(self.config.journal, clock).report(
                        self.config.plan_hash, json.loads(saved[0]) if saved else None
                    )
                    result = source.pop("runner")
                    source_cursor = source.pop("checkpoint")
                    result["source_queue"] = source
                else:
                    reader = Runner if self.config.source_kind == "RUNNER" else Ledger
                    result = reader(self.config.journal, clock).report(
                        self.config.plan_hash, checkpoint
                    )
                with self.repo.conn:
                    if source_cursor is not None:
                        self.repo.conn.execute(
                            "INSERT OR REPLACE INTO source_cursor VALUES (1,?)",
                            (json.dumps(source_cursor),),
                        )
                    self.repo.conn.execute(
                        "UPDATE workflow_cursor SET seq=?,sha=?",
                        (result["receipt_sequence"], result["receipt_hash"]),
                    )
            # Large artifact/snapshot content and full raw samples are never sent to UI.
            result.pop("study", None)
            result["source_kind"] = self.config.source_kind
            return result
        except Exception:
            return dict(
                status="UNAVAILABLE",
                result="INVALID_OR_MISSING_RECEIPTS",
                execution_enabled=False,
                qualified_for_unattended_paper=False,
            )

    @classmethod
    def from_file(cls, path):
        with Path(path).open("rb") as stream:
            raw = stream.read(8193)
        if len(raw) > 8192:
            raise ValueError("workflow binding too large")
        return cls(json.loads(raw))
