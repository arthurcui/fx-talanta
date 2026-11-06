"""Read-only, pinned matched-workflow view; never registers or advances a study."""

import json
from pathlib import Path

from fx_talanta.domain.models import FrozenModel, Hash
from fx_talanta.evaluation.ledger import Ledger


class WorkflowConfig(FrozenModel):
    journal: str
    plan_hash: Hash


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

    def read(self, clock):
        try:
            with self.repo.lock:
                row = self.repo.conn.execute("SELECT seq,sha FROM workflow_cursor").fetchone()
                checkpoint = tuple(row) if row and row[0] is not None else None
                result = Ledger(self.config.journal, clock).report(
                    self.config.plan_hash, checkpoint
                )
                with self.repo.conn:
                    self.repo.conn.execute(
                        "UPDATE workflow_cursor SET seq=?,sha=?",
                        (result["receipt_sequence"], result["receipt_hash"]),
                    )
            # Large artifact/snapshot content and full raw samples are never sent to UI.
            result.pop("study")
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
