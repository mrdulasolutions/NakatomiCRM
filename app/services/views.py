"""Saved-view filter DSL runner.

Filter clause shape::

    {"field": "status", "op": "eq", "value": "open"}

Ops: eq, ne, in, gt, gte, lt, lte, contains, is_null, is_not_null, tag_any,
relative date helpers on datetime fields:
  value ``P7D`` / ``-P14D`` with op ``lte``/``gte`` relative to now.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import Select, and_, func, select
from sqlalchemy.orm import Session

from app.models import (
    ApprovalRequest,
    ApprovalStatus,
    Company,
    Contact,
    Deal,
    DealStatus,
    Lead,
    LeadStatus,
    Task,
    TaskStatus,
)

_ENTITY_MODELS: dict[str, Any] = {
    "contact": Contact,
    "company": Company,
    "deal": Deal,
    "lead": Lead,
    "task": Task,
    "approval": ApprovalRequest,
}

_DURATION = re.compile(r"^(-)?P(?:(\d+)D)?(?:T(?:(\d+)H)?)?$", re.I)


def parse_relative(value: str) -> datetime | None:
    if not isinstance(value, str):
        return None
    m = _DURATION.match(value.strip())
    if not m:
        return None
    sign = -1 if m.group(1) else 1
    days = int(m.group(2) or 0) * sign
    hours = int(m.group(3) or 0) * sign
    return datetime.now(UTC) + timedelta(days=days, hours=hours)


def _col(model: Any, field: str):
    if not hasattr(model, field):
        raise ValueError(f"unknown field {field} on {model.__tablename__}")
    return getattr(model, field)


def apply_filters(query: Select, model: Any, filters: list[dict]) -> Select:
    clauses = []
    for f in filters or []:
        field = f.get("field")
        op = (f.get("op") or "eq").lower()
        value = f.get("value")
        if not field:
            continue
        if field == "tags" and op in ("tag_any", "contains"):
            # tags is JSONB list
            tags = value if isinstance(value, list) else [value]
            for t in tags:
                clauses.append(model.tags.contains([t]))
            continue
        col = _col(model, field)
        if op in ("lte", "gte", "lt", "gt") and isinstance(value, str) and value.startswith(("-P", "P")):
            rel = parse_relative(value)
            if rel is not None:
                value = rel
        if op == "eq":
            clauses.append(col == value)
        elif op == "ne":
            clauses.append(col != value)
        elif op == "in":
            clauses.append(col.in_(value if isinstance(value, list) else [value]))
        elif op == "gt":
            clauses.append(col > value)
        elif op == "gte":
            clauses.append(col >= value)
        elif op == "lt":
            clauses.append(col < value)
        elif op == "lte":
            clauses.append(col <= value)
        elif op == "contains":
            clauses.append(func.lower(col).like(f"%{str(value).lower()}%"))
        elif op == "is_null":
            clauses.append(col.is_(None))
        elif op == "is_not_null":
            clauses.append(col.is_not(None))
        else:
            raise ValueError(f"unsupported op: {op}")
    if clauses:
        query = query.where(and_(*clauses))
    return query


def apply_sort(query: Select, model: Any, sort: list[dict]) -> Select:
    if not sort:
        if hasattr(model, "created_at"):
            return query.order_by(model.created_at.desc())
        return query
    order = []
    for s in sort:
        field = s.get("field", "created_at")
        direction = (s.get("dir") or "desc").lower()
        col = _col(model, field)
        order.append(col.asc() if direction == "asc" else col.desc())
    return query.order_by(*order)


def run_view(
    db: Session,
    workspace_id: str,
    *,
    entity_type: str,
    filters: list[dict],
    sort: list[dict],
    limit: int = 50,
) -> list[Any]:
    model = _ENTITY_MODELS.get(entity_type)
    if model is None:
        raise ValueError(f"unsupported entity_type: {entity_type}")
    query = select(model).where(model.workspace_id == workspace_id)
    if hasattr(model, "deleted_at"):
        query = query.where(model.deleted_at.is_(None))
    query = apply_filters(query, model, filters)
    query = apply_sort(query, model, sort)
    query = query.limit(min(limit, 500))
    return list(db.scalars(query).all())


DEFAULT_VIEWS: list[dict] = [
    {
        "name": "Open deals",
        "slug": "open_deals",
        "entity_type": "deal",
        "filters": [{"field": "status", "op": "eq", "value": DealStatus.open.value}],
        "sort": [{"field": "updated_at", "dir": "desc"}],
        "is_default": True,
    },
    {
        "name": "Tasks due this week",
        "slug": "tasks_due_this_week",
        "entity_type": "task",
        "filters": [
            {"field": "status", "op": "in", "value": [TaskStatus.open.value, TaskStatus.in_progress.value]},
            {"field": "due_at", "op": "lte", "value": "P7D"},
            {"field": "due_at", "op": "is_not_null", "value": None},
        ],
        "sort": [{"field": "due_at", "dir": "asc"}],
        "is_default": True,
    },
    {
        "name": "New leads",
        "slug": "new_leads",
        "entity_type": "lead",
        "filters": [{"field": "status", "op": "eq", "value": LeadStatus.new.value}],
        "sort": [{"field": "created_at", "dir": "desc"}],
        "is_default": True,
    },
    {
        "name": "Pending approvals",
        "slug": "pending_approvals",
        "entity_type": "approval",
        "filters": [{"field": "status", "op": "eq", "value": ApprovalStatus.pending.value}],
        "sort": [{"field": "created_at", "dir": "desc"}],
        "is_default": True,
    },
    {
        "name": "Stale deals (14d)",
        "slug": "stale_deals",
        "entity_type": "deal",
        "filters": [
            {"field": "status", "op": "eq", "value": DealStatus.open.value},
            {"field": "updated_at", "op": "lte", "value": "-P14D"},
        ],
        "sort": [{"field": "updated_at", "dir": "asc"}],
        "is_default": True,
    },
]
