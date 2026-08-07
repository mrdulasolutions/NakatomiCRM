"""Leads CRUD + convert."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import Pagination, Principal, enforce_resource_scope, get_pagination, get_principal
from app.models import Contact, EntityType, Lead, LeadStatus
from app.schemas import (
    LeadConvertRequest,
    LeadConvertResponse,
    LeadIn,
    LeadOut,
    LeadPatch,
    Page,
)
from app.services.events import emit
from app.services.leads import convert_lead
from app.services.pagination import apply_cursor, encode_cursor

router = APIRouter(
    prefix="/leads",
    tags=["leads"],
    dependencies=[Depends(enforce_resource_scope("leads"))],
)


def _out(row: Lead) -> LeadOut:
    return LeadOut(
        id=row.id,
        external_id=row.external_id,
        first_name=row.first_name,
        last_name=row.last_name,
        email=row.email,
        phone=row.phone,
        title=row.title,
        company_name=row.company_name,
        company_domain=row.company_domain,
        source=row.source,
        status=row.status.value if hasattr(row.status, "value") else str(row.status),
        score=float(row.score) if row.score is not None else None,
        owner_user_id=row.owner_user_id,
        converted_contact_id=row.converted_contact_id,
        converted_company_id=row.converted_company_id,
        converted_deal_id=row.converted_deal_id,
        converted_at=row.converted_at,
        tags=row.tags or [],
        data=row.data or {},
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.get("", response_model=Page[LeadOut])
def list_leads(
    db: Session = Depends(get_db),
    p: Principal = Depends(get_principal),
    page: Pagination = Depends(get_pagination),
    q: str | None = None,
    status: str | None = None,
    email: str | None = None,
    include_deleted: bool = False,
):
    query = select(Lead).where(Lead.workspace_id == p.workspace.id)
    if not include_deleted:
        query = query.where(Lead.deleted_at.is_(None))
    if status:
        query = query.where(Lead.status == status)
    if email:
        query = query.where(func.lower(Lead.email) == email.lower())
    if q:
        like = f"%{q.lower()}%"
        query = query.where(
            or_(
                func.lower(Lead.first_name).like(like),
                func.lower(Lead.last_name).like(like),
                func.lower(Lead.email).like(like),
                func.lower(Lead.company_name).like(like),
            )
        )
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    query = apply_cursor(query, model=Lead, cursor=page.cursor)
    query = query.order_by(Lead.created_at.desc(), Lead.id.desc()).limit(page.limit + 1)
    rows = list(db.scalars(query).all())
    next_cursor = None
    if len(rows) > page.limit:
        last = rows[page.limit - 1]
        next_cursor = encode_cursor(last.created_at, last.id)
        rows = rows[: page.limit]
    return Page[LeadOut](items=[_out(r) for r in rows], next_cursor=next_cursor, count=total)


@router.post("", response_model=LeadOut, status_code=201)
def create_lead(
    payload: LeadIn,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    p: Principal = Depends(get_principal),
) -> LeadOut:
    data = payload.model_dump()
    status = data.pop("status", None) or LeadStatus.new.value
    try:
        st = LeadStatus(status)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=f"invalid status: {status}") from e
    from app.services.policies import apply_auto_tasks, evaluate_write

    evaluate_write(
        p,
        entity_type="lead",
        action="lead.created",
        payload={**data, "status": st.value},
    )
    row = Lead(workspace_id=p.workspace.id, status=st, **data)
    db.add(row)
    db.flush()
    emit(
        db,
        p,
        event_type="lead.created",
        entity_type=EntityType.lead,
        entity_id=row.id,
        payload={"lead_id": row.id},
        background=background,
    )
    apply_auto_tasks(
        db,
        p,
        event="lead.created",
        entity_type="lead",
        entity_id=row.id,
        title_fallback=f"Qualify lead {row.email or row.id[:8]}",
    )
    db.commit()
    db.refresh(row)
    return _out(row)


@router.get("/{lead_id}", response_model=LeadOut)
def get_lead(lead_id: str, db: Session = Depends(get_db), p: Principal = Depends(get_principal)):
    row = db.get(Lead, lead_id)
    if not row or row.workspace_id != p.workspace.id:
        raise HTTPException(status_code=404, detail="not found")
    return _out(row)


@router.patch("/{lead_id}", response_model=LeadOut)
def patch_lead(
    lead_id: str,
    payload: LeadPatch,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    p: Principal = Depends(get_principal),
) -> LeadOut:
    row = db.get(Lead, lead_id)
    if not row or row.workspace_id != p.workspace.id:
        raise HTTPException(status_code=404, detail="not found")
    updates = payload.model_dump(exclude_unset=True)
    if "status" in updates and updates["status"] is not None:
        try:
            updates["status"] = LeadStatus(updates["status"])
        except ValueError as e:
            raise HTTPException(status_code=422, detail=f"invalid status: {updates['status']}") from e
    for k, v in updates.items():
        setattr(row, k, v)
    emit(
        db,
        p,
        event_type="lead.updated",
        entity_type=EntityType.lead,
        entity_id=row.id,
        payload={"changes": list(updates.keys())},
        background=background,
    )
    db.commit()
    db.refresh(row)
    return _out(row)


@router.post("/{lead_id}/convert", response_model=LeadConvertResponse)
def convert(
    lead_id: str,
    payload: LeadConvertRequest,
    db: Session = Depends(get_db),
    p: Principal = Depends(get_principal),
) -> LeadConvertResponse:
    row = db.get(Lead, lead_id)
    if not row or row.workspace_id != p.workspace.id or row.deleted_at:
        raise HTTPException(status_code=404, detail="not found")
    try:
        result = convert_lead(
            db,
            p,
            row,
            create_company=payload.create_company,
            create_deal=payload.create_deal,
            deal_name=payload.deal_name,
            pipeline_id=payload.pipeline_id,
            stage_id=payload.stage_id,
            amount=payload.amount,
            link_existing_contact=payload.link_existing_contact,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return LeadConvertResponse(**result)


@router.get("/{lead_id}/duplicates")
def lead_contact_duplicates(
    lead_id: str,
    db: Session = Depends(get_db),
    p: Principal = Depends(get_principal),
):
    """Contacts that match this lead's email (pre-convert hygiene)."""
    row = db.get(Lead, lead_id)
    if not row or row.workspace_id != p.workspace.id:
        raise HTTPException(status_code=404, detail="not found")
    if not row.email:
        return {"items": [], "count": 0}
    matches = db.scalars(
        select(Contact).where(
            Contact.workspace_id == p.workspace.id,
            func.lower(Contact.email) == row.email.lower(),
            Contact.deleted_at.is_(None),
        )
    ).all()
    return {
        "items": [
            {
                "id": c.id,
                "email": c.email,
                "first_name": c.first_name,
                "last_name": c.last_name,
            }
            for c in matches
        ],
        "count": len(matches),
    }


@router.delete("/{lead_id}")
def delete_lead(
    lead_id: str,
    db: Session = Depends(get_db),
    p: Principal = Depends(get_principal),
    hard: bool = False,
):
    row = db.get(Lead, lead_id)
    if not row or row.workspace_id != p.workspace.id:
        raise HTTPException(status_code=404, detail="not found")
    if hard:
        if not p.can("leads:delete"):
            raise HTTPException(status_code=403, detail="hard delete requires leads:delete")
        db.delete(row)
    else:
        row.deleted_at = datetime.now(UTC)
    db.commit()
    return {"ok": True}
