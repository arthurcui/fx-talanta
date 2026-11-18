"""Ephemeral, deterministic research journal; accepts only simulator accounts.

No database credentials, network connection or durable mutation authority. The
replay command exports this journal; this adapter does not claim crash recovery.
"""

import json
from copy import deepcopy
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
        self.compact = False
        self._core = None
        self._compact_previous = {}

    def assert_owner(self):
        if self.closed:
            raise RuntimeError("replay store closed")

    def next_id(self):
        self.assert_owner()
        self.counter += 1
        return uuid5(self.run_id, f"record/{self.counter}")

    def _validated(self, records):
        if self.compact and not records:
            return self.records
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
        original = book
        core_fields = {"account", "policy", "entries", "operations"}
        cache = self._core
        reuse = (
            self.compact
            and stream == "gateway"
            and cache is not None
            and all(getattr(original, k) is cache["refs"][k] for k in core_fields)
            and all(value == snapshot for value, snapshot in cache["guards"])
        )
        if reuse:
            dynamic = json.loads(original.model_dump_json(exclude=core_fields))
            book = model.model_validate({**dynamic, **cache["validated"]})
            encoded_book = {**book.model_dump(mode="json", exclude=core_fields), **cache["encoded"]}
        else:
            book = model.model_validate_json(book.model_dump_json())
            encoded_book = book.model_dump(mode="json")
            if self.compact and stream == "gateway":
                refs = {k: getattr(original, k) for k in core_fields}
                guards = []

                def guard(value):
                    if isinstance(value, dict):
                        guards.append((value, deepcopy(value)))
                    elif isinstance(value, (tuple, list)):
                        for child in value:
                            guard(child)
                    elif hasattr(type(value), "model_fields"):
                        for name in type(value).model_fields:
                            guard(getattr(value, name))

                for value in refs.values():
                    guard(value)
                self._core = dict(
                    refs=refs,
                    guards=guards,
                    validated={k: getattr(book, k) for k in core_fields},
                    encoded={k: encoded_book[k] for k in core_fields},
                )
        if book.account != self.account:
            raise AccountMismatch("replay book account mismatch")
        pending = self._validated(records)
        payload = {
            "stream": stream,
            "event": event,
            "at": self.clock.now().isoformat(),
            "book": encoded_book,
            "records": [r.model_dump(mode="json") for r in records],
        }
        if self.compact:
            payload["encoding"] = "book-delta/1"
            previous = self._compact_previous.get(stream)
            if previous is not None:
                payload.pop("book")
                payload["book_delta"] = {
                    k: value for k, value in encoded_book.items() if previous.get(k) != value
                }
                payload["book_removed"] = sorted(set(previous) - set(encoded_book))
            self._compact_previous[stream] = encoded_book
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


def reconstruct_books(journal):
    """Expand versioned deltas to exact snapshots without dropping events."""
    books = {}
    for record in journal:
        payload = dict(record["payload"])
        stream = payload["stream"]
        if "book_delta" in payload:
            if payload.get("encoding") != "book-delta/1" or stream not in books:
                raise ValueError("audit delta has no preceding checkpoint")
            book = dict(books[stream])
            for key in payload.pop("book_removed"):
                if key not in book:
                    raise ValueError("audit delta removes unknown field")
                book.pop(key)
            book.update(payload.pop("book_delta"))
            payload["book"] = book
        if "book" in payload:
            books[stream] = payload["book"]
        yield {**record, "payload": payload}
