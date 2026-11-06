"""Separate local inspection journal; never opens an execution database."""

import sqlite3
from threading import RLock

from fx_talanta.domain.models import Record
from fx_talanta.storage.repository import RecordConflict


class InspectionJournal:
    def __init__(self, path, snapshot):
        self.account = snapshot.account
        self.sources = {r.record_id: r for r in snapshot.records}
        self.lock = RLock()
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.execute("CREATE TABLE IF NOT EXISTS records (id TEXT PRIMARY KEY, payload TEXT)")
        self.conn.execute("CREATE TABLE IF NOT EXISTS binding (snapshot TEXT NOT NULL)")
        identity = snapshot.model_dump_json()
        row = self.conn.execute("SELECT snapshot FROM binding").fetchone()
        if row and row[0] != identity:
            self.conn.close()
            raise ValueError("inspection journal belongs to another snapshot")
        if not row:
            self.conn.execute("INSERT INTO binding VALUES (?)", (identity,))
            self.conn.commit()

    def get(self, rid):
        with self.lock:
            if rid in self.sources:
                return self.sources[rid]
            row = self.conn.execute(
                "SELECT payload FROM records WHERE id=?", (str(rid),)
            ).fetchone()
            if row is None:
                raise KeyError(rid)
            record = Record.model_validate_json(row[0])
            if record.account != self.account:
                raise PermissionError("journal account mismatch")
            return record

    def append_batch(self, records):
        with self.lock, self.conn:
            for r in records:
                r = Record.model_validate(r.model_dump(mode="json"))
                if r.account != self.account or r.body.kind != "message":
                    raise PermissionError("inspection journal accepts only scoped advisor receipts")
                try:
                    old = self.get(r.record_id)
                except KeyError:
                    old = None
                if old:
                    if old != r:
                        raise RecordConflict("immutable inspection receipt")
                else:
                    self.conn.execute(
                        "INSERT INTO records VALUES (?,?)", (str(r.record_id), r.model_dump_json())
                    )

    def close(self):
        self.conn.close()
