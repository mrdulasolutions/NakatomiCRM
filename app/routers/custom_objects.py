"""Custom object types + records (moldable CRM model)."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import Principal, enforce_resource_scope, get_principal
from app.models import CustomObjectType, CustomRecord

router = APIRouter(
    prefix="/custom-objects",
    tags=["custom-objects"],
    dependencies=[Depends(enforce_resource_scope("custom_fields"))],  # reuse custom_fields scopes
)


class ObjectTypeIn(BaseModel):
    name: str
    slug: str = Field(pattern=r"^[a-z][a-z0-9_-]*$")
    description: str | None = None
    fields: list[dict] = Field(
        default_factory=list,
        description="[{name, label, type: string|number|bool|date|select|text, required?, options?}]",
    )
    data: dict = {}


class ObjectTypeOut(BaseModel):
    id: str
    name: str
    slug: str
    description: str | None
    fields: list
    data: dict
    created_at: datetime


class RecordIn(BaseModel):
    name: str | None = None
    external_id: str | None = None
    values: dict = {}
    related_entity_type: str | None = None
    related_entity_id: str | None = None
    tags: list[str] = []
    data: dict = {}


class RecordOut(BaseModel):
    id: str
    object_slug: str
    name: str | None
    external_id: str | None
    values: dict
    related_entity_type: str | None
    related_entity_id: str | None
    tags: list
    data: dict
    created_at: datetime
    updated_at: datetime


def _type_out(t: CustomObjectType) -> ObjectTypeOut:
    return ObjectTypeOut(
        id=t.id,
        name=t.name,
        slug=t.slug,
        description=t.description,
        fields=t.fields or [],
        data=t.data or {},
        created_at=t.created_at,
    )


def _rec_out(r: CustomRecord) -> RecordOut:
    return RecordOut(
        id=r.id,
        object_slug=r.object_slug,
        name=r.name,
        external_id=r.external_id,
        values=r.values or {},
        related_entity_type=r.related_entity_type,
        related_entity_id=r.related_entity_id,
        tags=r.tags or [],
        data=r.data or {},
        created_at=r.created_at,
        updated_at=r.updated_at,
    )


def _get_type(db: Session, workspace_id: str, slug: str) -> CustomObjectType:
    t = db.scalar(
        select(CustomObjectType).where(
            CustomObjectType.workspace_id == workspace_id,
            CustomObjectType.slug == slug,
            CustomObjectType.deleted_at.is_(None),
        )
    )
    if not t:
        raise HTTPException(status_code=404, detail=f"object type not found: {slug}")
    return t


@router.get("/types", response_model=list[ObjectTypeOut])
def list_types(db: Session = Depends(get_db), p: Principal = Depends(get_principal)):
    rows = db.scalars(
        select(CustomObjectType).where(
            CustomObjectType.workspace_id == p.workspace.id,
            CustomObjectType.deleted_at.is_(None),
        )
    ).all()
    return [_type_out(t) for t in rows]


@router.post("/types", response_model=ObjectTypeOut, status_code=201)
def create_type(
    payload: ObjectTypeIn,
    db: Session = Depends(get_db),
    p: Principal = Depends(get_principal),
):
    if not p.can("custom_fields:write") and "*" not in p.scopes:
        raise HTTPException(status_code=403, detail="missing custom_fields:write")
    row = CustomObjectType(
        workspace_id=p.workspace.id,
        name=payload.name,
        slug=payload.slug,
        description=payload.description,
        fields=payload.fields,
        data=payload.data or {},
    )
    db.add(row)
    try:
        db.commit()
    except Exception as e:  # noqa: BLE001
        db.rollback()
        raise HTTPException(status_code=409, detail=f"conflict: {e.__class__.__name__}") from e
    db.refresh(row)
    return _type_out(row)


@router.get("/types/{slug}", response_model=ObjectTypeOut)
def get_type(slug: str, db: Session = Depends(get_db), p: Principal = Depends(get_principal)):
    return _type_out(_get_type(db, p.workspace.id, slug))


@router.get("/types/{slug}/records", response_model=list[RecordOut])
def list_records(
    slug: str,
    db: Session = Depends(get_db),
    p: Principal = Depends(get_principal),
    q: str | None = None,
    limit: int = Query(50, ge=1, le=500),
):
    _get_type(db, p.workspace.id, slug)
    query = select(CustomRecord).where(
        CustomRecord.workspace_id == p.workspace.id,
        CustomRecord.object_slug == slug,
        CustomRecord.deleted_at.is_(None),
    )
    if q:
        like = f"%{q.lower()}%"
        query = query.where(
            or_(
                func.lower(CustomRecord.name).like(like),
                func.lower(CustomRecord.external_id).like(like),
            )
        )
    query = query.order_by(CustomRecord.created_at.desc()).limit(limit)
    return [_rec_out(r) for r in db.scalars(query).all()]


@router.post("/types/{slug}/records", response_model=RecordOut, status_code=201)
def create_record(
    slug: str,
    payload: RecordIn,
    db: Session = Depends(get_db),
    p: Principal = Depends(get_principal),
):
    t = _get_type(db, p.workspace.id, slug)
    if not p.can("custom_fields:write") and "*" not in p.scopes:
        raise HTTPException(status_code=403, detail="missing custom_fields:write")
    # soft validate required fields
    for fdef in t.fields or []:
        if fdef.get("required") and not (payload.values or {}).get(fdef.get("name")):
            if not payload.name or fdef.get("name") != "name":
                raise HTTPException(
                    status_code=422,
                    detail=f"required field missing: {fdef.get('name')}",
                )
    # upsert by external_id
    if payload.external_id:
        existing = db.scalar(
            select(CustomRecord).where(
                CustomRecord.workspace_id == p.workspace.id,
                CustomRecord.object_slug == slug,
                CustomRecord.external_id == payload.external_id,
            )
        )
        if existing:
            existing.name = payload.name or existing.name
            existing.values = payload.values or existing.values
            existing.related_entity_type = payload.related_entity_type
            existing.related_entity_id = payload.related_entity_id
            existing.tags = payload.tags or existing.tags
            if payload.data:
                existing.data = {**(existing.data or {}), **payload.data}
            db.commit()
            db.refresh(existing)
            return _rec_out(existing)
    row = CustomRecord(
        workspace_id=p.workspace.id,
        object_type_id=t.id,
        object_slug=slug,
        name=payload.name,
        external_id=payload.external_id,
        values=payload.values or {},
        related_entity_type=payload.related_entity_type,
        related_entity_id=payload.related_entity_id,
        tags=payload.tags or [],
        data=payload.data or {},
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _rec_out(row)


@router.get("/types/{slug}/records/{record_id}", response_model=RecordOut)
def get_record(
    slug: str,
    record_id: str,
    db: Session = Depends(get_db),
    p: Principal = Depends(get_principal),
):
    row = db.get(CustomRecord, record_id)
    if not row or row.workspace_id != p.workspace.id or row.object_slug != slug:
        raise HTTPException(status_code=404, detail="not found")
    return _rec_out(row)


@router.patch("/types/{slug}/records/{record_id}", response_model=RecordOut)
def patch_record(
    slug: str,
    record_id: str,
    payload: RecordIn,
    db: Session = Depends(get_db),
    p: Principal = Depends(get_principal),
):
    row = db.get(CustomRecord, record_id)
    if not row or row.workspace_id != p.workspace.id or row.object_slug != slug:
        raise HTTPException(status_code=404, detail="not found")
    data = payload.model_dump(exclude_unset=True)
    for k, v in data.items():
        if k == "values" and v is not None:
            row.values = {**(row.values or {}), **v}
        elif v is not None:
            setattr(row, k if k != "data" else "data", v if k != "data" else {**(row.data or {}), **v})
    db.commit()
    db.refresh(row)
    return _rec_out(row)


@router.delete("/types/{slug}/records/{record_id}")
def delete_record(
    slug: str,
    record_id: str,
    db: Session = Depends(get_db),
    p: Principal = Depends(get_principal),
):
    row = db.get(CustomRecord, record_id)
    if not row or row.workspace_id != p.workspace.id or row.object_slug != slug:
        raise HTTPException(status_code=404, detail="not found")
    row.deleted_at = datetime.now(UTC)
    db.commit()
    return {"ok": True}
