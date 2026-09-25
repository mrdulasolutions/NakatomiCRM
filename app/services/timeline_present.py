"""Timeline presentation — actor labels (P5.2)."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models import TimelineEvent
from app.services.agent_identity import load_actor_labels


def enrich_timeline_events(
    db: Session,
    workspace_id: str,
    events: list[TimelineEvent],
) -> list[dict[str, Any]]:
    """Convert timeline rows to API dicts with ``actor_label``."""
    key_ids = {e.actor_api_key_id for e in events if e.actor_api_key_id}
    user_ids = {e.actor_user_id for e in events if e.actor_user_id}
    key_labels, user_labels = load_actor_labels(db, workspace_id, key_ids, user_ids)
    out: list[dict[str, Any]] = []
    for e in events:
        label = None
        if e.actor_api_key_id and e.actor_api_key_id in key_labels:
            label = key_labels[e.actor_api_key_id]
        elif e.actor_user_id and e.actor_user_id in user_labels:
            label = user_labels[e.actor_user_id]
        out.append(
            {
                "id": e.id,
                "entity_type": e.entity_type.value if e.entity_type else None,
                "entity_id": e.entity_id,
                "event_type": e.event_type,
                "occurred_at": e.occurred_at.isoformat() if e.occurred_at else None,
                "actor_user_id": e.actor_user_id,
                "actor_api_key_id": e.actor_api_key_id,
                "actor_label": label,
                "payload": e.payload or {},
            }
        )
    return out
