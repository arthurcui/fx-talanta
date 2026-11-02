"""Exact scripted messages, not natural-language interpretation or owner authentication."""

from datetime import timedelta
from uuid import UUID, uuid5

from fx_talanta.clock import Clock
from fx_talanta.domain.models import (
    AdministrativeCommand,
    ConversationMessage,
    EvidenceLink,
    Record,
)
from fx_talanta.storage.repository import Repository


def record_chat(
    repository: Repository,
    clock: Clock,
    run_id: UUID,
    label: str,
    text: str,
    *,
    actor_id: str = "fixture-owner",
    authenticated: bool = True,
    language: str = "en",
) -> tuple[Record, Record | None]:
    account = repository.account
    # Exact fixture allowlist. No substring or model-based command inference.
    commands = {
        f"Pause {account.environment} entries": "PAUSE_ENTRIES",
        f"暂停 {account.environment} 开仓": "PAUSE_ENTRIES",
    }
    reads = {f"What is {account.environment} status?", f"{account.environment} 状态如何？"}
    action = commands.get(text) if authenticated else None
    interpretation = (
        "UNAUTHORIZED"
        if not authenticated
        else "EXPLICIT_COMMAND"
        if action
        else "READ_ONLY"
        if text in reads
        else "AMBIGUOUS"
    )
    message_id = uuid5(run_id, label + "/message")
    message = Record(
        record_id=message_id,
        account=account,
        recorded_at=clock.now(),
        correlation_id=run_id,
        body=ConversationMessage(
            conversation_id=run_id,
            message_id=message_id,
            actor_id=actor_id,
            authenticated=authenticated,
            role="USER",
            language=language,
            text=text,
            interpretation=interpretation,
            interpreted_action=action,
        ),
    )
    command = None
    if action:
        command = Record(
            record_id=uuid5(run_id, label + "/command"),
            account=account,
            recorded_at=clock.now(),
            correlation_id=run_id,
            references=(EvidenceLink(record_id=message_id, relation="MESSAGE"),),
            body=AdministrativeCommand(
                actor_id=actor_id,
                conversation_id=run_id,
                message_id=message_id,
                request_id=uuid5(run_id, label + "/request"),
                action=action,
                expires_at=clock.now() + timedelta(seconds=60),
                expected_state_version=0,
                status="INTERPRETED",
                outcome="Scripted interpretation recorded; execution disabled.",
            ),
        )
    repository.append_batch((message, command) if command else (message,))
    return message, command
