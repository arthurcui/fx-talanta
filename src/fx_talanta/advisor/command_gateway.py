"""Trusted harness adapter for the existing offline Gateway and Simulator only."""

import hashlib
import json
from uuid import uuid5

from fx_talanta.advisor.commands import CommandInput, SimulatedScope, SimulatedState, evaluate
from fx_talanta.brokers.simulator import Simulator
from fx_talanta.domain.models import ConversationMessage, EvidenceLink, Record, Versions
from fx_talanta.domain.offline import BrokerRequest, Market
from fx_talanta.gateway.offline import Gateway
from fx_talanta.risk.governor import health_reason
from fx_talanta.storage.repository import RecordConflict


def _bound(gateway):
    if (
        type(gateway) is not Gateway
        or type(gateway.broker) is not Simulator
        or gateway.account.environment != "PAPER"
        or gateway.account.venue != "SIMULATOR"
    ):
        raise PermissionError("offline PAPER simulator required")
    gateway.store.assert_owner()


def _snapshot(gateway, market):
    broker = gateway.broker.snapshot()
    book = gateway.book
    now = gateway.clock.now()
    # Opaque integer state token, not a counter. Both persisted books participate.
    digest = hashlib.sha256((book.model_dump_json() + broker.model_dump_json()).encode()).digest()
    known = {e.intent.intent_id for e in book.entries}
    positions = tuple(
        p.position_id for p in broker.positions if p.owned and p.volume and p.entry_id in known
    )
    unresolved = any(o.state in {"SUBMITTING", "OUTCOME_UNKNOWN"} for o in book.operations)
    unresolved |= any(e.state in {"SUBMITTING", "OUTCOME_UNKNOWN"} for e in book.entries)
    external = any(p.volume and (not p.owned or p.entry_id not in known) for p in broker.positions)
    restricted = market
    for symbol in ("EURUSD", "USDJPY"):
        restricted = gateway._restrict_news(restricted, symbol)
    return SimulatedState(
        account=gateway.account,
        version=int.from_bytes(digest, "big"),
        observed_at=market.at,
        administrative_pause=book.administrative_pause,
        loss_pause=bool(book.losses and book.losses.loss_pause_day == now.date()),
        hard_halt=bool(book.losses and book.losses.hard_halt),
        integrity_halt=book.integrity_halt or external,
        unresolved_orders=unresolved,
        inputs_qualified=restricted.calendar_ok and restricted.news_ok,
        healthy=book.state == "RUNNING" and health_reason(restricted, now, book.policy) is None,
        quote_at=min((q.at for q in market.quotes), default=None),
        owned_positions=positions,
    )


def command_snapshot(gateway, market):
    """Read authoritative simulator state under the same lock as entry/management."""
    with gateway.lock:
        _bound(gateway)
        return _snapshot(gateway, Market.model_validate(market.model_dump(mode="json")))


def dispatch_simulated(gateway, scope, request, market):
    """Commit-before-action; same request never re-dispatches, even after a crash.

    No external execution authority is provided by this function. Scope is supplied
    by a trusted test harness; production authentication is still separate work.
    """
    with gateway.lock:
        _bound(gateway)
        scope = SimulatedScope.model_validate(scope.model_dump(mode="json"))
        request = CommandInput.model_validate(request.model_dump(mode="json"))
        market = Market.model_validate(market.model_dump(mode="json"))
        now = gateway.clock.now()
        if (
            scope.account != gateway.account
            or request.account != gateway.account
            or now >= scope.expires_at
        ):
            raise PermissionError("simulator command scope denied")
        rid = uuid5(request.request_id, "gateway-admin/request/1")
        result_id = uuid5(request.request_id, "gateway-admin/result/1")
        identity = json.dumps(
            {
                "request": request.model_dump(mode="json"),
                "actor": scope.actor_id,
                "actions": sorted(scope.allowed_actions),
                "run_id": str(gateway.run_id),
            },
            sort_keys=True,
        )

        def get(record_id):
            try:
                return gateway.store.repo.get(record_id)
            except KeyError:
                return None

        old = get(rid)
        if old is not None:
            if old.body.kind != "message" or old.body.text != identity:
                raise RecordConflict("administrative request identity changed")
            saved = get(result_id)
            if saved:
                return json.loads(saved.body.text)
            return {
                "status": "OUTCOME_UNKNOWN",
                "reason": "INTERRUPTED_NO_RESEND",
                "simulation_only": True,
                "execution_enabled": False,
            }
        state = _snapshot(gateway, market)
        evaluation = evaluate(scope, request, state, now=now)

        def message(record_id, role, text, refs=()):
            return Record(
                record_id=record_id,
                account=gateway.account,
                recorded_at=gateway.clock.now(),
                correlation_id=request.conversation_id,
                provenance="OFFLINE_SIMULATION",
                references=refs,
                versions=Versions(
                    component="m4-simulator-command-gateway/1", model="none", prompt="none"
                ),
                body=ConversationMessage(
                    conversation_id=request.conversation_id,
                    message_id=record_id,
                    actor_id=scope.actor_id,
                    authenticated=False,
                    role=role,
                    language=request.language,
                    text=text,
                    interpretation="READ_ONLY",
                ),
            )

        prior = gateway.book
        try:
            # Persist entry restrictions with the request BEFORE any cancel/close.
            if evaluation.status != "REJECTED":
                if evaluation.action == "PAUSE_ENTRIES":
                    gateway.book = gateway.book.model_copy(update={"administrative_pause": True})
                elif evaluation.action == "RESUME_ENTRIES":
                    gateway.book = gateway.book.model_copy(update={"administrative_pause": False})
                elif evaluation.action == "FLATTEN_OWNED_AND_HALT":
                    gateway.book = gateway.book.model_copy(
                        update={"administrative_pause": True, "integrity_halt": True}
                    )
            gateway._save("ADMIN_REQUEST_RESERVED", (message(rid, "USER", identity),))
        except BaseException:
            gateway.book = prior
            gateway.close()  # Failed durable fencing cannot leave a usable writer.
            raise

        status, reason = "REJECTED", evaluation.reason
        operations = []
        try:
            if evaluation.status != "REJECTED":
                status, reason = "COMPLETED", "SIMULATOR_CONFIRMED"
                if evaluation.action in {"CLOSE_OWNED_POSITION", "FLATTEN_OWNED_AND_HALT"}:
                    if state.unresolved_orders or not gateway.broker.history_visible:
                        status, reason = "OUTCOME_UNKNOWN", "RECONCILE_NO_RESEND"
                    else:
                        targets = (
                            (evaluation.position_id,)
                            if evaluation.position_id
                            else state.owned_positions
                        )
                        entries = {
                            p.entry_id
                            for p in gateway.broker.book.positions
                            if p.position_id in targets
                        }
                        if evaluation.action == "FLATTEN_OWNED_AND_HALT":
                            entries |= {
                                e.intent.intent_id
                                for e in gateway.book.entries
                                if e.reservation and e.reservation.volume
                            }
                        # Cancel unfilled remainders first, so a later fill cannot reopen exposure.
                        for entry_id in sorted(entries, key=str):
                            if gateway.clock.now() >= min(request.expires_at, scope.expires_at):
                                status, reason = "OUTCOME_UNKNOWN", "DEADLINE_NO_FURTHER_ACTION"
                                break
                            entry = gateway.entry(entry_id)
                            if entry.reservation and entry.reservation.volume:
                                operation = gateway.manage(
                                    BrokerRequest(
                                        request_id=uuid5(request.request_id, f"cancel/{entry_id}"),
                                        account=gateway.account,
                                        action="CANCEL",
                                        entry_id=entry_id,
                                        symbol=entry.intent.symbol,
                                    ),
                                    market,
                                )
                                operations.append(str(operation.request.request_id))
                                if operation.state != "COMPLETED":
                                    status, reason = operation.state, "CANCEL_NOT_CONFIRMED"
                                    break
                        if status == "COMPLETED":
                            for position_id in targets:
                                if gateway.clock.now() >= min(request.expires_at, scope.expires_at):
                                    status, reason = "OUTCOME_UNKNOWN", "DEADLINE_NO_FURTHER_ACTION"
                                    break
                                p = next(
                                    p
                                    for p in gateway.broker.book.positions
                                    if p.position_id == position_id
                                )
                                if not p.volume:
                                    continue
                                operation = gateway.manage(
                                    BrokerRequest(
                                        request_id=uuid5(
                                            request.request_id, f"close/{position_id}"
                                        ),
                                        account=gateway.account,
                                        action="CLOSE",
                                        entry_id=p.entry_id,
                                        symbol=p.symbol,
                                        position_id=p.position_id,
                                        expected_version=p.version,
                                        volume=p.volume,
                                    ),
                                    market,
                                )
                                operations.append(str(operation.request.request_id))
                                if operation.state != "COMPLETED":
                                    status, reason = operation.state, "CLOSE_NOT_CONFIRMED"
                                    break
                            if status == "COMPLETED":
                                snapshot = gateway.broker.snapshot()
                                if any(
                                    p.volume and p.position_id in targets
                                    for p in snapshot.positions
                                ) or any(
                                    o.remaining and o.request.entry_id in entries
                                    for o in snapshot.orders
                                ):
                                    status, reason = "OUTCOME_UNKNOWN", "EXPOSURE_STILL_PRESENT"
            result = {
                "status": status,
                "reason": reason,
                "action": evaluation.action,
                "operation_ids": operations,
                "simulation_only": True,
                "execution_enabled": False,
            }
            gateway._save(
                "ADMIN_RESULT",
                (
                    message(
                        result_id,
                        "ADVISOR",
                        json.dumps(result),
                        (EvidenceLink(record_id=rid, relation="MESSAGE"),),
                    ),
                ),
            )
            return result
        except BaseException:
            # A reserved request survives and cannot cause a blind resend on restart.
            gateway.close()
            raise
