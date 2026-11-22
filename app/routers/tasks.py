from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import Pagination, Principal, enforce_resource_scope, get_pagination, get_principal
from app.models import EntityType, Task, TaskStatus
from app.schemas import OkResponse, Page, TaskIn, TaskOut, TaskPatch
from app.services.entity_patch import apply_task_patch
from app.services.events import emit
from app.services.pagination import apply_cursor, encode_cursor

router = APIRouter(
    prefix="/tasks",
    tags=["tasks"],
    dependencies=[Depends(enforce_resource_scope("tasks"))],
)


@router.get("", response_model=Page[TaskOut])
def list_tasks(
    db: Session = Depends(get_db),
    p: Principal = Depends(get_principal),
    page: Pagination = Depends(get_pagination),
    status: TaskStatus | None = None,
    assignee_user_id: str | None = None,
    entity_type: EntityType | None = None,
    entity_id: str | None = None,
    due_before: datetime | None = None,
):
    query = select(Task).where(Task.workspace_id == p.workspace.id, Task.deleted_at.is_(None))
    if status:
        query = query.where(Task.status == status)
    if assignee_user_id:
        query = query.where(Task.assignee_user_id == assignee_user_id)
    if entity_type:
        query = query.where(Task.entity_type == entity_type)
    if entity_id:
        query = query.where(Task.entity_id == entity_id)
    if due_before:
        query = query.where(Task.due_at <= due_before)

    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    query = apply_cursor(query, model=Task, cursor=page.cursor)
    query = query.order_by(Task.created_at.desc(), Task.id.desc()).limit(page.limit + 1)
    rows = db.scalars(query).all()
    next_cursor = None
    if len(rows) > page.limit:
        last = rows[page.limit - 1]
        next_cursor = encode_cursor(last.created_at, last.id)
        rows = rows[: page.limit]
    return Page[TaskOut](
        items=[TaskOut.model_validate(r) for r in rows],
        next_cursor=next_cursor,
        count=total,
    )


@router.post("", response_model=TaskOut, status_code=201)
def create_task(
    payload: TaskIn,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    p: Principal = Depends(get_principal),
) -> TaskOut:
    t = Task(workspace_id=p.workspace.id, **payload.model_dump())
    db.add(t)
    db.flush()
    emit(
        db,
        p,
        event_type="task.created",
        entity_type=EntityType.task,
        entity_id=t.id,
        payload={"title": t.title},
        background=background,
    )
    db.commit()
    db.refresh(t)
    return TaskOut.model_validate(t)


@router.get("/{task_id}", response_model=TaskOut)
def get_task(task_id: str, db: Session = Depends(get_db), p: Principal = Depends(get_principal)):
    t = db.get(Task, task_id)
    if not t or t.workspace_id != p.workspace.id:
        raise HTTPException(status_code=404, detail="not found")
    return TaskOut.model_validate(t)


@router.patch("/{task_id}", response_model=TaskOut)
def patch_task(
    task_id: str,
    payload: TaskPatch,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    p: Principal = Depends(get_principal),
) -> TaskOut:
    t = db.get(Task, task_id)
    if not t or t.workspace_id != p.workspace.id:
        raise HTTPException(status_code=404, detail="not found")
    apply_task_patch(db, p, t, payload.model_dump(exclude_unset=True), background=background)
    db.commit()
    db.refresh(t)
    return TaskOut.model_validate(t)


@router.delete("/{task_id}", response_model=OkResponse)
def delete_task(
    task_id: str,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    p: Principal = Depends(get_principal),
    hard: bool = False,
) -> OkResponse:
    t = db.get(Task, task_id)
    if not t or t.workspace_id != p.workspace.id:
        raise HTTPException(status_code=404, detail="not found")
    if hard:
        db.delete(t)
    else:
        t.deleted_at = datetime.now(UTC)
    emit(
        db,
        p,
        event_type="task.deleted",
        entity_type=EntityType.task,
        entity_id=task_id,
        payload={"hard": hard},
        background=background,
    )
    db.commit()
    return OkResponse(message="deleted")
