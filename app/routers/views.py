"""Saved views / segments."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import Principal, enforce_resource_scope, get_principal, require_scopes
from app.models import SavedView
from app.schemas import SavedViewIn, SavedViewOut
from app.services.views import DEFAULT_VIEWS, run_view

router = APIRouter(
    prefix="/views",
    tags=["views"],
    dependencies=[Depends(enforce_resource_scope("views"))],
)


def _out(row: SavedView) -> SavedViewOut:
    return SavedViewOut(
        id=row.id,
        name=row.name,
        slug=row.slug,
        entity_type=row.entity_type,
        filters=row.filters or [],
        sort=row.sort or [],
        owner_user_id=row.owner_user_id,
        is_default=row.is_default,
        data=row.data or {},
        created_at=row.created_at,
    )


def ensure_default_views(db: Session, workspace_id: str) -> None:
    existing = {
        r.slug
        for r in db.scalars(select(SavedView).where(SavedView.workspace_id == workspace_id)).all()
    }
    for v in DEFAULT_VIEWS:
        if v["slug"] in existing:
            continue
        db.add(
            SavedView(
                workspace_id=workspace_id,
                name=v["name"],
                slug=v["slug"],
                entity_type=v["entity_type"],
                filters=v["filters"],
                sort=v["sort"],
                is_default=v.get("is_default", False),
            )
        )
    db.commit()


@router.get("", response_model=list[SavedViewOut])
def list_views(
    db: Session = Depends(get_db),
    p: Principal = Depends(get_principal),
    seed: bool = Query(True, description="ensure default views exist"),
):
    if seed:
        ensure_default_views(db, p.workspace.id)
    rows = db.scalars(
        select(SavedView)
        .where(SavedView.workspace_id == p.workspace.id, SavedView.deleted_at.is_(None))
        .order_by(SavedView.slug)
    ).all()
    return [_out(r) for r in rows]


@router.post("", response_model=SavedViewOut, status_code=201)
def create_view(
    payload: SavedViewIn,
    db: Session = Depends(get_db),
    p: Principal = Depends(get_principal),
) -> SavedViewOut:
    row = SavedView(
        workspace_id=p.workspace.id,
        name=payload.name,
        slug=payload.slug,
        entity_type=payload.entity_type,
        filters=payload.filters,
        sort=payload.sort,
        is_default=payload.is_default,
        owner_user_id=p.user_id,
        data=payload.data or {},
    )
    db.add(row)
    try:
        db.commit()
    except Exception as e:  # noqa: BLE001
        db.rollback()
        raise HTTPException(status_code=409, detail=f"conflict: {e.__class__.__name__}") from e
    db.refresh(row)
    return _out(row)


@router.get("/{view_ref}", response_model=SavedViewOut)
def get_view(view_ref: str, db: Session = Depends(get_db), p: Principal = Depends(get_principal)):
    ensure_default_views(db, p.workspace.id)
    row = _resolve(db, p.workspace.id, view_ref)
    return _out(row)


@router.post("/{view_ref}/run")
def run(
    view_ref: str,
    db: Session = Depends(get_db),
    p: Principal = Depends(get_principal),
    limit: int = Query(50, ge=1, le=500),
):
    ensure_default_views(db, p.workspace.id)
    row = _resolve(db, p.workspace.id, view_ref)
    try:
        items = run_view(
            db,
            p.workspace.id,
            entity_type=row.entity_type,
            filters=row.filters or [],
            sort=row.sort or [],
            limit=limit,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    # serialize simply
    out = []
    for obj in items:
        d = {c.name: getattr(obj, c.name) for c in obj.__table__.columns}
        for k, v in list(d.items()):
            if hasattr(v, "isoformat"):
                d[k] = v.isoformat()
            elif hasattr(v, "value"):
                d[k] = v.value
            elif v is not None and not isinstance(v, str | int | float | bool | list | dict):
                d[k] = str(v)
        out.append(d)
    return {
        "view": {"id": row.id, "slug": row.slug, "entity_type": row.entity_type},
        "count": len(out),
        "items": out,
    }


@router.delete("/{view_ref}")
def delete_view(view_ref: str, db: Session = Depends(get_db), p: Principal = Depends(get_principal)):
    row = _resolve(db, p.workspace.id, view_ref)
    if row.is_default:
        raise HTTPException(status_code=400, detail="cannot delete seeded default views; recreate after soft-delete")
    row.deleted_at = datetime.now(UTC)
    db.commit()
    return {"ok": True}


def _resolve(db: Session, workspace_id: str, view_ref: str) -> SavedView:
    import uuid as _uuid

    row = None
    try:
        _uuid.UUID(view_ref)
        row = db.get(SavedView, view_ref)
    except (ValueError, AttributeError):
        row = None
    if row and row.workspace_id == workspace_id and not row.deleted_at:
        return row
    row = db.scalar(
        select(SavedView).where(
            SavedView.workspace_id == workspace_id,
            SavedView.slug == view_ref,
            SavedView.deleted_at.is_(None),
        )
    )
    if not row:
        raise HTTPException(status_code=404, detail="view not found")
    return row
