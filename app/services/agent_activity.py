"""P5.6 agent_activity — structured workforce facts from timeline (not orchestration)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    ApiKey,
    ApprovalRequest,
    ApprovalStatus,
    EntityType,
    TimelineEvent,
)
from app.services.agent_identity import agent_display_name


def build_agent_activity(
    db: Session,
    workspace_id: str,
    *,
    since: datetime,
    until: datetime | None = None,
    agent_api_key_id: str | None = None,
    entity_type: str | None = None,
    event_type_prefix: str | None = None,
) -> dict[str, Any]:
    """Aggregate business-facing counts for one or all agent keys since ``since``."""
    q = select(TimelineEvent).where(
        TimelineEvent.workspace_id == workspace_id,
        TimelineEvent.occurred_at >= since,
    )
    if until:
        q = q.where(TimelineEvent.occurred_at <= until)
    if agent_api_key_id:
        q = q.where(TimelineEvent.actor_api_key_id == agent_api_key_id)
    if entity_type:
        try:
            q = q.where(TimelineEvent.entity_type == EntityType(entity_type))
        except ValueError as e:
            raise ValueError(f"unsupported entity_type: {entity_type}") from e
    if event_type_prefix:
        q = q.where(TimelineEvent.event_type.startswith(event_type_prefix))

    events = db.scalars(q).all()
    agent_label = None
    if agent_api_key_id:
        key = db.get(ApiKey, agent_api_key_id)
        if key and key.workspace_id == workspace_id:
            agent_label = agent_display_name(key)

    companies_touched: set[str] = set()
    contacts_touched: set[str] = set()
    deals_touched: set[str] = set()
    activities_logged = 0
    event_counts: dict[str, int] = {}

    for ev in events:
        event_counts[ev.event_type] = event_counts.get(ev.event_type, 0) + 1
        if ev.entity_type == EntityType.company and ev.entity_id:
            companies_touched.add(ev.entity_id)
        elif ev.entity_type == EntityType.contact and ev.entity_id:
            contacts_touched.add(ev.entity_id)
        elif ev.entity_type == EntityType.deal and ev.entity_id:
            deals_touched.add(ev.entity_id)
        if ev.event_type.startswith("activity."):
            activities_logged += 1

    pending_q = select(func.count()).select_from(ApprovalRequest).where(
        ApprovalRequest.workspace_id == workspace_id,
        ApprovalRequest.deleted_at.is_(None),
        ApprovalRequest.status == ApprovalStatus.pending,
    )
    if agent_api_key_id:
        pending_q = pending_q.where(ApprovalRequest.requested_by_api_key_id == agent_api_key_id)
    approvals_pending = db.scalar(pending_q) or 0

    # Heuristic enrichments aligned with workforce demo language
    companies_created = event_counts.get("company.created", 0)
    contacts_created = event_counts.get("contact.created", 0)

    return {
        "protocol": "nakatomi.agent_activity/v1",
        "since": since.isoformat(),
        "until": until.isoformat() if until else None,
        "agent_api_key_id": agent_api_key_id,
        "agent": agent_label or agent_api_key_id,
        "timeline_events": len(events),
        "companies_created": companies_created,
        "companies_touched": len(companies_touched),
        "contacts_created": contacts_created,
        "contacts_touched": len(contacts_touched),
        "opportunities_touched": len(deals_touched),
        "activities_logged": activities_logged,
        "approvals_pending": approvals_pending,
        "event_type_counts": event_counts,
    }


def list_workspace_agents(db: Session, workspace_id: str) -> list[dict[str, Any]]:
    """Roster of non-revoked API keys with agent identity conventions."""
    from app.services.agent_identity import agent_profile_from_key

    keys = db.scalars(
        select(ApiKey)
        .where(
            ApiKey.workspace_id == workspace_id,
            ApiKey.revoked_at.is_(None),
        )
        .order_by(ApiKey.name.asc())
    ).all()
    # Omit OAuth refresh-token rows from workforce roster
    out: list[dict[str, Any]] = []
    for k in keys:
        kind = (k.data or {}).get("oauth", {}).get("kind")
        if kind == "refresh":
            continue
        if k.name.startswith("oauth:"):
            continue
        out.append(agent_profile_from_key(k))
    return out
