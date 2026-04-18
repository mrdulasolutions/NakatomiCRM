from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import Pagination, Principal, get_pagination, get_principal
from app.models import Company, EntityType
from app.schemas import BulkUpsertResult, CompanyIn, CompanyOut, CompanyPatch, Page
from app.services.events import emit
from app.services.pagination import apply_cursor, encode_cursor

router = APIRouter(prefix="/companies", tags=["companies"])


@router.get("", response_model=Page[CompanyOut])
def list_companies(
    db: Session = Depends(get_db),
    p: Principal = Depends(get_principal),
    page: Pagination = Depends(get_pagination),
    q: str | None = Query(None),
    domain: str | None = None,
    tag: str | None = None,
    include_deleted: bool = False,
):
    query = select(Company).where(Company.workspace_id == p.workspace.id)
    if not include_deleted:
        query = query.where(Company.deleted_at.is_(None))
    if q:
        like = f"%{q.lower()}%"
        query = query.where(or_(func.lower(Company.name).like(like), func.lower(Company.domain).like(like)))
    if domain:
        query = query.where(func.lower(Company.domain) == domain.lower())
    if tag:
        query = query.where(Company.tags.contains([tag]))

    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    query = apply_cursor(query, model=Company, cursor=page.cursor)
    query = query.order_by(Company.created_at.desc(), Company.id.desc()).limit(page.limit + 1)

    rows = db.scalars(query).all()
    next_cursor = None
    if len(rows) > page.limit:
        last = rows[page.limit - 1]
        next_cursor = encode_cursor(last.created_at, last.id)
        rows = rows[: page.limit]
    return Page[CompanyOut](
        items=[CompanyOut.model_validate(r) for r in rows],
        next_cursor=next_cursor,
        count=total,
    )


@router.post("", response_model=CompanyOut, status_code=201)
def create_company(
    payload: CompanyIn,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    p: Principal = Depends(get_principal),
) -> CompanyOut:
    c = Company(workspace_id=p.workspace.id, **payload.model_dump())
    db.add(c)
    try:
        db.flush()
    except Exception as e:  # noqa: BLE001
        db.rollback()
        raise HTTPException(status_code=409, detail=f"conflict: {e.__class__.__name__}")
    emit(
        db,
        p,
        event_type="company.created",
        entity_type=EntityType.company,
        entity_id=c.id,
        payload={"company_id": c.id},
        background=background,
    )
    db.commit()
    db.refresh(c)
    return CompanyOut.model_validate(c)


@router.get("/{company_id}", response_model=CompanyOut)
def get_company(company_id: str, db: Session = Depends(get_db), p: Principal = Depends(get_principal)):
    c = db.get(Company, company_id)
    if not c or c.workspace_id != p.workspace.id:
        raise HTTPException(status_code=404, detail="not found")
    return CompanyOut.model_validate(c)


@router.patch("/{company_id}", response_model=CompanyOut)
def patch_company(
    company_id: str,
    payload: CompanyPatch,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    p: Principal = Depends(get_principal),
) -> CompanyOut:
    c = db.get(Company, company_id)
    if not c or c.workspace_id != p.workspace.id:
        raise HTTPException(status_code=404, detail="not found")
    updates = payload.model_dump(exclude_unset=True)
    for k, v in updates.items():
        setattr(c, k, v)
    emit(
        db,
        p,
        event_type="company.updated",
        entity_type=EntityType.company,
        entity_id=c.id,
        payload={"changes": list(updates.keys())},
        background=background,
    )
    db.commit()
    db.refresh(c)
    return CompanyOut.model_validate(c)


@router.delete("/{company_id}")
def delete_company(
    company_id: str,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    p: Principal = Depends(get_principal),
    hard: bool = False,
):
    c = db.get(Company, company_id)
    if not c or c.workspace_id != p.workspace.id:
        raise HTTPException(status_code=404, detail="not found")
    if hard:
        db.delete(c)
    else:
        c.deleted_at = datetime.now(UTC)
    emit(
        db,
        p,
        event_type="company.deleted",
        entity_type=EntityType.company,
        entity_id=c.id,
        payload={"hard": hard},
        background=background,
    )
    db.commit()
    return {"ok": True}


@router.post("/bulk_upsert", response_model=BulkUpsertResult)
def bulk_upsert(
    items: list[CompanyIn],
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
                select(Company).where(
                    Company.workspace_id == p.workspace.id,
                    Company.external_id == item.external_id,
                )
            )
        elif item.domain:
            existing = db.scalar(
                select(Company).where(
                    Company.workspace_id == p.workspace.id,
                    func.lower(Company.domain) == item.domain.lower(),
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
                event_type="company.updated",
                entity_type=EntityType.company,
                entity_id=existing.id,
                payload={"via": "bulk_upsert"},
                background=background,
            )
        else:
            c = Company(workspace_id=p.workspace.id, **item.model_dump())
            db.add(c)
            db.flush()
            created += 1
            ids.append(c.id)
            emit(
                db,
                p,
                event_type="company.created",
                entity_type=EntityType.company,
                entity_id=c.id,
                payload={"via": "bulk_upsert"},
                background=background,
            )
    db.commit()
    return BulkUpsertResult(created=created, updated=updated, ids=ids)
