"""Time-travel reconstruction and audit search."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Activity,
    AuditLog,
    Company,
    Contact,
    Deal,
    Lead,
    Note,
    Task,
    TimelineEvent,
)

_MODELS: dict[str, Any] = {
    "contact": Contact,
    "company": Company,
    "deal": Deal,
    "lead": Lead,
    "task": Task,
    "note": Note,
    "activity": Activity,
}


def entity_as_of(
    db: Session,
    workspace_id: str,
    entity_type: str,
    entity_id: str,
    at: datetime,
) -> dict[str, Any]:
    """Reconstruct entity field state as of timestamp using timeline change events.

    Starts from current row (or last known), then walks timeline events backward
    applying inverse of ``payload.changes`` where present.
    """
    model = _MODELS.get(entity_type)
    if model is None:
        raise ValueError(f"unsupported entity_type: {entity_type}")

    row = db.get(model, entity_id)
    if not row or getattr(row, "workspace_id", None) != workspace_id:
        raise ValueError("entity not found")

    # Current snapshot
    state = _row_dict(row)
    if row.created_at and row.created_at > at:
        return {
            "entity_type": entity_type,
            "entity_id": entity_id,
            "as_of": at.isoformat(),
            "exists": False,
            "state": None,
            "note": "entity created after as_of timestamp",
        }

    # Events after `at` that mutated this entity — reverse their changes
    events = db.scalars(
        select(TimelineEvent)
        .where(
            TimelineEvent.workspace_id == workspace_id,
            TimelineEvent.entity_type == entity_type,
            TimelineEvent.entity_id == entity_id,
            TimelineEvent.occurred_at > at,
        )
        .order_by(TimelineEvent.occurred_at.desc())
    ).all()

    for ev in events:
        changes = (ev.payload or {}).get("changes") or {}
        if not isinstance(changes, dict):
            continue
        for field, diff in changes.items():
            if not isinstance(diff, dict):
                continue
            # reverse: go back to "from"
            if "from" in diff:
                state[field] = diff["from"]

    return {
        "entity_type": entity_type,
        "entity_id": entity_id,
        "as_of": at.isoformat(),
        "exists": True,
        "state": state,
        "events_reversed": len(events),
    }


def search_audit(
    db: Session,
    workspace_id: str,
    *,
    actor_user_id: str | None = None,
    actor_api_key_id: str | None = None,
    action: str | None = None,
    entity_type: str | None = None,
    entity_id: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    q = select(AuditLog).where(AuditLog.workspace_id == workspace_id)
    if actor_user_id:
        q = q.where(AuditLog.actor_user_id == actor_user_id)
    if actor_api_key_id:
        q = q.where(AuditLog.actor_api_key_id == actor_api_key_id)
    if action:
        q = q.where(AuditLog.action == action)
    if entity_type:
        q = q.where(AuditLog.entity_type == entity_type)
    if entity_id:
        q = q.where(AuditLog.entity_id == entity_id)
    if since:
        q = q.where(AuditLog.created_at >= since)
    if until:
        q = q.where(AuditLog.created_at <= until)
    q = q.order_by(AuditLog.created_at.desc()).limit(min(limit, 500))
    rows = db.scalars(q).all()
    return [
        {
            "id": r.id,
            "action": r.action,
            "entity_type": r.entity_type,
            "entity_id": r.entity_id,
            "actor_user_id": r.actor_user_id,
            "actor_api_key_id": r.actor_api_key_id,
            "payload": r.payload or {},
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]


def _row_dict(row: Any) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for col in row.__table__.columns:
        v = getattr(row, col.name)
        if hasattr(v, "isoformat"):
            out[col.name] = v.isoformat()
        elif hasattr(v, "value"):
            out[col.name] = v.value
        elif isinstance(v, float | int | str | bool | list | dict) or v is None:
            out[col.name] = v
        else:
            out[col.name] = str(v)
    return out
