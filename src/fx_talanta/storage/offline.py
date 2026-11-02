"""Session-fenced simulator journal. A lost connection also loses mutation authority."""

from uuid import UUID

import psycopg
from psycopg.types.json import Jsonb

from fx_talanta.clock import Clock
from fx_talanta.domain.models import AccountIdentity, Record
from fx_talanta.domain.offline import BrokerBook, GatewayBook
from fx_talanta.storage.repository import AccountMismatch, Repository

WRITER_LOCK = 640032


class WriterBusy(RuntimeError):
    pass


class OfflineStore:
    def __init__(self, dsn: str, account: AccountIdentity, run_id: UUID, clock: Clock):
        if account.environment != "PAPER" or account.venue != "SIMULATOR":
            raise AccountMismatch("M0B execution requires PAPER/SIMULATOR")
        self.account, self.run_id, self.clock = account, run_id, clock
        self.repo = Repository(dsn, account)
        self.conn = psycopg.connect(dsn, autocommit=True)
        try:
            if not self.conn.execute("SELECT pg_try_advisory_lock(%s)", (WRITER_LOCK,)).fetchone()[
                0
            ]:
                raise WriterBusy("another gateway still owns this account")
            self.assert_owner()
        except BaseException:
            self.conn.close()
            raise

    def assert_owner(self):
        self.repo._check_binding(self.conn)
        owned = self.conn.execute(
            "SELECT 1 FROM pg_locks WHERE locktype='advisory' AND pid=pg_backend_pid() "
            "AND classid=0 AND objid=%s AND objsubid=1 AND granted",
            (WRITER_LOCK,),
        ).fetchone()
        if not owned:
            raise WriterBusy("session no longer owns simulator mutation authority")

    def load(self, stream: str):
        self.assert_owner()
        row = self.conn.execute(
            "SELECT payload FROM fx.offline_journal WHERE run_id=%s AND stream=%s "
            "ORDER BY revision DESC LIMIT 1",
            (self.run_id, stream),
        ).fetchone()
        if not row:
            return None
        model = GatewayBook if stream == "gateway" else BrokerBook
        return model.model_validate(row[0])

    def save(self, stream: str, book, event: str, records: tuple[Record, ...] = ()):
        self.assert_owner()
        model = GatewayBook if stream == "gateway" else BrokerBook
        book = model.model_validate(book.model_dump(mode="json"))
        with self.conn.transaction():
            revision = self.conn.execute(
                "SELECT COALESCE(max(revision),0)+1 FROM fx.offline_journal "
                "WHERE run_id=%s AND stream=%s",
                (self.run_id, stream),
            ).fetchone()[0]
            self.conn.execute(
                "INSERT INTO fx.offline_journal VALUES (%s,%s,%s,%s,%s,%s)",
                (
                    self.run_id,
                    stream,
                    revision,
                    self.clock.now(),
                    event,
                    Jsonb(book.model_dump(mode="json")),
                ),
            )
            self.repo.append_in(self.conn, records)

    def close(self):
        self.conn.close()
