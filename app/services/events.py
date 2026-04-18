"""Event emission — writes to timeline, audit log, fans out to webhooks, and
mirrors to any enabled memory connectors."""

from __future__ import annotations

import logging

from fastapi import BackgroundTasks
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.deps import Principal
from app.models import AuditLog, EntityType, MemoryLink, TimelineEvent, Webhook
from app.services.memory import enabled_connectors
from app.services.webhook_delivery import deliver_webhook

log = logging.getLogger("nakatomi.events")


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

    if background is None:
        return

    # Fan out to enabled memory connectors (best-effort, runs in background).
    for name in enabled_connectors():
        background.add_task(
            _mirror_to_memory,
            connector_name=name,
            workspace_id=principal.workspace.id,
            event_type=event_type,
            crm_entity_type=et_enum.value,
            crm_entity_id=entity_id,
            text=_summarize(event_type, payload),
            metadata={"payload": payload},
        )

    hooks = db.scalars(
        select(Webhook).where(
            Webhook.workspace_id == principal.workspace.id,
            Webhook.is_active.is_(True),
        )
    ).all()
    for hook in hooks:
        if hook.events and event_type not in hook.events and "*" not in hook.events:
            continue
        background.add_task(
            deliver_webhook,
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


def _summarize(event_type: str, payload: dict) -> str:
    """Cheap summary string sent to memory connectors. Agents handle semantics."""
    return f"{event_type}: {payload}"


def _mirror_to_memory(
    *,
    connector_name: str,
    workspace_id: str,
    event_type: str,
    crm_entity_type: str,
    crm_entity_id: str,
    text: str,
    metadata: dict,
) -> None:
    from app.db import db_session
    from app.services.memory import get_connector

    connector = get_connector(connector_name)
    if not connector:
        return
    try:
        result = connector.store_event(
            workspace_id=workspace_id,
            event_type=event_type,
            crm_entity_type=crm_entity_type,
            crm_entity_id=crm_entity_id,
            text=text,
            metadata=metadata,
        )
    except Exception as e:  # noqa: BLE001
        log.warning("memory connector '%s' raised during store: %s", connector_name, e)
        return
    if not result or not result.external_id:
        return
    with db_session() as db:
        db.add(
            MemoryLink(
                workspace_id=workspace_id,
                connector=connector_name,
                external_id=result.external_id,
                crm_entity_type=EntityType(crm_entity_type),
                crm_entity_id=crm_entity_id,
                note=f"auto-link via {event_type}",
                data={"event_type": event_type},
            )
        )
