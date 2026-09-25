"""P5.5 explain_change — evidence chain for a material change."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ApprovalRequest, EntityType, TimelineEvent
from app.services.forensics import search_audit
from app.services.timeline_present import enrich_timeline_events


def explain_change(
    db: Session,
    workspace_id: str,
    entity_type: str,
    entity_id: str,
    *,
    event_id: int | None = None,
    since: datetime | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    """Return timeline + audit evidence for why an entity looks the way it does."""
    et = entity_type.lower().strip()
    try:
        EntityType(et)
    except ValueError as e:
        raise ValueError(f"unsupported entity_type: {entity_type}") from e
    q = select(TimelineEvent).where(
        TimelineEvent.workspace_id == workspace_id,
        TimelineEvent.entity_type == EntityType(et),
        TimelineEvent.entity_id == entity_id,
    )
    if event_id is not None:
        q = q.where(TimelineEvent.id == event_id)
    if since:
        q = q.where(TimelineEvent.occurred_at >= since)
    q = q.order_by(TimelineEvent.occurred_at.desc(), TimelineEvent.id.desc()).limit(min(limit, 50))
    events = db.scalars(q).all()
    timeline = enrich_timeline_events(db, workspace_id, events)

    audit = search_audit(
        db,
        workspace_id,
        entity_type=et,
        entity_id=entity_id,
        since=since,
        limit=limit,
    )

    approvals: list[dict[str, Any]] = []
    if events:
        ev = events[0]
        payload = ev.payload or {}
        approval_id = payload.get("approval_id")
        if approval_id:
            row = db.get(ApprovalRequest, approval_id)
            if row and row.workspace_id == workspace_id:
                approvals.append(
                    {
                        "id": row.id,
                        "action": row.action,
                        "status": row.status.value,
                        "decided_at": row.decided_at.isoformat() if row.decided_at else None,
                        "decision_note": row.decision_note,
                    }
                )

    return {
        "protocol": "nakatomi.explain_change/v1",
        "entity_type": et,
        "entity_id": entity_id,
        "focus_event_id": event_id,
        "timeline": timeline,
        "audit_log": audit,
        "approvals": approvals,
        "suggestion": "Read timeline entries with actor_label; cross-check audit_log.payload.changes when present.",
    }
