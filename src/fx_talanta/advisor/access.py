"""Local authenticated application API. No listening socket or broker credentials.

The owner provisions high-entropy bearer digests and exact account permissions in
trusted server configuration. Never accept a Principal/ReadGrant from client data.
"""

import hashlib
import hmac
from threading import RLock
from typing import Annotated, Literal

from pydantic import Field

from fx_talanta.advisor.command_gateway import command_snapshot, dispatch_simulated
from fx_talanta.advisor.commands import Action, SimulatedScope
from fx_talanta.advisor.evidence import ReadGrant
from fx_talanta.advisor.journal import read_and_record
from fx_talanta.advisor.service import answer_question
from fx_talanta.domain.models import AccountIdentity, FrozenModel, Identifier, Timestamp, utc


class Principal(FrozenModel):
    actor_id: Identifier
    account: AccountIdentity
    expires_at: Timestamp
    permissions: tuple[Literal["read", "explain", "command", "propose"], ...]
    actions: tuple[Action, ...] = ()
    token_sha256: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$", repr=False)]


def token_digest(token: str) -> str:
    if not isinstance(token, str) or not 32 <= len(token) <= 256 or any(c.isspace() for c in token):
        raise PermissionError("invalid credential")
    return hashlib.sha256(token.encode()).hexdigest()


class AccessControl:
    def __init__(self, principals):
        self._lock = RLock()
        validated = tuple(Principal.model_validate(p.model_dump(mode="json")) for p in principals)
        if len({p.token_sha256 for p in validated}) != len(validated):
            raise ValueError("duplicate credential mapping")
        if any(
            p.account.environment != "PAPER" or p.account.venue != "SIMULATOR" for p in validated
        ):
            raise ValueError("local M4 access is simulator-only")
        self._principals = validated
        self._revoked = set()

    def revoke(self, token_sha256):
        with self._lock:
            self._revoked.add(token_sha256)

    def verify(self, token, account, permission, now):
        digest = token_digest(token)
        now = utc(now)
        with self._lock:
            matches = [p for p in self._principals if hmac.compare_digest(p.token_sha256, digest)]
            if (
                len(matches) != 1
                or digest in self._revoked
                or now >= matches[0].expires_at
                or matches[0].account != account
                or permission not in matches[0].permissions
            ):
                raise PermissionError("access denied")
            return matches[0]


class AdvisorAPI:
    """Private in-process API for a trusted local host, not an internet HTTP server.

    Local process/OS isolation is the transport boundary. Do not expose this API
    over a network without the separate TLS/host deployment boundary.
    """

    def __init__(
        self,
        access,
        repository,
        clock,
        *,
        gateway=None,
        budget=None,
        transport=None,
        proposal_source=None,
        allowed_strategies=(),
    ):
        self.access, self.repository, self.clock, self.gateway = access, repository, clock, gateway
        self._budget, self._transport = budget, transport
        self._proposal_source, self._allowed_strategies = proposal_source, tuple(allowed_strategies)

    def _principal(self, token, permission):
        return self.access.verify(token, self.repository.account, permission, self.clock.now())

    def _audit(self, principal, request_id, permission):
        import json
        from uuid import uuid5

        from fx_talanta.advisor.service import _save
        from fx_talanta.domain.models import ConversationMessage, Record, Versions

        rid = uuid5(request_id, "authenticated/" + permission)
        record = Record(
            record_id=rid,
            account=principal.account,
            recorded_at=self.clock.now(),
            correlation_id=request_id,
            provenance="OFFLINE_SIMULATION",
            versions=Versions(component="m4-authenticated-api/1", model="none", prompt="none"),
            body=ConversationMessage(
                conversation_id=request_id,
                message_id=rid,
                actor_id=principal.actor_id,
                authenticated=True,
                role="USER",
                language="en",
                interpretation="READ_ONLY",
                text=json.dumps(
                    {
                        "permission": permission,
                        "grant_expires_at": principal.expires_at.isoformat(),
                        "simulation_only": True,
                    }
                ),
            ),
        )
        return _save(self.repository, record)

    def read(self, token, query, *, conversation_id, request_id, language="en"):
        p = self._principal(token, "read")
        if query.account != p.account:
            raise PermissionError("query account denied")
        self._audit(p, request_id, "read")
        result = read_and_record(
            self.repository,
            ReadGrant(actor_id=p.actor_id, account=p.account, expires_at=p.expires_at),
            query,
            conversation_id=conversation_id,
            request_id=request_id,
            language=language,
            now=self.clock.now(),
        )
        self._principal(token, "read")
        return result

    def explain(
        self, token, query, question, *, conversation_id, request_id, expires_at, language="en"
    ):
        p = self._principal(token, "explain")
        if query.account != p.account:
            raise PermissionError("query account denied")
        self._audit(p, request_id, "explain")
        result = answer_question(
            self.repository,
            ReadGrant(actor_id=p.actor_id, account=p.account, expires_at=p.expires_at),
            query,
            question,
            now=self.clock.now,
            budget=self._budget,
            transport=self._transport,
            conversation_id=conversation_id,
            request_id=request_id,
            expires_at=expires_at,
            language=language,
        )
        self._principal(token, "explain")
        return result

    def snapshot(self, token, market):
        self._principal(token, "command")
        if self.gateway is None or self.gateway.account != self.repository.account:
            raise PermissionError("no bound simulator gateway")
        return command_snapshot(self.gateway, market)

    def rationale(self, token, query, record_id, *, conversation_id, request_id):
        from fx_talanta.advisor.rationale import from_receipt

        evidence = self.read(token, query, conversation_id=conversation_id, request_id=request_id)
        result = from_receipt(self.repository, evidence, record_id)
        self._principal(token, "read")
        return result

    def command(self, token, request, market):
        # Serialize revocation with command start. Revocation cannot undo a completed
        # action; no revocation can race past verification to start a later one.
        with self.access._lock:
            p = self._principal(token, "command")
            if self.gateway is None or self.gateway.account != p.account:
                raise PermissionError("no bound simulator gateway")
            if request.account != p.account:
                raise PermissionError("command account denied")
            self._audit(p, request.request_id, "command")
            return dispatch_simulated(
                self.gateway,
                SimulatedScope(
                    actor_id=p.actor_id,
                    account=p.account,
                    expires_at=p.expires_at,
                    allowed_actions=p.actions,
                ),
                request,
                market,
            )

    def propose(self, token, request_id):
        """Server snapshot/candidate source only; client supplies identity, not risk parameters.

        Provider work runs outside gateway/access locks. Authorization and original
        quote freshness are checked again before the existing simulator risk path.
        """
        from fx_talanta.advisor.command_gateway import _bound
        from fx_talanta.advisor.proposals import propose

        p = self._principal(token, "propose")
        if (
            self._proposal_source is None
            or self.gateway is None
            or self.gateway.account != p.account
        ):
            raise PermissionError("no configured simulator proposal pipeline")
        _bound(self.gateway)
        self._audit(p, request_id, "propose")
        request, market = self._proposal_source(request_id)
        if (
            request.account != p.account
            or request.cutoff != market.at
            or request.quote_at != min(q.at for q in market.quotes)
        ):
            raise ValueError("proposal must pin original market snapshot")
        decision, intent = propose(
            self.repository,
            ReadGrant(actor_id=p.actor_id, account=p.account, expires_at=p.expires_at),
            request,
            request_id,
            self._allowed_strategies,
            self._budget,
            self._transport,
            now=self.clock.now,
        )
        with self.access._lock:
            self._principal(token, "propose")
            if intent is None:
                return decision, None
            # Gateway repeats health, loss, exposure, spread and freshness checks;
            # model selection cannot grant risk authority or change sizing.
            with self.gateway.lock:
                if not 0 <= (self.clock.now() - request.quote_at).total_seconds() <= 2:
                    return decision, None
                intent = intent.model_copy(
                    update={"policy_version": self.gateway.book.policy.version}
                )
                return decision, self.gateway.submit(intent, market)
