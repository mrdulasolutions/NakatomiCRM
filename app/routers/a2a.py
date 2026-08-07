"""A2A REST binding — Agent Card helpers + Task lifecycle.

Binding choice: **REST** (not JSON-RPC) for operational simplicity with
FastAPI, OpenAPI, and existing API-key auth. See docs/A2A.md.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import Principal, require_scopes
from app.models import A2ATask, A2ATaskStatus, EntityType, Task, TaskStatus
from app.services.agent_card import build_agent_card
from app.services.approvals import create_approval
from app.services.events import emit

router = APIRouter(tags=["a2a"])


def _base_url(request: Request) -> str:
    proto = request.headers.get("x-forwarded-proto") or request.url.scheme
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or request.url.netloc
    return f"{proto}://{host}"


def _task_out(row: A2ATask) -> dict:
    return {
        "id": row.id,
        "status": row.status.value if hasattr(row.status, "value") else row.status,
        "skill": row.skill,
        "title": row.title,
        "description": row.description,
        "input": row.input or {},
        "result": row.result or {},
        "messages": row.messages or [],
        "artifacts": row.artifacts or [],
        "entity_type": row.entity_type,
        "entity_id": row.entity_id,
        "linked_task_id": row.linked_task_id,
        "linked_approval_id": row.linked_approval_id,
        "callback_url": row.callback_url,
        "context_etag": row.context_etag,
        "context_url": "/acp/context",
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "completed_at": row.completed_at.isoformat() if row.completed_at else None,
    }


@router.get("/a2a/agent-card")
def agent_card_via_a2a(request: Request) -> dict:
    """Same shape as /.well-known/agent-card.json — convenience under /a2a."""
    auth = request.headers.get("authorization") or ""
    extended = auth.lower().startswith("bearer ")
    return build_agent_card(base_url=_base_url(request), extended=extended)


class A2ATaskCreate(BaseModel):
    title: str
    description: str | None = None
    skill: str | None = None
    input: dict = Field(default_factory=dict)
    entity_type: str | None = None
    entity_id: str | None = None
    callback_url: str | None = None
    context_etag: str | None = None
    require_approval: bool = False
    create_crm_task: bool = False


class A2AMessageIn(BaseModel):
    role: str = "user"
    text: str | None = None
    parts: list[dict] = Field(default_factory=list)
    data: dict = Field(default_factory=dict)


class A2AStatusUpdate(BaseModel):
    result: dict | None = None
    artifact: dict | None = None
    note: str | None = None


@router.post("/a2a/tasks", status_code=201)
def create_a2a_task(
    payload: A2ATaskCreate,
    db: Session = Depends(get_db),
    p: Principal = Depends(require_scopes("a2a:invoke")),
) -> dict:
    now = datetime.now(UTC)
    messages = [
        {
            "role": "system",
            "parts": [{"type": "text", "text": "task submitted"}],
            "at": now.isoformat(),
        }
    ]
    linked_task_id = None
    if payload.create_crm_task:
        t = Task(
            workspace_id=p.workspace.id,
            title=payload.title,
            description=payload.description,
            status=TaskStatus.open,
            entity_type=EntityType(payload.entity_type) if payload.entity_type else None,
            entity_id=payload.entity_id,
            data={"via": "a2a"},
        )
        db.add(t)
        db.flush()
        linked_task_id = t.id

    row = A2ATask(
        workspace_id=p.workspace.id,
        status=A2ATaskStatus.working,
        skill=payload.skill,
        title=payload.title,
        description=payload.description,
        input=payload.input or {},
        messages=messages,
        entity_type=payload.entity_type,
        entity_id=payload.entity_id,
        linked_task_id=linked_task_id,
        callback_url=payload.callback_url,
        context_etag=payload.context_etag,
        requested_by_user_id=p.user_id,
        requested_by_api_key_id=p.api_key_id,
    )
    db.add(row)
    db.flush()

    if payload.require_approval:
        # create_approval commits; we set linkage then update status
        approval = create_approval(
            db,
            p,
            action=f"a2a.task:{payload.skill or 'generic'}",
            payload={"a2a_task_id": row.id, "title": payload.title, "input": payload.input},
            entity_type=payload.entity_type,
            entity_id=payload.entity_id,
            reason=f"A2A task requires HITL: {payload.title}",
        )
        row = db.get(A2ATask, row.id)
        assert row is not None
        row.linked_approval_id = approval.id
        row.status = A2ATaskStatus.input_required
        db.commit()
        db.refresh(row)
    else:
        emit(
            db,
            p,
            event_type="a2a.task.created",
            entity_type=EntityType.task,
            entity_id=row.id,
            payload={"a2a_task_id": row.id, "status": row.status.value, "skill": row.skill},
        )
        db.commit()
        db.refresh(row)

    return _task_out(row)


@router.get("/a2a/tasks")
def list_a2a_tasks(
    db: Session = Depends(get_db),
    p: Principal = Depends(require_scopes("a2a:invoke")),
    status_filter: str | None = Query(None, alias="status"),
    limit: int = Query(50, ge=1, le=200),
) -> list[dict]:
    q = select(A2ATask).where(
        A2ATask.workspace_id == p.workspace.id,
        A2ATask.deleted_at.is_(None),
    )
    if status_filter:
        q = q.where(A2ATask.status == status_filter)
    q = q.order_by(A2ATask.created_at.desc()).limit(limit)
    return [_task_out(r) for r in db.scalars(q).all()]


@router.get("/a2a/tasks/{task_id}")
def get_a2a_task(
    task_id: str,
    db: Session = Depends(get_db),
    p: Principal = Depends(require_scopes("a2a:invoke")),
) -> dict:
    row = db.get(A2ATask, task_id)
    if not row or row.workspace_id != p.workspace.id or row.deleted_at:
        raise HTTPException(status_code=404, detail="not found")
    return _task_out(row)


@router.post("/a2a/tasks/{task_id}/messages")
def add_message(
    task_id: str,
    payload: A2AMessageIn,
    db: Session = Depends(get_db),
    p: Principal = Depends(require_scopes("a2a:invoke")),
) -> dict:
    row = db.get(A2ATask, task_id)
    if not row or row.workspace_id != p.workspace.id or row.deleted_at:
        raise HTTPException(status_code=404, detail="not found")
    if row.status in (A2ATaskStatus.completed, A2ATaskStatus.failed, A2ATaskStatus.canceled):
        raise HTTPException(status_code=409, detail=f"task is {row.status.value}; cannot add messages")
    parts = list(payload.parts or [])
    if payload.text:
        parts.append({"type": "text", "text": payload.text})
    msgs = list(row.messages or [])
    msgs.append(
        {
            "role": payload.role,
            "parts": parts,
            "data": payload.data or {},
            "at": datetime.now(UTC).isoformat(),
        }
    )
    row.messages = msgs
    if row.status == A2ATaskStatus.submitted:
        row.status = A2ATaskStatus.working
    emit(
        db,
        p,
        event_type="a2a.task.updated",
        entity_type=EntityType.task,
        entity_id=row.id,
        payload={"a2a_task_id": row.id, "event": "message"},
    )
    db.commit()
    db.refresh(row)
    return _task_out(row)


@router.post("/a2a/tasks/{task_id}/cancel")
def cancel_task(
    task_id: str,
    db: Session = Depends(get_db),
    p: Principal = Depends(require_scopes("a2a:invoke")),
) -> dict:
    row = db.get(A2ATask, task_id)
    if not row or row.workspace_id != p.workspace.id or row.deleted_at:
        raise HTTPException(status_code=404, detail="not found")
    if row.status in (A2ATaskStatus.completed, A2ATaskStatus.failed, A2ATaskStatus.canceled):
        raise HTTPException(status_code=409, detail=f"task already terminal: {row.status.value}")
    row.status = A2ATaskStatus.canceled
    row.completed_at = datetime.now(UTC)
    emit(
        db,
        p,
        event_type="a2a.task.updated",
        entity_type=EntityType.task,
        entity_id=row.id,
        payload={"a2a_task_id": row.id, "status": "canceled"},
    )
    db.commit()
    db.refresh(row)
    return _task_out(row)


@router.post("/a2a/tasks/{task_id}/complete")
def complete_task(
    task_id: str,
    payload: A2AStatusUpdate,
    db: Session = Depends(get_db),
    p: Principal = Depends(require_scopes("a2a:invoke")),
) -> dict:
    row = db.get(A2ATask, task_id)
    if not row or row.workspace_id != p.workspace.id or row.deleted_at:
        raise HTTPException(status_code=404, detail="not found")
    if row.status in (A2ATaskStatus.completed, A2ATaskStatus.failed, A2ATaskStatus.canceled):
        raise HTTPException(status_code=409, detail=f"task already terminal: {row.status.value}")
    row.status = A2ATaskStatus.completed
    row.completed_at = datetime.now(UTC)
    if payload.result is not None:
        row.result = payload.result
    if payload.artifact:
        arts = list(row.artifacts or [])
        arts.append({**payload.artifact, "at": datetime.now(UTC).isoformat()})
        row.artifacts = arts
    emit(
        db,
        p,
        event_type="a2a.task.updated",
        entity_type=EntityType.task,
        entity_id=row.id,
        payload={"a2a_task_id": row.id, "status": "completed"},
    )
    db.commit()
    db.refresh(row)
    return _task_out(row)


@router.post("/a2a/tasks/{task_id}/fail")
def fail_task(
    task_id: str,
    payload: A2AStatusUpdate,
    db: Session = Depends(get_db),
    p: Principal = Depends(require_scopes("a2a:invoke")),
) -> dict:
    row = db.get(A2ATask, task_id)
    if not row or row.workspace_id != p.workspace.id or row.deleted_at:
        raise HTTPException(status_code=404, detail="not found")
    if row.status in (A2ATaskStatus.completed, A2ATaskStatus.failed, A2ATaskStatus.canceled):
        raise HTTPException(status_code=409, detail=f"task already terminal: {row.status.value}")
    row.status = A2ATaskStatus.failed
    row.completed_at = datetime.now(UTC)
    row.result = payload.result or {"error": payload.note or "failed"}
    emit(
        db,
        p,
        event_type="a2a.task.updated",
        entity_type=EntityType.task,
        entity_id=row.id,
        payload={"a2a_task_id": row.id, "status": "failed"},
    )
    db.commit()
    db.refresh(row)
    return _task_out(row)


@router.post("/a2a/tasks/{task_id}/input-required")
def mark_input_required(
    task_id: str,
    payload: A2AStatusUpdate,
    db: Session = Depends(get_db),
    p: Principal = Depends(require_scopes("a2a:invoke")),
) -> dict:
    """Park task for HITL — creates an ApprovalRequest linked to the task."""
    row = db.get(A2ATask, task_id)
    if not row or row.workspace_id != p.workspace.id or row.deleted_at:
        raise HTTPException(status_code=404, detail="not found")
    if row.status in (A2ATaskStatus.completed, A2ATaskStatus.failed, A2ATaskStatus.canceled):
        raise HTTPException(status_code=409, detail=f"task already terminal: {row.status.value}")
    approval = create_approval(
        db,
        p,
        action=f"a2a.task:{row.skill or 'generic'}",
        payload={"a2a_task_id": row.id, "note": payload.note, "result": payload.result},
        entity_type=row.entity_type,
        entity_id=row.entity_id,
        reason=payload.note or f"A2A task needs input: {row.title}",
    )
    row = db.get(A2ATask, task_id)
    assert row is not None
    row.status = A2ATaskStatus.input_required
    row.linked_approval_id = approval.id
    db.commit()
    db.refresh(row)
    return _task_out(row)
