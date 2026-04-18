from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import Pagination, Principal, get_pagination, get_principal
from app.models import Contact, EntityType
from app.schemas import BulkUpsertResult, ContactIn, ContactOut, ContactPatch, Page
from app.services.events import emit
from app.services.pagination import apply_cursor, encode_cursor

router = APIRouter(prefix="/contacts", tags=["contacts"])


def _base_query(db: Session, workspace_id: str, include_deleted: bool):
    q = select(Contact).where(Contact.workspace_id == workspace_id)
    if not include_deleted:
        q = q.where(Contact.deleted_at.is_(None))
    return q


@router.get("", response_model=Page[ContactOut])
def list_contacts(
    db: Session = Depends(get_db),
    p: Principal = Depends(get_principal),
    page: Pagination = Depends(get_pagination),
    q: Optional[str] = Query(None, description="substring match on first/last name/email"),
    email: Optional[str] = None,
    company_id: Optional[str] = None,
    tag: Optional[str] = None,
    include_deleted: bool = False,
):
    query = _base_query(db, p.workspace.id, include_deleted)
    if q:
        like = f"%{q.lower()}%"
        query = query.where(
            or_(
                func.lower(Contact.first_name).like(like),
                func.lower(Contact.last_name).like(like),
                func.lower(Contact.email).like(like),
            )
        )
    if email:
        query = query.where(func.lower(Contact.email) == email.lower())
    if company_id:
        query = query.where(Contact.company_id == company_id)
    if tag:
        query = query.where(Contact.tags.contains([tag]))

    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    query = apply_cursor(query, model=Contact, cursor=page.cursor)
    query = query.order_by(Contact.created_at.desc(), Contact.id.desc()).limit(page.limit + 1)

    rows = db.scalars(query).all()
    next_cursor = None
    if len(rows) > page.limit:
        last = rows[page.limit - 1]
        next_cursor = encode_cursor(last.created_at, last.id)
        rows = rows[: page.limit]
    return Page[ContactOut](
        items=[ContactOut.model_validate(r) for r in rows],
        next_cursor=next_cursor,
        count=total,
    )


@router.post("", response_model=ContactOut, status_code=201)
def create_contact(
    payload: ContactIn,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    p: Principal = Depends(get_principal),
) -> ContactOut:
    c = Contact(workspace_id=p.workspace.id, **payload.model_dump())
    db.add(c)
    try:
        db.flush()
    except Exception as e:  # noqa: BLE001
        db.rollback()
        raise HTTPException(status_code=409, detail=f"conflict: {e.__class__.__name__}")
    emit(db, p, event_type="contact.created", entity_type=EntityType.contact,
         entity_id=c.id, payload={"contact_id": c.id}, background=background)
    db.commit()
    db.refresh(c)
    return ContactOut.model_validate(c)


@router.get("/{contact_id}", response_model=ContactOut)
def get_contact(contact_id: str, db: Session = Depends(get_db), p: Principal = Depends(get_principal)):
    c = db.get(Contact, contact_id)
    if not c or c.workspace_id != p.workspace.id:
        raise HTTPException(status_code=404, detail="not found")
    return ContactOut.model_validate(c)


@router.patch("/{contact_id}", response_model=ContactOut)
def patch_contact(
    contact_id: str,
    payload: ContactPatch,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    p: Principal = Depends(get_principal),
) -> ContactOut:
    c = db.get(Contact, contact_id)
    if not c or c.workspace_id != p.workspace.id:
        raise HTTPException(status_code=404, detail="not found")
    updates = payload.model_dump(exclude_unset=True)
    for k, v in updates.items():
        setattr(c, k, v)
    emit(db, p, event_type="contact.updated", entity_type=EntityType.contact,
         entity_id=c.id, payload={"changes": list(updates.keys())}, background=background)
    db.commit()
    db.refresh(c)
    return ContactOut.model_validate(c)


@router.delete("/{contact_id}")
def delete_contact(
    contact_id: str,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    p: Principal = Depends(get_principal),
    hard: bool = False,
):
    c = db.get(Contact, contact_id)
    if not c or c.workspace_id != p.workspace.id:
        raise HTTPException(status_code=404, detail="not found")
    if hard:
        db.delete(c)
    else:
        c.deleted_at = datetime.now(timezone.utc)
    emit(db, p, event_type="contact.deleted", entity_type=EntityType.contact,
         entity_id=c.id, payload={"hard": hard}, background=background)
    db.commit()
    return {"ok": True}


@router.post("/bulk_upsert", response_model=BulkUpsertResult)
def bulk_upsert(
    items: list[ContactIn],
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    p: Principal = Depends(get_principal),
) -> BulkUpsertResult:
    created = updated = 0
    ids: list[str] = []
    for item in items:
        existing = None
        if item.external_id:
            existing = db.scalar(
                select(Contact).where(
                    Contact.workspace_id == p.workspace.id,
                    Contact.external_id == item.external_id,
                )
            )
        elif item.email:
            existing = db.scalar(
                select(Contact).where(
                    Contact.workspace_id == p.workspace.id,
                    func.lower(Contact.email) == item.email.lower(),
                )
            )
        if existing:
            for k, v in item.model_dump(exclude_unset=True).items():
                setattr(existing, k, v)
            updated += 1
            ids.append(existing.id)
            emit(db, p, event_type="contact.updated", entity_type=EntityType.contact,
                 entity_id=existing.id, payload={"via": "bulk_upsert"}, background=background)
        else:
            c = Contact(workspace_id=p.workspace.id, **item.model_dump())
            db.add(c)
            db.flush()
            created += 1
            ids.append(c.id)
            emit(db, p, event_type="contact.created", entity_type=EntityType.contact,
                 entity_id=c.id, payload={"via": "bulk_upsert"}, background=background)
    db.commit()
    return BulkUpsertResult(created=created, updated=updated, ids=ids)
