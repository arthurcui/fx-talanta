"""Budget-bound publication rehearsal. Native execution remains hard-disabled."""

from decimal import ROUND_CEILING

from fx_talanta.demo.acceptance_budget import AcceptanceBudget
from fx_talanta.demo.coordinator import DemoBackend, DemoCoordinator
from fx_talanta.domain.ea_protocol import Envelope
from fx_talanta.shadow.work import scope_for


class BoundedDemoCoordinator(DemoCoordinator):
    def __init__(self, store, authority, account, *args, budget, **kwargs):
        if not isinstance(budget, AcceptanceBudget) or budget.binding["scope"] != scope_for(
            account
        ):
            raise ValueError("DEMO_BUDGET_ACCOUNT_MISMATCH")

        class BudgetBackend(DemoBackend):
            binding_extension = DemoBackend.binding_extension | {
                "acceptance_budget": budget.binding_hash,
            }

            def publish(self, envelope, snapshot, now):
                envelope = Envelope.model_validate(envelope.model_dump())
                request = envelope.payload
                if request.account != self.account:
                    raise ValueError("DEMO_BUDGET_ACCOUNT_MISMATCH")
                if request.action == "ENTER":
                    if request.currency != budget.plan.currency:
                        raise ValueError("DEMO_BUDGET_CURRENCY_MISMATCH")
                    # Round UP, never discard fractional lot units or risk cents.
                    units = int(
                        (request.max_volume * 100_000_000).to_integral_value(rounding=ROUND_CEILING)
                    )
                    cents = int((request.max_risk * 100).to_integral_value(rounding=ROUND_CEILING))
                    budget.reserve(envelope.digest, request.symbol, units, cents, now)
                # A publication failure leaves its charge unresolved. No rollback
                # of the other journal, automatic refund, or uncertain-call retry.
                return super().publish(envelope, snapshot, now)

        self.backend_type = BudgetBackend
        self.acceptance_budget = budget
        super().__init__(store, authority, account, *args, **kwargs)

    def status(self, now):
        result = super().status(now)
        result["acceptance_budget"] = self.acceptance_budget.status(now)
        return result
