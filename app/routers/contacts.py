from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import Pagination, Principal, get_pagination, get_principal, require_role
from app.models import Contact, EntityType, MemberRole
from app.schemas import (
    BulkUpsertResult,
    ContactIn,
    ContactMergeRequest,
    ContactMergeResponse,
    ContactOut,
    ContactPatch,
    Page,
)
from app.services.diffs import compute_changes
from app.services.events import emit
from app.services.merge import merge_contacts
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
    q: str | None = Query(None, description="substring match on first/last name/email"),
    email: str | None = None,
    company_id: str | None = None,
    tag: str | None = None,
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
    emit(
        db,
        p,
        event_type="contact.created",
        entity_type=EntityType.contact,
        entity_id=c.id,
        payload={"contact_id": c.id},
        background=background,
    )
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
    changes = compute_changes(c, list(updates.keys()))
    emit(
        db,
        p,
        event_type="contact.updated",
        entity_type=EntityType.contact,
        entity_id=c.id,
        payload={"changes": changes},
        background=background,
    )
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
        c.deleted_at = datetime.now(UTC)
    emit(
        db,
        p,
        event_type="contact.deleted",
        entity_type=EntityType.contact,
        entity_id=c.id,
        payload={"hard": hard},
        background=background,
    )
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
            emit(
                db,
                p,
                event_type="contact.updated",
                entity_type=EntityType.contact,
                entity_id=existing.id,
                payload={"via": "bulk_upsert"},
                background=background,
            )
        else:
            c = Contact(workspace_id=p.workspace.id, **item.model_dump())
            db.add(c)
            db.flush()
            created += 1
            ids.append(c.id)
            emit(
                db,
                p,
                event_type="contact.created",
                entity_type=EntityType.contact,
                entity_id=c.id,
                payload={"via": "bulk_upsert"},
                background=background,
            )
    db.commit()
    return BulkUpsertResult(created=created, updated=updated, ids=ids)


@router.post("/merge", response_model=ContactMergeResponse)
def merge_endpoint(
    req: ContactMergeRequest,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    p: Principal = Depends(require_role(MemberRole.owner, MemberRole.admin)),
) -> ContactMergeResponse:
    """Merge two duplicate contacts — owner/admin only because it's destructive.

    The ``winner_id`` contact is kept and enriched with non-conflicting fields
    from the ``loser_id``; the loser is soft-deleted with ``data.merged_into``
    pointing at the winner. All references (deal.primary_contact_id,
    relationships, notes/tasks/activities/files/memory_links) are rewritten.

    Pass ``dry_run=true`` to preview. Use ``field_preferences`` to override the
    default "winner wins unless null" rule per field:

        {"field_preferences": {"title": "loser"}}
    """
    try:
        result = merge_contacts(
            db,
            p.workspace.id,
            winner_id=req.winner_id,
            loser_id=req.loser_id,
            field_preferences=req.field_preferences,
            dry_run=req.dry_run,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if not req.dry_run:
        emit(
            db,
            p,
            event_type="contact.merged",
            entity_type=EntityType.contact,
            entity_id=req.winner_id,
            payload={
                "loser_id": req.loser_id,
                "changes": result.changes,
                "references_rewritten": result.references_rewritten,
            },
            background=background,
        )
        db.commit()
    else:
        db.rollback()
    return ContactMergeResponse(
        winner_id=req.winner_id,
        loser_id=req.loser_id,
        changes=result.changes,
        references_rewritten=result.references_rewritten,
        warnings=result.warnings,
        dry_run=req.dry_run,
    )
