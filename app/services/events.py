"""Event emission — writes to timeline, audit log, fans out to webhooks, and
mirrors to any enabled memory connectors."""

from __future__ import annotations

from fastapi import BackgroundTasks
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.deps import Principal
from app.models import AuditLog, EntityType, TimelineEvent, Webhook
from app.services.memory.delivery import enqueue as enqueue_memory
from app.services.webhook_delivery import enqueue as enqueue_webhook


def emit(
    db: Session,
    principal: Principal,
    *,
    event_type: str,
    entity_type: EntityType | str,
    entity_id: str,
    payload: dict,
    background: BackgroundTasks | None = None,
) -> None:
    """Record a timeline event, an audit entry, and fan out to matching webhooks."""
    et_enum = entity_type if isinstance(entity_type, EntityType) else EntityType(entity_type)

    db.add(
        TimelineEvent(
            workspace_id=principal.workspace.id,
            entity_type=et_enum,
            entity_id=entity_id,
            event_type=event_type,
            actor_user_id=principal.user_id,
            actor_api_key_id=principal.api_key_id,
            payload=payload,
        )
    )
    db.add(
        AuditLog(
            workspace_id=principal.workspace.id,
            actor_user_id=principal.user_id,
            actor_api_key_id=principal.api_key_id,
            action=event_type,
            entity_type=et_enum.value,
            entity_id=entity_id,
            payload=payload,
        )
    )

    enqueue_memory(db, principal.workspace, event_type, et_enum, entity_id)

    if background is None:
        return

    # Durable webhook delivery — enqueue a pending row per subscriber; the
    # background worker picks them up. Failures are persisted, not lost.
    hooks = db.scalars(
        select(Webhook).where(
            Webhook.workspace_id == principal.workspace.id,
            Webhook.is_active.is_(True),
        )
    ).all()
    for hook in hooks:
        if hook.events and event_type not in hook.events and "*" not in hook.events:
            continue
        enqueue_webhook(
            db,
            workspace_id=principal.workspace.id,
            webhook_id=hook.id,
            event_type=event_type,
            payload={
                "event": event_type,
                "workspace_id": principal.workspace.id,
                "entity_type": et_enum.value,
                "entity_id": entity_id,
                "data": payload,
            },
        )
