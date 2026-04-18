from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import Principal, get_principal, require_role
from app.models import CustomFieldDefinition, EntityType, MemberRole
from app.schemas import (
    CustomFieldIn,
    CustomFieldOut,
    CustomFieldPatch,
    OkResponse,
)

router = APIRouter(prefix="/custom-fields", tags=["custom-fields"])


@router.get("", response_model=list[CustomFieldOut])
def list_fields(
    entity_type: EntityType | None = None,
    db: Session = Depends(get_db),
    p: Principal = Depends(get_principal),
) -> list[CustomFieldOut]:
    q = select(CustomFieldDefinition).where(CustomFieldDefinition.workspace_id == p.workspace.id)
    if entity_type:
        q = q.where(CustomFieldDefinition.entity_type == entity_type)
    q = q.order_by(CustomFieldDefinition.entity_type, CustomFieldDefinition.name)
    return [CustomFieldOut.model_validate(r) for r in db.scalars(q).all()]


@router.post("", response_model=CustomFieldOut, status_code=201)
def create_field(
    req: CustomFieldIn,
    db: Session = Depends(get_db),
    p: Principal = Depends(require_role(MemberRole.owner, MemberRole.admin)),
) -> CustomFieldOut:
    try:
        req._check()
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    cfd = CustomFieldDefinition(
        workspace_id=p.workspace.id,
        entity_type=req.entity_type,
        name=req.name,
        label=req.label,
        field_type=req.field_type,
        required=req.required,
        default_value=req.default_value or {},
        options=req.options,
        description=req.description,
    )
    db.add(cfd)
    try:
        db.flush()
    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail=f"a field named '{req.name}' already exists on {req.entity_type.value}",
        )
    db.commit()
    db.refresh(cfd)
    return CustomFieldOut.model_validate(cfd)


@router.patch("/{field_id}", response_model=CustomFieldOut)
def patch_field(
    field_id: str,
    req: CustomFieldPatch,
    db: Session = Depends(get_db),
    p: Principal = Depends(require_role(MemberRole.owner, MemberRole.admin)),
) -> CustomFieldOut:
    cfd = db.get(CustomFieldDefinition, field_id)
    if not cfd or cfd.workspace_id != p.workspace.id:
        raise HTTPException(status_code=404, detail="not found")
    updates = req.model_dump(exclude_unset=True)
    if "field_type" in updates and updates["field_type"] not in {
        "string",
        "text",
        "number",
        "bool",
        "date",
        "url",
        "email",
        "select",
    }:
        raise HTTPException(status_code=422, detail="invalid field_type")
    for k, v in updates.items():
        setattr(cfd, k, v if v is not None else getattr(cfd, k))
    db.commit()
    db.refresh(cfd)
    return CustomFieldOut.model_validate(cfd)


@router.delete("/{field_id}", response_model=OkResponse)
def delete_field(
    field_id: str,
    db: Session = Depends(get_db),
    p: Principal = Depends(require_role(MemberRole.owner, MemberRole.admin)),
) -> OkResponse:
    cfd = db.get(CustomFieldDefinition, field_id)
    if not cfd or cfd.workspace_id != p.workspace.id:
        raise HTTPException(status_code=404, detail="not found")
    db.delete(cfd)
    db.commit()
    return OkResponse(message="deleted")
