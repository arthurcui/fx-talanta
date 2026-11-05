"""Ephemeral, deterministic research journal; accepts only simulator accounts.

No database credentials, network connection or durable mutation authority. The
replay command exports this journal; this adapter does not claim crash recovery.
"""

import json
from hashlib import sha256
from uuid import uuid5

from fx_talanta.domain.models import Record
from fx_talanta.domain.offline import BrokerBook, GatewayBook
from fx_talanta.storage.repository import AccountMismatch, RecordConflict


class ReplayStore:
    def __init__(self, account, run_id, clock):
        if account.environment != "PAPER" or account.venue != "SIMULATOR":
            raise AccountMismatch("replay requires PAPER/SIMULATOR")
        self.account, self.run_id, self.clock = account, run_id, clock
        self.repo = self
        self.records, self.books, self.journal = {}, {}, []
        self.closed, self.counter = False, 0

    def assert_owner(self):
        if self.closed:
            raise RuntimeError("replay store closed")

    def next_id(self):
        self.assert_owner()
        self.counter += 1
        return uuid5(self.run_id, f"record/{self.counter}")

    def _validated(self, records):
        pending = dict(self.records)
        for record in records:
            record = Record.model_validate_json(record.model_dump_json())
            if record.account != self.account:
                raise AccountMismatch("replay record account mismatch")
            if record.record_id in pending and pending[record.record_id] != record:
                raise RecordConflict("replay record conflict")
            refs = [r.record_id for r in record.references]
            if record.supersedes:
                refs.append(record.supersedes)
            if any(r not in pending for r in refs):
                raise ValueError("missing earlier replay evidence")
            pending[record.record_id] = record
        return pending

    def append_batch(self, records):
        self.assert_owner()
        pending = self._validated(records)
        self._append(
            {
                "stream": "records",
                "event": "APPEND",
                "at": self.clock.now().isoformat(),
                "records": [r.model_dump(mode="json") for r in records],
            }
        )
        self.records = pending

    def get(self, record_id):
        self.assert_owner()
        return self.records[record_id]

    def load(self, stream):
        self.assert_owner()
        return self.books.get(stream)

    def save(self, stream, book, event, records=()):
        self.assert_owner()
        model = {"broker": BrokerBook, "gateway": GatewayBook}[stream]
        book = model.model_validate_json(book.model_dump_json())
        if book.account != self.account:
            raise AccountMismatch("replay book account mismatch")
        pending = self._validated(records)
        payload = {
            "stream": stream,
            "event": event,
            "at": self.clock.now().isoformat(),
            "book": book.model_dump(mode="json"),
            "records": [r.model_dump(mode="json") for r in records],
        }
        self._append(payload)
        self.books[stream], self.records = book, pending

    def _append(self, payload):
        payload["previous"] = self.journal[-1]["hash"] if self.journal else "0" * 64
        digest = sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        self.journal.append({"payload": payload, "hash": digest})

    def close(self):
        self.closed = True
