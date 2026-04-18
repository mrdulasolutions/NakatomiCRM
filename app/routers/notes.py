from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import Pagination, Principal, get_pagination, get_principal
from app.models import EntityType, Note
from app.schemas import NoteIn, NoteOut, OkResponse, Page
from app.services.events import emit
from app.services.pagination import apply_cursor, encode_cursor

router = APIRouter(prefix="/notes", tags=["notes"])


@router.get("", response_model=Page[NoteOut])
def list_notes(
    db: Session = Depends(get_db),
    p: Principal = Depends(get_principal),
    page: Pagination = Depends(get_pagination),
    entity_type: Optional[EntityType] = None,
    entity_id: Optional[str] = None,
):
    query = select(Note).where(Note.workspace_id == p.workspace.id)
    if entity_type:
        query = query.where(Note.entity_type == entity_type)
    if entity_id:
        query = query.where(Note.entity_id == entity_id)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    query = apply_cursor(query, model=Note, cursor=page.cursor)
    query = query.order_by(Note.created_at.desc(), Note.id.desc()).limit(page.limit + 1)
    rows = db.scalars(query).all()
    next_cursor = None
    if len(rows) > page.limit:
        last = rows[page.limit - 1]
        next_cursor = encode_cursor(last.created_at, last.id)
        rows = rows[: page.limit]
    return Page[NoteOut](
        items=[NoteOut.model_validate(r) for r in rows],
        next_cursor=next_cursor,
        count=total,
    )


@router.post("", response_model=NoteOut, status_code=201)
def create_note(
    payload: NoteIn,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    p: Principal = Depends(get_principal),
) -> NoteOut:
    n = Note(
        workspace_id=p.workspace.id,
        author_user_id=p.user_id,
        **payload.model_dump(),
    )
    db.add(n)
    db.flush()
    emit(db, p, event_type="note.created", entity_type=EntityType.note,
         entity_id=n.id, payload={"on": n.entity_type.value, "entity_id": n.entity_id},
         background=background)
    db.commit()
    db.refresh(n)
    return NoteOut.model_validate(n)


@router.patch("/{note_id}", response_model=NoteOut)
def patch_note(
    note_id: str,
    body: dict,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    p: Principal = Depends(get_principal),
) -> NoteOut:
    n = db.get(Note, note_id)
    if not n or n.workspace_id != p.workspace.id:
        raise HTTPException(status_code=404, detail="not found")
    if "body" in body:
        n.body = body["body"]
    if "data" in body:
        n.data = body["data"]
    emit(db, p, event_type="note.updated", entity_type=EntityType.note,
         entity_id=n.id, payload={}, background=background)
    db.commit()
    db.refresh(n)
    return NoteOut.model_validate(n)


@router.delete("/{note_id}", response_model=OkResponse)
def delete_note(
    note_id: str,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    p: Principal = Depends(get_principal),
) -> OkResponse:
    n = db.get(Note, note_id)
    if not n or n.workspace_id != p.workspace.id:
        raise HTTPException(status_code=404, detail="not found")
    db.delete(n)
    emit(db, p, event_type="note.deleted", entity_type=EntityType.note,
         entity_id=note_id, payload={}, background=background)
    db.commit()
    return OkResponse(message="deleted")
