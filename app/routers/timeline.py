from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import Pagination, Principal, get_pagination, get_principal
from app.models import EntityType, TimelineEvent
from app.schemas import Page, TimelineEventOut

router = APIRouter(prefix="/timeline", tags=["timeline"])


def _paginate(db: Session, query, page: Pagination):
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    # Timeline uses integer id + occurred_at; order newest first.
    q = query.order_by(TimelineEvent.occurred_at.desc(), TimelineEvent.id.desc())
    # For simplicity, cursor here is just an id offset.
    if page.cursor:
        try:
            cut = int(page.cursor)
            q = q.where(TimelineEvent.id < cut)
        except ValueError:
            pass
    q = q.limit(page.limit + 1)
    rows = db.scalars(q).all()
    next_cursor = None
    if len(rows) > page.limit:
        next_cursor = str(rows[page.limit - 1].id)
        rows = rows[: page.limit]
    return Page[TimelineEventOut](
        items=[TimelineEventOut.model_validate(r) for r in rows],
        next_cursor=next_cursor,
        count=total,
    )


@router.get("", response_model=Page[TimelineEventOut])
def workspace_timeline(
    db: Session = Depends(get_db),
    p: Principal = Depends(get_principal),
    page: Pagination = Depends(get_pagination),
    event_type: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
):
    query = select(TimelineEvent).where(TimelineEvent.workspace_id == p.workspace.id)
    if event_type:
        query = query.where(TimelineEvent.event_type == event_type)
    if since:
        query = query.where(TimelineEvent.occurred_at >= since)
    if until:
        query = query.where(TimelineEvent.occurred_at <= until)
    return _paginate(db, query, page)


@router.get("/{entity_type}/{entity_id}", response_model=Page[TimelineEventOut])
def entity_timeline(
    entity_type: EntityType,
    entity_id: str,
    db: Session = Depends(get_db),
    p: Principal = Depends(get_principal),
    page: Pagination = Depends(get_pagination),
):
    query = select(TimelineEvent).where(
        TimelineEvent.workspace_id == p.workspace.id,
        TimelineEvent.entity_type == entity_type,
        TimelineEvent.entity_id == entity_id,
    )
    return _paginate(db, query, page)
