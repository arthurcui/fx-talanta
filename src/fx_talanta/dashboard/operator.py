"""Explicit authenticated administration of the existing PAPER simulator only.

No entry/proposal route, terminal adapter, broker credentials or model authority.
"""

import hmac
import json
from datetime import timedelta
from uuid import UUID, uuid4

from fx_talanta.advisor.command_gateway import _bound, command_snapshot, dispatch_simulated
from fx_talanta.advisor.commands import CommandInput, SimulatedScope, command_text
from fx_talanta.domain.offline import Market

ACTIONS = ("PAUSE_ENTRIES", "RESUME_ENTRIES", "CLOSE_OWNED_POSITION", "FLATTEN_OWNED_AND_HALT")


class Operator:
    def __init__(self, app, gateway, market_source, token):
        _bound(gateway)
        if gateway.account != app.snapshot.account or len(token) < 32 or token == app.token:
            raise PermissionError("separate credential and exact simulator account required")
        self.app, self.gateway, self.market_source, self._token = app, gateway, market_source, token
        self.revoked = False
        with app.repo.lock, app.repo.conn:
            app.repo.conn.execute(
                "CREATE TABLE IF NOT EXISTS operator_binding (identity TEXT NOT NULL)"
            )
            app.repo.conn.execute(
                "CREATE TABLE IF NOT EXISTS operator_requests (id TEXT PRIMARY KEY, "
                "request TEXT NOT NULL, started INTEGER NOT NULL DEFAULT 0, result TEXT)"
            )
            identity = json.dumps(
                {"account": gateway.account.model_dump(mode="json"), "run_id": str(gateway.run_id)},
                sort_keys=True,
            )
            row = app.repo.conn.execute("SELECT identity FROM operator_binding").fetchone()
            if row and row[0] != identity:
                raise ValueError("operator cannot rebind on resume")
            if not row:
                app.repo.conn.execute("INSERT INTO operator_binding VALUES (?)", (identity,))

    def authorize(self, supplied):
        if self.revoked or not supplied.isascii() or not hmac.compare_digest(supplied, self._token):
            raise PermissionError("operator denied")
        self.app.authorize(self.app.token)

    def reconcile_text(self):
        return "Reconcile simulator " + self.gateway.account.model_dump_json()

    def market(self):
        value = self.market_source()
        return Market.model_validate(value.model_dump(mode="json"))

    def status(self, token):
        self.authorize(token)
        state = command_snapshot(self.gateway, self.market())
        return dict(
            state=state.model_dump(mode="json"), simulation_only=True, execution_enabled=False
        )

    def preview(self, token, data):
        self.authorize(token)
        if (
            not isinstance(data, dict)
            or set(data) != {"action", "position_id"}
            or data["action"] not in (*ACTIONS, "RECONCILE_SIMULATOR")
        ):
            raise ValueError("invalid action")
        action = data["action"]
        position = UUID(data["position_id"]) if data["position_id"] else None
        if (action == "CLOSE_OWNED_POSITION") != (position is not None):
            raise ValueError("invalid position")
        with self.app.repo.lock:
            self.app.monitor.read(self.app.clock.now())
            state = command_snapshot(self.gateway, self.market())
            if position is not None and position not in state.owned_positions:
                raise ValueError("position not owned")
            now = self.app.clock.now()
            if not 0 <= (now - state.observed_at).total_seconds() <= 2:
                raise ValueError("stale original market state")
            rid = uuid4()
            request = CommandInput(
                request_id=rid,
                conversation_id=rid,
                account=state.account,
                text=self.reconcile_text()
                if action == "RECONCILE_SIMULATOR"
                else command_text(state.account, action, "en", position),
                language="en",
                expires_at=min(now + timedelta(seconds=20), self.app.expires_at),
                expected_state_version=state.version,
            )
            with self.app.repo.conn:
                self.app.repo.conn.execute(
                    "INSERT INTO operator_requests(id,request) VALUES (?,?)",
                    (str(rid), request.model_dump_json()),
                )
            return dict(
                request_id=str(rid),
                text=request.text,
                expires_at=request.expires_at.isoformat(),
                simulation_only=True,
                execution_enabled=False,
            )

    def confirm(self, token, data):
        self.authorize(token)
        if (
            not isinstance(data, dict)
            or set(data) != {"request_id", "confirmation"}
            or data["confirmation"] != "SIMULATOR ONLY"
        ):
            raise ValueError("explicit simulator confirmation required")
        rid = str(UUID(data["request_id"]))
        # One lock covers revocation, reservation and dispatch; no model/network work.
        with self.app.repo.lock:
            self.authorize(token)
            row = self.app.repo.conn.execute(
                "SELECT request,started,result FROM operator_requests WHERE id=?", (rid,)
            ).fetchone()
            if not row:
                raise ValueError("unknown preview")
            if row[2]:
                return json.loads(row[2])
            if row[1]:
                return dict(
                    status="OUTCOME_UNKNOWN",
                    reason="INTERRUPTED_NO_RESEND",
                    simulation_only=True,
                    execution_enabled=False,
                )
            self.app.monitor.read(self.app.clock.now())
            request = CommandInput.model_validate_json(row[0])
            # Persist uncertainty before mutation; a failed result write cannot resend.
            with self.app.repo.conn:
                self.app.repo.conn.execute(
                    "UPDATE operator_requests SET started=1 WHERE id=?", (rid,)
                )
            if request.text == self.reconcile_text():
                with self.gateway.lock:
                    market = self.market()
                    current = command_snapshot(self.gateway, market)
                    now = self.app.clock.now()
                    if (
                        now >= request.expires_at
                        or current.version != request.expected_state_version
                        or not 0 <= (now - market.at).total_seconds() <= 2
                    ):
                        result = dict(status="REJECTED", reason="EXPIRED_STALE_OR_CHANGED_STATE")
                    else:
                        book = self.gateway.reconcile(market)
                        result = dict(
                            status="COMPLETED",
                            reason="SIMULATOR_RECONCILED",
                            gateway_state=book.state,
                        )
                    result.update(simulation_only=True, execution_enabled=False)
            else:
                result = dispatch_simulated(
                    self.gateway,
                    SimulatedScope(
                        actor_id="dashboard-operator",
                        account=self.gateway.account,
                        expires_at=self.app.expires_at,
                        allowed_actions=ACTIONS,
                    ),
                    request,
                    self.market(),
                )
            with self.app.repo.conn:
                self.app.repo.conn.execute(
                    "UPDATE operator_requests SET result=? WHERE id=?", (json.dumps(result), rid)
                )
            return result

    def revoke(self, token):
        with self.app.repo.lock:
            self.authorize(token)
            self.revoked = True
        return dict(revoked=True, execution_enabled=False)
