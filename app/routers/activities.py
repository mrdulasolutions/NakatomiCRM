from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import Pagination, Principal, get_pagination, get_principal
from app.models import Activity, EntityType
from app.schemas import ActivityIn, ActivityOut, OkResponse, Page
from app.services.events import emit
from app.services.pagination import apply_cursor, encode_cursor

router = APIRouter(prefix="/activities", tags=["activities"])


@router.get("", response_model=Page[ActivityOut])
def list_activities(
    db: Session = Depends(get_db),
    p: Principal = Depends(get_principal),
    page: Pagination = Depends(get_pagination),
    kind: Optional[str] = None,
    entity_type: Optional[EntityType] = None,
    entity_id: Optional[str] = None,
):
    query = select(Activity).where(Activity.workspace_id == p.workspace.id)
    if kind:
        query = query.where(Activity.kind == kind)
    if entity_type:
        query = query.where(Activity.entity_type == entity_type)
    if entity_id:
        query = query.where(Activity.entity_id == entity_id)

    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    query = apply_cursor(query, model=Activity, cursor=page.cursor)
    query = query.order_by(Activity.created_at.desc(), Activity.id.desc()).limit(page.limit + 1)

    rows = db.scalars(query).all()
    next_cursor = None
    if len(rows) > page.limit:
        last = rows[page.limit - 1]
        next_cursor = encode_cursor(last.created_at, last.id)
        rows = rows[: page.limit]
    return Page[ActivityOut](
        items=[ActivityOut.model_validate(r) for r in rows],
        next_cursor=next_cursor,
        count=total,
    )


@router.post("", response_model=ActivityOut, status_code=201)
def create_activity(
    payload: ActivityIn,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    p: Principal = Depends(get_principal),
) -> ActivityOut:
    body = payload.model_dump()
    if not body.get("occurred_at"):
        from datetime import datetime, timezone

        body["occurred_at"] = datetime.now(timezone.utc)
    a = Activity(workspace_id=p.workspace.id, actor_user_id=p.user_id, **body)
    db.add(a)
    db.flush()
    emit(db, p, event_type="activity.created", entity_type=EntityType.activity,
         entity_id=a.id, payload={"kind": a.kind}, background=background)
    db.commit()
    db.refresh(a)
    return ActivityOut.model_validate(a)


@router.get("/{activity_id}", response_model=ActivityOut)
def get_activity(activity_id: str, db: Session = Depends(get_db), p: Principal = Depends(get_principal)):
    a = db.get(Activity, activity_id)
    if not a or a.workspace_id != p.workspace.id:
        raise HTTPException(status_code=404, detail="not found")
    return ActivityOut.model_validate(a)


@router.delete("/{activity_id}", response_model=OkResponse)
def delete_activity(
    activity_id: str,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    p: Principal = Depends(get_principal),
) -> OkResponse:
    a = db.get(Activity, activity_id)
    if not a or a.workspace_id != p.workspace.id:
        raise HTTPException(status_code=404, detail="not found")
    db.delete(a)
    emit(db, p, event_type="activity.deleted", entity_type=EntityType.activity,
         entity_id=activity_id, payload={}, background=background)
    db.commit()
    return OkResponse(message="deleted")
