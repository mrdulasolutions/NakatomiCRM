"""P5.1 entity_context — coherent business-state bundle for one entity."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models import (
    Activity,
    ApprovalRequest,
    ApprovalStatus,
    Company,
    Contact,
    Deal,
    EntityType,
    Lead,
    Note,
    Relationship,
    Task,
    TaskStatus,
    TimelineEvent,
)
from app.scopes import has_scope
from app.services.timeline_present import enrich_timeline_events

_PROTOCOL = "nakatomi.entity_context/v1"
_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.I,
)


def _escape_ilike_literal(ref: str) -> str:
    """Treat user ref as literal substring, not SQL wildcards."""
    return ref.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _ilike_literal(column, ref: str):
    pattern = f"%{_escape_ilike_literal(ref.strip())}%"
    return column.ilike(pattern, escape="\\")


_MODELS: dict[str, type] = {
    "company": Company,
    "contact": Contact,
    "deal": Deal,
    "lead": Lead,
}


def _row_dict(row: Any) -> dict[str, Any]:
    if row is None:
        return {}
    out: dict[str, Any] = {}
    for col in row.__table__.columns:
        val = getattr(row, col.name)
        if hasattr(val, "isoformat"):
            val = val.isoformat()
        elif hasattr(val, "value"):
            val = val.value
        out[col.name] = val
    return out


def resolve_entity_id(
    db: Session,
    workspace_id: str,
    entity_type: str,
    entity_ref: str,
) -> str:
    """Resolve UUID or human ref (company name/domain, contact email, deal name)."""
    et = entity_type.lower().strip()
    ref = entity_ref.strip()
    if not ref:
        raise ValueError("entity_ref required")
    model = _MODELS.get(et)
    if model is None:
        raise ValueError(f"unsupported entity_type: {entity_type}")

    if _UUID_RE.match(ref):
        row = db.get(model, ref)
        if row and row.workspace_id == workspace_id and getattr(row, "deleted_at", None) is None:
            return row.id
        raise ValueError("entity not found")

    if et == "company":
        row = db.scalar(
            select(Company)
            .where(
                Company.workspace_id == workspace_id,
                Company.deleted_at.is_(None),
                or_(_ilike_literal(Company.name, ref), _ilike_literal(Company.domain, ref)),
            )
            .order_by(Company.name.asc())
            .limit(1)
        )
    elif et == "contact":
        row = db.scalar(
            select(Contact)
            .where(
                Contact.workspace_id == workspace_id,
                Contact.deleted_at.is_(None),
                or_(_ilike_literal(Contact.email, ref), _ilike_literal(Contact.last_name, ref)),
            )
            .order_by(Contact.email.asc())
            .limit(1)
        )
    elif et == "deal":
        row = db.scalar(
            select(Deal)
            .where(
                Deal.workspace_id == workspace_id,
                Deal.deleted_at.is_(None),
                _ilike_literal(Deal.name, ref),
            )
            .order_by(Deal.name.asc())
            .limit(1)
        )
    elif et == "lead":
        row = db.scalar(
            select(Lead)
            .where(
                Lead.workspace_id == workspace_id,
                Lead.deleted_at.is_(None),
                or_(_ilike_literal(Lead.email, ref), _ilike_literal(Lead.company_name, ref)),
            )
            .order_by(Lead.email.asc())
            .limit(1)
        )
    else:
        row = None

    if not row:
        raise ValueError("entity not found")
    return row.id


def _related_contact_ids(db: Session, workspace_id: str, company_id: str) -> set[str]:
    ids: set[str] = set()
    edges = db.scalars(
        select(Relationship).where(
            Relationship.workspace_id == workspace_id,
            or_(
                (Relationship.source_type == EntityType.company) & (Relationship.source_id == company_id),
                (Relationship.target_type == EntityType.company) & (Relationship.target_id == company_id),
            ),
        )
    ).all()
    for e in edges:
        if e.source_type == EntityType.contact:
            ids.add(e.source_id)
        if e.target_type == EntityType.contact:
            ids.add(e.target_id)
    return ids


def build_entity_context(
    db: Session,
    workspace_id: str,
    entity_type: str,
    entity_ref: str,
    *,
    scopes: list[str] | None,
    timeline_limit: int = 40,
    include_notes: bool = True,
) -> dict[str, Any]:
    """Assemble entity-scoped business state for agent takeover."""
    scopes = scopes or ["*"]
    et = entity_type.lower().strip()
    entity_id = resolve_entity_id(db, workspace_id, et, entity_ref)
    model = _MODELS[et]
    row = db.get(model, entity_id)
    if not row or row.workspace_id != workspace_id or getattr(row, "deleted_at", None):
        raise ValueError("entity not found")

    read_scope = {
        "company": "companies:read",
        "contact": "contacts:read",
        "deal": "deals:read",
        "lead": "leads:read",
    }[et]

    def can(resource: str) -> bool:
        return has_scope(scopes, resource)

    now = datetime.now(UTC)
    bundle: dict[str, Any] = {
        "protocol": _PROTOCOL,
        "as_of": now.isoformat(),
        "entity_type": et,
        "entity_id": entity_id,
        "entity": _row_dict(row) if can(read_scope) else {"id": entity_id, "redacted": True},
        "relationships": [],
        "contacts": [],
        "deals": [],
        "activities": [],
        "tasks": [],
        "notes": [],
        "pending_approvals": [],
        "timeline": [],
    }

    # Graph edges touching this entity
    if can("relationships:read"):
        edges = db.scalars(
            select(Relationship).where(
                Relationship.workspace_id == workspace_id,
                or_(
                    (Relationship.source_type == EntityType(et)) & (Relationship.source_id == entity_id),
                    (Relationship.target_type == EntityType(et)) & (Relationship.target_id == entity_id),
                ),
            )
        ).all()
        bundle["relationships"] = [_row_dict(e) for e in edges]

    contact_ids: set[str] = set()
    if et == "company":
        if can("contacts:read"):
            contact_ids = _related_contact_ids(db, workspace_id, entity_id)
        if can("deals:read"):
            deals = db.scalars(
                select(Deal).where(
                    Deal.workspace_id == workspace_id,
                    Deal.deleted_at.is_(None),
                    Deal.company_id == entity_id,
                )
            ).all()
            bundle["deals"] = [_row_dict(d) for d in deals]
    elif et == "deal":
        deal = row
        if deal.company_id and can("companies:read"):
            co = db.get(Company, deal.company_id)
            if co and co.deleted_at is None and co.workspace_id == workspace_id:
                bundle["company"] = _row_dict(co)
        if deal.primary_contact_id:
            contact_ids.add(deal.primary_contact_id)
    elif et == "contact":
        contact_ids.add(entity_id)

    if contact_ids and can("contacts:read"):
        contacts = db.scalars(
            select(Contact).where(
                Contact.workspace_id == workspace_id,
                Contact.deleted_at.is_(None),
                Contact.id.in_(contact_ids),
            )
        ).all()
        bundle["contacts"] = [_row_dict(c) for c in contacts]

    entity_types_for_tasks = {EntityType(et)}
    entity_ids_for_tasks = {entity_id}
    if et == "company":
        entity_types_for_tasks.add(EntityType.deal)
        entity_ids_for_tasks.update(d.id for d in bundle.get("deals") or [])

    if can("tasks:read"):
        tasks = db.scalars(
            select(Task)
            .where(
                Task.workspace_id == workspace_id,
                Task.deleted_at.is_(None),
                Task.status.in_([TaskStatus.open, TaskStatus.in_progress]),
                Task.entity_type.in_(entity_types_for_tasks),
                Task.entity_id.in_(entity_ids_for_tasks),
            )
            .order_by(Task.due_at.asc().nulls_last())
            .limit(30)
        ).all()
        bundle["tasks"] = [_row_dict(t) for t in tasks]

    if can("activities:read"):
        activities = db.scalars(
            select(Activity)
            .where(
                Activity.workspace_id == workspace_id,
                Activity.deleted_at.is_(None),
                Activity.entity_type == EntityType(et),
                Activity.entity_id == entity_id,
            )
            .order_by(Activity.occurred_at.desc())
            .limit(25)
        ).all()
        bundle["activities"] = [_row_dict(a) for a in activities]

    if include_notes and can("notes:read"):
        notes = db.scalars(
            select(Note)
            .where(
                Note.workspace_id == workspace_id,
                Note.deleted_at.is_(None),
                Note.entity_type == EntityType(et),
                Note.entity_id == entity_id,
            )
            .order_by(Note.created_at.desc())
            .limit(15)
        ).all()
        bundle["notes"] = [_row_dict(n) for n in notes]

    if can("approvals:read"):
        pending = db.scalars(
            select(ApprovalRequest)
            .where(
                ApprovalRequest.workspace_id == workspace_id,
                ApprovalRequest.deleted_at.is_(None),
                ApprovalRequest.status == ApprovalStatus.pending,
                ApprovalRequest.entity_type == et,
                ApprovalRequest.entity_id == entity_id,
            )
            .order_by(ApprovalRequest.created_at.desc())
            .limit(20)
        ).all()
        bundle["pending_approvals"] = [_row_dict(a) for a in pending]

    if can("timeline:read"):
        tl_rows = db.scalars(
            select(TimelineEvent)
            .where(
                TimelineEvent.workspace_id == workspace_id,
                TimelineEvent.entity_type == EntityType(et),
                TimelineEvent.entity_id == entity_id,
            )
            .order_by(TimelineEvent.occurred_at.desc(), TimelineEvent.id.desc())
            .limit(min(timeline_limit, 100))
        ).all()
        bundle["timeline"] = enrich_timeline_events(db, workspace_id, tl_rows)

    # Related timeline on deals for company context
    if et == "company" and bundle["deals"] and can("timeline:read") and can("deals:read"):
        deal_ids = [d["id"] for d in bundle["deals"][:10]]
        deal_events = db.scalars(
            select(TimelineEvent)
            .where(
                TimelineEvent.workspace_id == workspace_id,
                TimelineEvent.entity_type == EntityType.deal,
                TimelineEvent.entity_id.in_(deal_ids),
            )
            .order_by(TimelineEvent.occurred_at.desc())
            .limit(20)
        ).all()
        bundle["related_deal_timeline"] = enrich_timeline_events(db, workspace_id, deal_events)

    return bundle
