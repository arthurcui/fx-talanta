"""Budget-bound demo publication; explicit local activation is required for native execution."""

from decimal import ROUND_CEILING, ROUND_FLOOR

from fx_talanta.demo.acceptance_budget import AcceptanceBudget
from fx_talanta.demo.activation import DemoActivation
from fx_talanta.demo.coordinator import DemoBackend, DemoCoordinator
from fx_talanta.domain.ea_protocol import Envelope
from fx_talanta.shadow.wire import Frame, digest
from fx_talanta.shadow.work import scope_for


class BoundedDemoCoordinator(DemoCoordinator):
    def __init__(self, store, authority, account, *args, budget, activation=None, **kwargs):
        if not isinstance(budget, AcceptanceBudget) or budget.binding["scope"] != scope_for(
            account
        ):
            raise ValueError("DEMO_BUDGET_ACCOUNT_MISMATCH")

        activation_hash = None
        if activation is not None:
            if not isinstance(activation, DemoActivation) or len(args) < 5:
                raise ValueError("EXPLICIT_DEMO_ACTIVATION_REQUIRED")
            activation_hash = activation.validate(budget, args[3], args[4])
        self.native_execution_authorized = activation is not None
        self.activation = activation

        owner = self

        class BudgetBackend(DemoBackend):
            binding_extension = DemoBackend.binding_extension | {
                "acceptance_budget": budget.binding_hash,
                **({"bounded_activation": activation_hash} if activation else {}),
            }

            def publish(self, envelope, snapshot, now):
                envelope = Envelope.model_validate(envelope.model_dump())
                request = envelope.payload
                if request.account != self.account:
                    raise ValueError("DEMO_BUDGET_ACCOUNT_MISMATCH")
                if request.action == "ENTER":
                    if activation and not activation.entry_open(now, snapshot.clock_error_ms):
                        raise ValueError("ACTIVATION_ENTRY_WINDOW_CLOSED")
                    if activation and not owner.native_ready(now):
                        raise ValueError("NATIVE_DEMO_NOT_READY")
                    if request.currency != budget.plan.currency:
                        raise ValueError("DEMO_BUDGET_CURRENCY_MISMATCH")
                    # Round UP, never discard fractional lot units or risk cents.
                    units = int(
                        (request.max_volume * 100_000_000).to_integral_value(rounding=ROUND_CEILING)
                    )
                    cents = int((request.max_risk * 100).to_integral_value(rounding=ROUND_CEILING))
                    eligible = int(
                        (min(snapshot.equity, snapshot.capital) * 100).to_integral_value(
                            rounding=ROUND_FLOOR
                        )
                    )
                    budget.reserve(
                        envelope.digest,
                        request.symbol,
                        units,
                        cents,
                        now,
                        eligible_equity_cents=eligible,
                    )
                # A publication failure leaves its charge unresolved. No rollback
                # of the other journal, automatic refund, or uncertain-call retry.
                return super().publish(envelope, snapshot, now)

        self.backend_type = BudgetBackend
        self.acceptance_budget = budget
        super().__init__(store, authority, account, *args, **kwargs)

    def publish(self, envelope, snapshot, now):
        # Readiness refusal occurs before admission starts; no journal or budget
        # mutation is attempted. Persistence uncertainty inside admission still
        # invokes the base coordinator's permanent failure latch.
        with self.lock:
            if self.activation and envelope.payload.action == "ENTER":
                if not self.activation.entry_open(now, snapshot.clock_error_ms):
                    raise ValueError("ACTIVATION_ENTRY_WINDOW_CLOSED")
                if not self.native_ready(now):
                    raise ValueError("NATIVE_DEMO_NOT_READY")
            return super().publish(envelope, snapshot, now)

    def exchange(self, raw, now):
        frame = Frame.decode(
            raw, self.backend.key, direction="C2S", scope=self.scope, client=self.client, now=now
        )
        if frame.operation == "PULL" and frame.payload.startswith("bounded-sync/1\t"):
            fields = frame.payload.split("\t")
            if (
                not self.activation
                or len(fields) != 3
                or fields[2] not in {"0", "1"}
                or fields[1] != digest(self.activation.native_manifest())
            ):
                raise ValueError("BOUNDED_READINESS_BINDING")
            with self.lock:
                result = self._sync(frame, raw, now)
                with self.store.transaction() as events:
                    self._check(events)
                    if not any(
                        e["kind"] == "demo_readiness" and e["nonce"] == frame.nonce
                        for e in events.records
                    ):
                        events.append(
                            dict(
                                kind="demo_readiness",
                                nonce=frame.nonce,
                                issued_ms=frame.issued,
                                at_ms=now,
                                enabled=fields[2] == "1",
                                execution_enabled=False,
                            )
                        )
                self._advance()
                return result
        return super().exchange(raw, now)

    def native_ready(self, now):
        with self.lock, self.store.transaction() as events:
            self._check(events)
            readings = [e for e in events.records if e["kind"] == "demo_readiness"]
            return bool(
                readings
                and readings[-1]["enabled"]
                and 0 <= now - readings[-1]["issued_ms"] <= 2000
                and 0 <= now - readings[-1]["at_ms"] <= 2000
            )

    def status(self, now):
        result = super().status(now)
        result["native_demo_ready"] = self.native_ready(now)
        result["acceptance_budget"] = self.acceptance_budget.status(now)
        return result
