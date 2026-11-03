"""Compose implemented M2A/M2C components in a durable, simulator-only fault trace."""

import hashlib
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal as D
from pathlib import Path
from uuid import UUID

from fx_talanta.domain.ea_protocol import Envelope, ReconciliationResult, payload_hash
from fx_talanta.execution_contracts.replay import Allocation, ReferenceInbox, management_reason
from fx_talanta.safety.control import LossState, Protection, losses, protection_step
from fx_talanta.safety.journal import SafetyJournal, canonical, seal
from fx_talanta.safety.preflight import shadow_preflight
from fx_talanta.safety.risk import SafetyInput


def read(root, path):
    return json.loads((root / path).read_text(encoding="utf-8"))


def readiness(root):
    broker = read(root, "docs/evidence/broker-campaign-final-20261103.json")
    providers = read(root, "docs/evidence/provider-campaign-final-20261103.json")
    return {
        "broker_historical_acceptance": {
            b: {
                k: broker[b]["evidence"][k]
                for k in ("collector_accepted", "quote_readiness_accepted", "accepted")
            }
            for b in ("cmc", "forex")
        },
        "provider_coverage_qualified": providers["coverage_qualified"],
        "provider_qualified_for_trading": providers["qualified_for_trading"],
        "connected_transport_and_fencing": "NOT_QUALIFIED",
        "broker_costs_conversion_and_protection_deadlines": "NOT_QUALIFIED",
        "connected_fault_execution": "NOT_AUTHORIZED_OR_RUN",
        "execution_enabled": False,
        "m2d_accepted": False,
    }


def run(root: Path, folder: Path):
    fixture = read(root, "tests/fixtures/safety/risk.json")
    archive = read(root, "docs/evidence/m2c-native-20261103.json")
    if not archive["all_pass"] or archive["native_failures"] != 0:
        raise ValueError("native reference did not pass")
    # Archived native results are reused only against the exact recorded source/fixture bytes.
    for path, digest in archive["source_sha256"].items():
        if hashlib.sha256((root / path).read_bytes()).hexdigest() != digest:
            raise ValueError("native reference source changed; regenerate parity evidence")
    native = next(r["native"] for r in archive["results"] if r["id"] == "usd-eurusd-buy")
    original = Envelope.model_validate(read(root, "tests/fixtures/ea_protocol/request.json"))
    value = SafetyInput.model_validate(fixture["defaults"])
    now = datetime.fromtimestamp(value.measured_at_ms / 1000, UTC) + timedelta(seconds=1)
    ledger = LossState(day=now.date(), start=value.day_start, units=value.equity, owner_pause=False)
    work = original.payload.model_copy(
        update={"snapshot_hash": payload_hash(value), "max_risk": D(25)}
    )
    request = Envelope.seal(work)
    scope = hashlib.sha256(work.account.model_dump_json().encode()).hexdigest()
    key = b"synthetic-m2d-test-key-not-a-secret"  # fixture-only, never deployed
    journal_path = folder / "safety.sqlite"
    if journal_path.exists():
        raise ValueError("evidence directory already used")
    journal = SafetyJournal(journal_path, scope, key=key, bootstrap=True)
    epoch = journal.acquire(
        "fixture",
        1000,
        5000,
        reconciled=True,
        clock_error_ms=0,
        peer_checkpoint=journal.checkpoint(),
    )
    results, clock = [], 1100

    def persist(event_id, body, *, owner="fixture", writer_epoch=None, signature=None, at=None):
        nonlocal clock
        clock += 1
        sequence = journal.checkpoint()[0] + 1
        writer_epoch = epoch if writer_epoch is None else writer_epoch
        authenticated = canonical({"id": event_id, "body": body})
        signature = signature or seal(key, scope, writer_epoch, sequence, 5900, authenticated)
        return journal.append(
            event_id,
            body,
            owner=owner,
            epoch=writer_epoch,
            sequence=sequence,
            now_ms=clock if at is None else at,
            clock_error_ms=0,
            expires_ms=5900,
            signature=signature,
        )

    def check(name, observed, expected):
        result = {
            "id": name,
            "observed": observed,
            "expected": expected,
            "passed": observed == expected,
        }
        persist(name, result)
        results.append(result)

    def preflight(
        updates=None,
        *,
        at=now,
        native_result=native,
        storage_ok=True,
        fenced=True,
        account=work.account,
        loss=ledger,
    ):
        snapshot = SafetyInput.model_validate(value.model_dump() | (updates or {}))
        envelope = Envelope.seal(work.model_copy(update={"snapshot_hash": payload_hash(snapshot)}))
        return shadow_preflight(
            envelope,
            snapshot,
            loss,
            account=account,
            release_hash=work.release_hash,
            policy_hash=work.policy_hash,
            now=at,
            storage_ok=storage_ok,
            fenced=fenced,
            native_result=native_result,
        )

    def veto(name, expected, updates=None, **kwargs):
        result = preflight(updates, **kwargs)
        check(
            name,
            {k: result[k] for k in ("reason", "send_enabled")},
            {"reason": expected, "send_enabled": False},
        )

    try:
        inbox = ReferenceInbox(work.account, work.release_hash, work.policy_hash)
        admitted = inbox.receive(request, now, clock_uncertainty_ms=D(10))
        persist(
            "admitted-request",
            {
                "inbox": inbox.rows,
                "snapshot": value.model_dump(mode="json"),
                "loss": ledger.model_dump(mode="json"),
                "native_reference": native,
            },
        )
        check("admit_once", list(admitted), ["ACCEPTED", False])
        veto("nominal_still_no_send", "ACCEPTED")
        veto("quote_aged_in_transit", "QUOTE_STALE", at=now + timedelta(seconds=1))
        veto("required_news_missing", "REQUIRED_INPUTS", {"inputs_ok": False})
        veto("calendar_blackout", "BLACKOUT_OR_SESSION", {"blackout": True})
        veto("market_closed", "BLACKOUT_OR_SESSION", {"session_open": False})
        veto("native_response_lost", "NATIVE_PARITY_BLOCK", native_result=None)
        veto("storage_unavailable", "STORAGE_OR_FENCE_BLOCK", storage_ok=False)
        veto("writer_not_fenced", "STORAGE_OR_FENCE_BLOCK", fenced=False)
        veto(
            "wrong_account",
            "ACCOUNT_MISMATCH",
            account=work.account.model_copy(update={"login": "other-fixture"}),
        )
        veto("clock_regressed", "SNAPSHOT_FUTURE", at=now - timedelta(seconds=2))
        veto("work_expired", "EXPIRED_OR_FUTURE", at=now + timedelta(seconds=60))
        check(
            "duplicate_no_new_admission",
            list(inbox.receive(request, now, clock_uncertainty_ms=D(10))),
            ["ACCEPTED", True],
        )
        altered = Envelope.seal(work.model_copy(update={"max_volume": D("0.08")}))
        check(
            "same_id_changed_hash",
            list(inbox.receive(altered, now, clock_uncertainty_ms=D(10))),
            ["HASH_CONFLICT", False],
        )
        other = Envelope.seal(work.model_copy(update={"release_hash": "b" * 64}))
        check(
            "wrong_release",
            list(inbox.receive(other, now, clock_uncertainty_ms=D(10))),
            ["RELEASE_MISMATCH", False],
        )
        allocation = Allocation(request)
        persist(
            "ack-lost",
            {"unknown": True, "reserved": str(allocation.reserved), "sent_to_broker": False},
        )
        checkpoint = journal.checkpoint()
        journal.close()
        journal = SafetyJournal(journal_path, scope, key=key)
        records = journal.verify()
        recovered = next(r for r in records if "inbox" in r)
        restored = ReferenceInbox(
            work.account, work.release_hash, work.policy_hash, recovered["inbox"]
        )
        recovered_request = Envelope.model_validate(restored.rows[0]["envelope"])
        allocation = Allocation(recovered_request)
        check(
            "lost_ack_restart_retains_allowance",
            {
                "checkpoint_retained": journal.checkpoint() == checkpoint,
                "duplicate": list(
                    restored.receive(request, now + timedelta(hours=1), clock_uncertainty_ms=D(10))
                ),
                "reserved": str(allocation.reserved),
            },
            {"checkpoint_retained": True, "duplicate": ["ACCEPTED", True], "reserved": "0.09"},
        )

        def reconcile(sequence, filled, released, result, predecessor):
            event = Envelope.seal(
                ReconciliationResult(
                    account=work.account,
                    message_id=UUID(int=100 + sequence),
                    sequence=sequence,
                    created_at=now,
                    release_hash=work.release_hash,
                    policy_hash=work.policy_hash,
                    request_id=work.message_id,
                    request_hash=request.digest,
                    reservation_id=work.reservation_id,
                    predecessor_hash=predecessor,
                    result=result,
                    filled_volume=filled,
                    released_volume=released,
                    evidence=() if result == "UNKNOWN" else ("f" * 64,),
                )
            )
            allocation.reconcile(event)
            persist(
                f"fixture-reconciliation-{sequence}",
                {"provenance": "SYNTHETIC_ONLY", "event": event.model_dump(mode="json")},
            )
            return event

        unknown = reconcile(1, "0", "0", "UNKNOWN", request.digest)
        check("unknown_retains_reservation", str(allocation.reserved), "0.09")
        partial = reconcile(2, "0.04", "0", "CONFIRMED", unknown.digest)
        allocation.reconcile(partial)
        check(
            "partial_and_duplicate_do_not_double_count",
            [str(allocation.filled), str(allocation.reserved)],
            ["0.04", "0.05"],
        )
        reconcile(3, "0.04", "0.05", "CONFIRMED", partial.digest)
        check(
            "cancel_releases_only_unfilled",
            [str(allocation.filled), str(allocation.released), str(allocation.reserved)],
            ["0.04", "0.05", "0.00"],
        )
        check(
            "wrong_position_version",
            management_reason(
                owned=True, reconciled=True, mutation_unknown=False, expected=3, current=4
            ),
            "STATE_MISMATCH",
        )
        check(
            "unexpected_position",
            management_reason(
                owned=False, reconciled=True, mutation_unknown=False, expected=3, current=3
            ),
            "NOT_OWNED",
        )
        p = Protection(
            phase="PENDING",
            submitted_ms=0,
            repair_deadline_ms=1000,
            exit_deadline_ms=2000,
            last_ms=0,
            boot_id="fixture",
        )
        step_args = dict(
            boot_id="fixture",
            storage_ok=True,
            broker_ok=True,
            reconciled=True,
            protected=False,
            closed=False,
            mutation_unknown=False,
        )
        p, action = protection_step(p, now_ms=100, **step_args)
        persist("repair-recommendation", {"protection": p.model_dump(), "recommendation": action})
        check("protect_once", action, "ATTACH_STOP_ONCE")
        p, action = protection_step(p, now_ms=200, rejected=True, **step_args)
        persist("exit-recommendation", {"protection": p.model_dump(), "recommendation": action})
        check("rejected_stop_exit_once", action, "CONTROLLED_EXIT_ONCE")
        p, action = protection_step(
            p, now_ms=2100, **(step_args | {"mutation_unknown": True, "reconciled": False})
        )
        check(
            "lost_close_ack_no_resend",
            [p.phase, p.hard_halt, action],
            ["UNKNOWN", True, "RECONCILE_NO_RESEND"],
        )
        _, action = protection_step(
            p, now_ms=2200, **(step_args | {"broker_ok": False, "reconciled": False})
        )
        check("backend_outage_does_not_clear_unknown", action, "RECONCILE_NO_RESEND")
        _, action = protection_step(p, now_ms=2300, **(step_args | {"storage_ok": False}))
        check("disk_failure_no_mutation", action, "ALERT_STORAGE_NO_MUTATION")
        lost = losses(ledger, day=ledger.day, equity=D(9400), reconciled=True)
        restored_loss = LossState.model_validate_json(lost.model_dump_json())
        check(
            "loss_halt_survives_restart",
            [restored_loss.hard_halt, restored_loss.loss_pause],
            [True, True],
        )
        for name, kwargs in (
            ("wrong_signature", {"signature": "0" * 64}),
            ("second_writer", {"owner": "other-fixture"}),
            ("expired_lease", {"at": 6000}),
        ):
            before = journal.checkpoint()
            try:
                persist(f"rejected-{name}", {"attempt": name}, **kwargs)
                rejected = False
            except ValueError:
                rejected = True
            check(
                name,
                {"rejected": rejected, "unchanged": journal.checkpoint() == before},
                {"rejected": True, "unchanged": True},
            )
        trace_tip = journal.checkpoint()
        verified_records = len(journal.verify())
    finally:
        journal.close()
    evidence_paths = (
        "docs/evidence/broker-campaign-final-20261103.json",
        "docs/evidence/provider-campaign-final-20261103.json",
        "docs/evidence/m2c-native-20261103.json",
    )
    return {
        "schema": "m2d-no-order/1",
        "status": "NO_ORDER_CHECKS_PASSED" if all(r["passed"] for r in results) else "FAILED",
        "results": results,
        "durable_records": verified_records,
        "trace_tip": list(trace_tip),
        "reference": "Existing native fixture parity, not a new native or broker execution run",
        "historical_evidence_sha256": {
            p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in evidence_paths
        },
        "gates": readiness(root),
        "execution_enabled": False,
        "m2d_accepted": False,
        "limitation": (
            "Synthetic broker outcomes. SQLite/local fencing only; "
            "no production transport, broker fills, SL or exit qualification."
        ),
    }
