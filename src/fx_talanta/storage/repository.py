"""Account-bound append-only repository. Each operation opens a fresh connection."""

from collections.abc import Iterable
from uuid import UUID

import psycopg
from psycopg.types.json import Jsonb

from fx_talanta.domain.models import AccountIdentity, Record


class AccountMismatch(ValueError):
    pass


class RecordConflict(ValueError):
    pass


class Repository:
    def __init__(self, dsn: str, account: AccountIdentity):
        self._dsn = dsn
        self.account = account
        with psycopg.connect(dsn) as conn:
            self._check_binding(conn)

    def _check_binding(self, conn: psycopg.Connection) -> None:
        row = conn.execute("SELECT identity, execution_enabled FROM fx.account_binding").fetchone()
        if not row or row[0] != self.account.model_dump(mode="json") or row[1]:
            raise AccountMismatch("database is not bound to the expected disabled fixture account")

    def append(self, record: Record) -> int:
        return self.append_batch((record,))[0]

    def append_batch(self, records: Iterable[Record]) -> list[int]:
        """Atomic, ordered insertion; identical IDs/payloads are safe to retry."""
        sequences = []
        with psycopg.connect(self._dsn) as conn:
            self._check_binding(conn)
            for candidate in records:
                # Revalidate even model_construct/model_copy inputs from callers.
                record = Record.model_validate(candidate.model_dump(mode="json"))
                if record.account != self.account:
                    raise AccountMismatch("record cannot be routed to this account")
                payload = record.model_dump(mode="json")
                row = conn.execute(
                    "INSERT INTO fx.records(record_id,kind,recorded_at,supersedes,payload) "
                    "VALUES (%s,%s,%s,%s,%s) ON CONFLICT (record_id) DO NOTHING RETURNING sequence",
                    (
                        record.record_id,
                        record.body.kind,
                        record.recorded_at,
                        record.supersedes,
                        Jsonb(payload),
                    ),
                ).fetchone()
                if row:
                    sequences.append(row[0])
                else:
                    existing = conn.execute(
                        "SELECT sequence,payload FROM fx.records WHERE record_id=%s",
                        (record.record_id,),
                    ).fetchone()
                    if existing[1] != payload:
                        raise RecordConflict("record ID already has different immutable content")
                    sequences.append(existing[0])
        return sequences

    def get(self, record_id: UUID) -> Record:
        with psycopg.connect(self._dsn) as conn:
            row = conn.execute(
                "SELECT payload FROM fx.records WHERE record_id=%s", (record_id,)
            ).fetchone()
        if row is None:
            raise KeyError(record_id)
        return Record.model_validate(row[0])

    def history(
        self, *, correlation_id: UUID | None = None, kind: str | None = None
    ) -> list[Record]:
        with psycopg.connect(self._dsn) as conn:
            rows = conn.execute(
                "SELECT payload FROM fx.records WHERE (%s::text IS NULL OR kind=%s) "
                "AND (%s::text IS NULL OR payload->>'correlation_id'=%s) ORDER BY sequence",
                (
                    kind,
                    kind,
                    str(correlation_id) if correlation_id else None,
                    str(correlation_id) if correlation_id else None,
                ),
            ).fetchall()
        return [Record.model_validate(row[0]) for row in rows]

    def news_available(self, cutoff) -> list[Record]:
        """Exact historical versions, including originals; no latest-revision overwrite."""
        with psycopg.connect(self._dsn) as conn:
            rows = conn.execute(
                "SELECT payload FROM fx.records WHERE kind='news' AND recorded_at<=%s "
                "AND (payload#>>'{body,available_at}')::timestamptz<=%s ORDER BY sequence",
                (cutoff, cutoff),
            ).fetchall()
        return [Record.model_validate(row[0]) for row in rows]
