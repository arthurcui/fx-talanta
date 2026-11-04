"""Account-wide authority for no-order shadow sessions and explicit peer handoff.

There is no sender or execution permission here. PostgreSQL serializes independent
processes through a deterministic account stream. A lease is never adopted after
expiry: the old owner must be explicitly retired with paired journal evidence.
SQLiteStore is a single-file reference fixture, not a distributed authority.
"""

from contextlib import contextmanager
from dataclasses import asdict, dataclass
from uuid import NAMESPACE_URL, uuid5

from fx_talanta.shadow.store import Events, PostgresStore, canonical
from fx_talanta.shadow.wire import digest, hex64, integer
from fx_talanta.shadow.work import parse_receipt, scope_for


@dataclass(frozen=True)
class PeerCheckpoint:
    scope: str
    journal_hash: str
    sequence: int
    receipt_hash: str
    acknowledged: bool = True

    def __post_init__(self):
        if (
            not all(hex64(v) for v in (self.scope, self.journal_hash, self.receipt_hash))
            or type(self.sequence) is not int
            or self.sequence < 0
            or type(self.acknowledged) is not bool
            or (self.sequence == 0 and self.receipt_hash != "0" * 64)
        ):
            raise ValueError("INVALID_PEER_CHECKPOINT")


@dataclass(frozen=True)
class PairCheckpoint:
    backend: PeerCheckpoint
    native: PeerCheckpoint

    def __post_init__(self):
        if (
            not isinstance(self.backend, PeerCheckpoint)
            or not isinstance(self.native, PeerCheckpoint)
            or (self.backend.scope, self.backend.sequence, self.backend.receipt_hash)
            != (self.native.scope, self.native.sequence, self.native.receipt_hash)
            or not self.backend.acknowledged
        ):
            raise ValueError("PEER_CHECKPOINT_MISMATCH")

    @classmethod
    def match(cls, backend, native):
        return cls(backend, native)

    @property
    def fingerprint(self):
        # Native acknowledged=False is retained: retirement cannot invent an ACK.
        return digest(canonical(asdict(self)))


def backend_checkpoint(store, scope):
    """Read an actual hash-verified backend stream; accept only known receipt domains."""
    with store.transaction() as events:
        if (
            not events.records
            or events.records[0].get("kind") != "binding"
            or events.records[0].get("scope") != scope
            or any(e.get("execution_enabled") is not False for e in events.records)
        ):
            raise ValueError("BACKEND_CHECKPOINT_BINDING")
        works, sequence, receipt_hash = {}, 0, "0" * 64
        for event in events.records[1:]:
            if event["kind"] == "work":
                fields = event["work"].split("\t")
                if len(fields) < 5 or fields[1] in works:
                    raise ValueError("BACKEND_CHECKPOINT_WORK")
                works[fields[1]] = event["work"]
            elif event["kind"] == "receipt":
                receipt = event["receipt"]
                fields = receipt.split("\t")
                if len(fields) < 4 or fields[1] not in works:
                    raise ValueError("BACKEND_CHECKPOINT_RECEIPT")
                work = works[fields[1]]
                original = work.split("\t")
                if fields[0] == "shadow-receipt/1":
                    parse_receipt(receipt, work)
                    current = integer(fields[3])
                elif fields[0] == "connected-hold/1":
                    if (
                        len(fields) != 12
                        or fields[-1] != "0"
                        or len(original) != 14
                        or original[0] != "connected-observation/1"
                        or original[2] != fields[2]
                        or original[3] != scope
                        or not hex64(fields[3])
                        or original[4] != fields[3]
                    ):
                        raise ValueError("BACKEND_CHECKPOINT_RECEIPT")
                    current = integer(fields[2])
                else:
                    raise ValueError("UNSUPPORTED_CHECKPOINT_RECEIPT")
                if current != sequence + 1:
                    raise ValueError("BACKEND_CHECKPOINT_SEQUENCE")
                sequence, receipt_hash = current, digest(receipt)
        return PeerCheckpoint(scope, events.tip, sequence, receipt_hash)


@dataclass(frozen=True)
class Lease:
    scope: str
    client: str
    incarnation: str
    epoch: int
    expires_ms: int


class PostgresAuthorityStore(PostgresStore):
    """Fixed stream and account lock; callers cannot select another lease stream."""

    def __init__(self, dsn, account, *, reuse_connection=False):
        scope = scope_for(account)
        super().__init__(
            dsn,
            account,
            uuid5(NAMESPACE_URL, "fx-shadow-authority/1/" + scope),
            reuse_connection=reuse_connection,
        )

    @contextmanager
    def transaction(self):
        with self.connection() as db:
            db.execute("SET LOCAL statement_timeout='2000ms'")
            db.execute("SET LOCAL lock_timeout='1000ms'")
            row = db.execute("SELECT identity,execution_enabled FROM fx.account_binding").fetchone()
            if row != (self.account.model_dump(mode="json"), False):
                raise ValueError("ACCOUNT_BINDING_MISMATCH")
            scope = scope_for(self.account)
            db.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                ("fx-shadow-authority/1/" + scope,),
            )
            rows = db.execute(
                "SELECT seq,body,prior,hash FROM fx.shadow_events WHERE stream=%s ORDER BY seq",
                (self.stream,),
            ).fetchall()

            def insert(seq, body, prior, hashed):
                db.execute(
                    "INSERT INTO fx.shadow_events VALUES (%s,%s,%s,%s,%s,%s)",
                    (self.stream, seq, scope, body, prior, hashed),
                )

            yield Events(rows, insert)


class Authority:
    def __init__(self, store, account, *, bootstrap=False, expected_tip=None):
        if account.environment.value != "PAPER":
            raise ValueError("PAPER_REQUIRED")
        if isinstance(store, PostgresStore) and not isinstance(store, PostgresAuthorityStore):
            raise ValueError("ACCOUNT_AUTHORITY_STORE_REQUIRED")
        self.store, self.scope = store, scope_for(account)
        self.binding = dict(
            kind="binding",
            scope=self.scope,
            authority="shadow-authority/1",
            execution_enabled=False,
        )
        with store.transaction() as events:
            if not events.records:
                if not bootstrap or expected_tip is not None:
                    raise ValueError("MISSING_AUTHORITY")
                events.append(self.binding)
            elif bootstrap or events.records[0] != self.binding:
                raise ValueError("AUTHORITY_BINDING_CONFLICT")
            if expected_tip is not None and events.tip != expected_tip:
                raise ValueError("AUTHORITY_CHECKPOINT_CONFLICT")

    def _state(self, events, now):
        if not events.records or events.records[0] != self.binding:
            raise ValueError("AUTHORITY_BINDING_CONFLICT")
        if type(now) is not int or now < 0:
            raise ValueError("INVALID_CLOCK")
        if len(events.records) > 1 and now < events.records[-1]["at_ms"]:
            raise ValueError("CLOCK_REGRESSION")
        state = None
        for item in events.records[1:]:
            if item["kind"] in {"claim", "renew", "retire"}:
                state = item
        return state

    def _owner(self, state, client, incarnation, epoch):
        if (
            state is None
            or state["kind"] == "retire"
            or (state["client"], state["incarnation"], state["epoch"])
            != (client, incarnation, epoch)
        ):
            raise ValueError("NOT_AUTHORITY_OWNER")

    def _valid(self, state, client, incarnation, epoch, now):
        self._owner(state, client, incarnation, epoch)
        if now >= state["expires_ms"]:
            raise ValueError("LEASE_EXPIRED")

    def _lease(self, state):
        return Lease(
            self.scope, state["client"], state["incarnation"], state["epoch"], state["expires_ms"]
        )

    @staticmethod
    def _ttl(value):
        if type(value) is not int or not 1000 <= value <= 15000:
            raise ValueError("INVALID_LEASE_DURATION")

    def claim(self, client, incarnation, now_ms, *, lease_ms=15000, checkpoint=None):
        if not hex64(client) or not hex64(incarnation):
            raise ValueError("INVALID_OWNER")
        self._ttl(lease_ms)
        with self.store.transaction() as events:
            state = self._state(events, now_ms)
            epoch = 1
            if state is not None:
                if state["kind"] != "retire":
                    raise ValueError("EXPLICIT_RETIREMENT_REQUIRED")
                if (
                    not isinstance(checkpoint, PairCheckpoint)
                    or checkpoint.fingerprint != state["checkpoint_hash"]
                    or incarnation == state["incarnation"]
                ):
                    raise ValueError("HANDOFF_CHECKPOINT_MISMATCH")
                epoch = state["epoch"] + 1
            elif checkpoint is not None:
                raise ValueError("UNEXPECTED_HANDOFF")
            state = dict(
                kind="claim",
                client=client,
                incarnation=incarnation,
                epoch=epoch,
                expires_ms=now_ms + lease_ms,
                at_ms=now_ms,
                execution_enabled=False,
            )
            events.append(state)
            return self._lease(state)

    def renew(self, client, incarnation, epoch, now_ms, *, lease_ms=15000):
        self._ttl(lease_ms)
        with self.store.transaction() as events:
            state = self._state(events, now_ms)
            self._valid(state, client, incarnation, epoch, now_ms)
            state = dict(state, kind="renew", at_ms=now_ms, expires_ms=now_ms + lease_ms)
            events.append(state)
            return self._lease(state)

    def check(self, client, incarnation, epoch, now_ms):
        with self.guard(client, incarnation, epoch, lambda: now_ms) as lease:
            return lease

    @contextmanager
    def guard(self, client, incarnation, epoch, clock):
        """Hold authority while performing one bounded no-order operation.

        clock returns a verified conservative current UTC millisecond estimate.
        The caller's clock error must already be included (use the upper bound).
        Database errors escape; callers cannot substitute an offline permission.
        """
        with self.store.transaction() as events:
            started = clock()
            state = self._state(events, started)
            self._valid(state, client, incarnation, epoch, started)
            events.append(dict(kind="checked", at_ms=started, execution_enabled=False))
            yield self._lease(state)
            ended = clock()
            self._state(events, ended)
            self._valid(state, client, incarnation, epoch, ended)
            if ended != started:
                events.append(dict(kind="checked", at_ms=ended, execution_enabled=False))

    @contextmanager
    def guard_receipt(self, client, incarnation, epoch, clock):
        """Permit receipt-only recovery for the unreplaced owner after expiry.

        This must wrap receipt ingestion only, never PULL, publication or renewal.
        Expiry cannot strand a committed native receipt, but retirement/replacement
        still rejects it. The original lease and receipt times are not refreshed.
        """
        with self.store.transaction() as events:
            started = clock()
            state = self._state(events, started)
            self._owner(state, client, incarnation, epoch)
            events.append(dict(kind="receipt_checked", at_ms=started, execution_enabled=False))
            yield self._lease(state)
            ended = clock()
            self._state(events, ended)
            if ended != started:
                events.append(dict(kind="receipt_checked", at_ms=ended, execution_enabled=False))

    def retire(
        self,
        client,
        incarnation,
        epoch,
        now_ms,
        *,
        checkpoint,
        source_retired=False,
        backend_store=None,
    ):
        if (
            not source_retired
            or not isinstance(checkpoint, PairCheckpoint)
            or checkpoint.backend.scope != self.scope
        ):
            raise ValueError("PAIRED_RETIRED_SOURCE_REQUIRED")
        with self.store.transaction() as events:
            state = self._state(events, now_ms)
            self._owner(state, client, incarnation, epoch)
            self._verify_backend(checkpoint, backend_store)
            events.append(
                dict(
                    state,
                    kind="retire",
                    at_ms=now_ms,
                    expires_ms=now_ms,
                    checkpoint=asdict(checkpoint),
                    checkpoint_hash=checkpoint.fingerprint,
                )
            )

    def _verify_backend(self, checkpoint, backend_store):
        if backend_store is None:
            if isinstance(self.store, PostgresAuthorityStore):
                raise ValueError("ACTUAL_BACKEND_CHECKPOINT_REQUIRED")
        elif checkpoint.backend != backend_checkpoint(backend_store, self.scope):
            raise ValueError("BACKEND_CHECKPOINT_CHANGED")

    def verify_restore(self, checkpoint, *, expected_tip, backend_store=None):
        """Compare a restored authority with independently retained peer evidence.

        This never releases a database restore guard or changes peer journals.
        The old source must already be explicitly retired. An active lease cannot
        be restored as a new writer merely because its wall-clock deadline passed.
        """
        with self.store.transaction() as events:
            if events.tip != expected_tip:
                raise ValueError("AUTHORITY_CHECKPOINT_CONFLICT")
            state = self._state(events, events.records[-1].get("at_ms", 0))
            if (
                state is None
                or state["kind"] != "retire"
                or not isinstance(checkpoint, PairCheckpoint)
                or checkpoint.fingerprint != state["checkpoint_hash"]
            ):
                raise ValueError("RESTORE_CHECKPOINT_MISMATCH")
            self._verify_backend(checkpoint, backend_store)
            return True

    def tip(self):
        with self.store.transaction() as events:
            if not events.records or events.records[0] != self.binding:
                raise ValueError("AUTHORITY_BINDING_CONFLICT")
            return events.tip
