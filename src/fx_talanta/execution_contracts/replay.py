"""Fixture-only protocol inbox. Accepted means recorded, never sent to a broker."""

from decimal import Decimal

from fx_talanta.domain.ea_protocol import Envelope, ExecutionRequest


class ReferenceInbox:
    def __init__(self, account, release_hash, policy_hash, journal=()):
        self.account, self.release, self.policy = account, release_hash, policy_hash
        self.rows = []
        self.ids, self.reservations = {}, {}
        for raw in journal:
            envelope = Envelope.model_validate(raw["envelope"])
            reason = raw["reason"]
            if reason not in {
                "ACCEPTED",
                "EXPIRED",
                "FUTURE_MESSAGE",
                "CLOCK_UNCERTAIN",
                "STATE_MISMATCH",
            }:
                raise ValueError("invalid checkpoint result")
            # Rebuild the immutable admitted prefix; no rechecking elapsed TTL.
            if self._identity(envelope) or self._structural(envelope):
                raise ValueError("invalid checkpoint")
            self._record(envelope, reason)

    def _identity(self, envelope):
        p = envelope.payload
        if not isinstance(p, ExecutionRequest):
            return "UNSUPPORTED"
        if p.account != self.account:
            return "ACCOUNT_MISMATCH"
        if p.release_hash != self.release:
            return "RELEASE_MISMATCH"
        if p.policy_hash != self.policy:
            return "POLICY_MISMATCH"
        return None

    def _structural(self, envelope):
        p = envelope.payload
        if p.message_id in self.ids:
            return "HASH_CONFLICT"
        if p.sequence != len(self.rows) + 1:
            return "SEQUENCE_GAP"
        if p.reservation_id in self.reservations:
            return "RESERVATION_CONFLICT"
        return None

    def _record(self, envelope, reason="ACCEPTED"):
        p = envelope.payload
        self.rows.append({"envelope": envelope.model_dump(mode="json"), "reason": reason})
        self.ids[p.message_id] = (envelope.digest, reason)
        if reason == "ACCEPTED":
            self.reservations[p.reservation_id] = p.message_id
        return reason, False

    def receive(self, raw, now, *, clock_uncertainty_ms, state_version=None):
        # Re-parse even typed objects: model_copy/update is not a validation boundary.
        envelope = Envelope.model_validate_json(
            raw.model_dump_json() if isinstance(raw, Envelope) else raw
        )
        p = envelope.payload
        if reason := self._identity(envelope):
            return reason, False
        if p.message_id in self.ids:
            return (
                (self.ids[p.message_id][1], True)
                if self.ids[p.message_id][0] == envelope.digest
                else ("HASH_CONFLICT", False)
            )
        if reason := self._structural(envelope):
            return reason, False
        if (
            not isinstance(clock_uncertainty_ms, Decimal)
            or not clock_uncertainty_ms.is_finite()
            or not 0 <= clock_uncertainty_ms <= 100
        ):
            return self._record(envelope, "CLOCK_UNCERTAIN")
        uncertainty = clock_uncertainty_ms / 1000
        if Decimal(str((now - p.created_at).total_seconds())) < uncertainty:
            return self._record(envelope, "FUTURE_MESSAGE")
        if Decimal(str((p.expires_at - now).total_seconds())) <= uncertainty:
            return self._record(envelope, "EXPIRED")
        if p.action != "ENTER" and p.expected_state_version != state_version:
            return self._record(envelope, "STATE_MISMATCH")
        return self._record(envelope)


def management_reason(*, owned, reconciled, mutation_unknown, expected, current):
    if not owned:
        return "NOT_OWNED"
    if mutation_unknown:
        return "UNKNOWN_OUTCOME"
    if not reconciled or expected != current:
        return "STATE_MISMATCH"
    return None


def entry_reason(
    *,
    hard_halt,
    loss_pause,
    outcome_unknown,
    protection_pending,
    owner_pause,
    input_health,
    quote_age,
):
    # Composed gates: clearing owner pause never clears loss/unknown/protection gates.
    if hard_halt or loss_pause:
        return "LOSS_BLOCK"
    if outcome_unknown:
        return "UNKNOWN_OUTCOME"
    if protection_pending or owner_pause or not input_health:
        return "HEALTH_BLOCK"
    if quote_age is None or not quote_age.is_finite() or not 0 <= quote_age <= 2:
        return "STALE_QUOTE"
    return None


class Allocation:
    """Cumulative filled and positively released lots share ONE original allowance."""

    def __init__(self, request):
        self.request = request
        self.filled = Decimal(0)
        self.released = Decimal(0)
        self.events = {}
        self.last_sequence = 0

    @property
    def reserved(self):
        return self.request.payload.max_volume - self.filled - self.released

    def reconcile(self, event):
        event = Envelope.model_validate_json(event.model_dump_json())
        p, r = event.payload, self.request.payload
        if p.kind != "reconciliation_result":
            raise ValueError("reconciliation evidence required")
        if (
            p.account,
            p.request_id,
            p.request_hash,
            p.reservation_id,
            p.release_hash,
            p.policy_hash,
        ) != (
            r.account,
            r.message_id,
            self.request.digest,
            r.reservation_id,
            r.release_hash,
            r.policy_hash,
        ):
            raise ValueError("reconciliation scope mismatch")
        if p.message_id in self.events:
            if self.events[p.message_id] != event.digest:
                raise ValueError("reconciliation hash conflict")
            return
        if p.sequence != self.last_sequence + 1:
            raise ValueError("reconciliation sequence gap")
        predecessor = self.request.digest if not self.events else list(self.events.values())[-1]
        if p.predecessor_hash != predecessor:
            raise ValueError("reconciliation predecessor mismatch")
        if p.filled_volume < self.filled or p.released_volume < self.released:
            raise ValueError("cumulative quantities cannot regress")
        if p.filled_volume + p.released_volume > r.max_volume:
            raise ValueError("reservation overconsumed")
        self.filled, self.released = p.filled_volume, p.released_volume
        self.events[p.message_id] = event.digest
        self.last_sequence = p.sequence
