"""Product catalog and deal line items.

A workspace's product catalog is a flat list — no categories, no
hierarchy. Hierarchy belongs in tags or `data` so we don't impose a
shape that breaks for non-product workspaces (services, hours, etc.).

Line items snapshot ``name`` and ``unit_price`` at creation. A future
catalog price change does not retroactively rewrite historical deal
totals — that's a feature, not a bug. If you need to "refresh" a deal
to current prices, delete the line and re-add it.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import Pagination, Principal, get_pagination, get_principal, require_role
from app.models import Deal, DealLineItem, EntityType, MemberRole, Product
from app.schemas import (
    DealLineItemIn,
    DealLineItemOut,
    DealLineItemPatch,
    OkResponse,
    Page,
    ProductIn,
    ProductOut,
    ProductPatch,
)
from app.services.diffs import compute_changes
from app.services.events import emit
from app.services.pagination import apply_cursor, encode_cursor

router = APIRouter(tags=["products"])


# ---------------------------------------------------------------------------
# Products
# ---------------------------------------------------------------------------


@router.get("/products", response_model=Page[ProductOut])
def list_products(
    db: Session = Depends(get_db),
    p: Principal = Depends(get_principal),
    page: Pagination = Depends(get_pagination),
    q: str | None = Query(None, description="substring on name, sku, description"),
    sku: str | None = None,
    is_active: bool | None = None,
    tag: str | None = None,
    include_deleted: bool = False,
):
    query = select(Product).where(Product.workspace_id == p.workspace.id)
    if not include_deleted:
        query = query.where(Product.deleted_at.is_(None))
    if q:
        like = f"%{q.lower()}%"
        query = query.where(
            or_(
                func.lower(Product.name).like(like),
                func.lower(Product.sku).like(like),
                func.lower(Product.description).like(like),
            )
        )
    if sku:
        query = query.where(Product.sku == sku)
    if is_active is not None:
        query = query.where(Product.is_active.is_(is_active))
    if tag:
        query = query.where(Product.tags.contains([tag]))

    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    query = apply_cursor(query, model=Product, cursor=page.cursor)
    query = query.order_by(Product.created_at.desc(), Product.id.desc()).limit(page.limit + 1)

    rows = db.scalars(query).all()
    next_cursor = None
    if len(rows) > page.limit:
        last = rows[page.limit - 1]
        next_cursor = encode_cursor(last.created_at, last.id)
        rows = rows[: page.limit]
    return Page[ProductOut](
        items=[ProductOut.model_validate(r) for r in rows],
        next_cursor=next_cursor,
        count=total,
    )


@router.post("/products", response_model=ProductOut, status_code=201)
def create_product(
    payload: ProductIn,
    db: Session = Depends(get_db),
    p: Principal = Depends(require_role(MemberRole.owner, MemberRole.admin, MemberRole.member)),
) -> ProductOut:
    prod = Product(workspace_id=p.workspace.id, **payload.model_dump())
    db.add(prod)
    try:
        db.commit()
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=f"product conflict: {exc.__class__.__name__}") from exc
    db.refresh(prod)
    emit(db, p, event_type="product.created", entity_type=EntityType.product, entity_id=prod.id, payload={})
    return ProductOut.model_validate(prod)


@router.get("/products/{product_id}", response_model=ProductOut)
def get_product(product_id: str, db: Session = Depends(get_db), p: Principal = Depends(get_principal)) -> ProductOut:
    prod = db.get(Product, product_id)
    if not prod or prod.workspace_id != p.workspace.id:
        raise HTTPException(status_code=404, detail="not found")
    return ProductOut.model_validate(prod)


@router.patch("/products/{product_id}", response_model=ProductOut)
def patch_product(
    product_id: str,
    payload: ProductPatch,
    db: Session = Depends(get_db),
    p: Principal = Depends(require_role(MemberRole.owner, MemberRole.admin, MemberRole.member)),
) -> ProductOut:
    prod = db.get(Product, product_id)
    if not prod or prod.workspace_id != p.workspace.id:
        raise HTTPException(status_code=404, detail="not found")
    before = {c: getattr(prod, c) for c in ("name", "sku", "unit_price", "currency", "is_active")}
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(prod, k, v)
    db.commit()
    db.refresh(prod)
    after = {c: getattr(prod, c) for c in ("name", "sku", "unit_price", "currency", "is_active")}
    emit(
        db,
        p,
        event_type="product.updated",
        entity_type=EntityType.product,
        entity_id=prod.id,
        payload={"changes": compute_changes(before, after)},
    )
    return ProductOut.model_validate(prod)


@router.delete("/products/{product_id}", response_model=OkResponse)
def delete_product(
    product_id: str,
    db: Session = Depends(get_db),
    p: Principal = Depends(require_role(MemberRole.owner, MemberRole.admin)),
) -> OkResponse:
    prod = db.get(Product, product_id)
    if not prod or prod.workspace_id != p.workspace.id:
        raise HTTPException(status_code=404, detail="not found")
    prod.deleted_at = datetime.now(UTC)
    db.commit()
    emit(db, p, event_type="product.deleted", entity_type=EntityType.product, entity_id=prod.id, payload={})
    return OkResponse(message="deleted")


# ---------------------------------------------------------------------------
# Deal line items — nested under /deals/{deal_id}/line-items
# ---------------------------------------------------------------------------


def _resolve_deal(db: Session, deal_id: str, workspace_id: str) -> Deal:
    deal = db.get(Deal, deal_id)
    if not deal or deal.workspace_id != workspace_id or deal.deleted_at is not None:
        raise HTTPException(status_code=404, detail="deal not found")
    return deal


def _materialize_line(payload: DealLineItemIn, db: Session, workspace_id: str) -> dict:
    """Resolve a ``product_id`` reference by snapshotting catalog values into
    the line item. Caller-supplied ``name``/``unit_price`` always wins."""
    snapshot: dict = {
        "product_id": payload.product_id,
        "name": payload.name,
        "sku": payload.sku,
        "quantity": payload.quantity,
        "unit_price": payload.unit_price,
        "currency": payload.currency,
        "position": payload.position,
        "data": payload.data or {},
    }
    if payload.product_id:
        prod = db.get(Product, payload.product_id)
        if not prod or prod.workspace_id != workspace_id or prod.deleted_at is not None:
            raise HTTPException(status_code=404, detail="product not found")
        snapshot["name"] = snapshot["name"] or prod.name
        snapshot["sku"] = snapshot["sku"] or prod.sku
        if snapshot["unit_price"] is None:
            snapshot["unit_price"] = float(prod.unit_price or 0)
        if snapshot["currency"] is None:
            snapshot["currency"] = prod.currency
    if not snapshot["name"]:
        raise HTTPException(status_code=422, detail="name is required when product_id is omitted")
    if snapshot["unit_price"] is None:
        snapshot["unit_price"] = 0
    if snapshot["currency"] is None:
        snapshot["currency"] = "USD"
    return snapshot


@router.get("/deals/{deal_id}/line-items", response_model=list[DealLineItemOut])
def list_line_items(
    deal_id: str,
    db: Session = Depends(get_db),
    p: Principal = Depends(get_principal),
) -> list[DealLineItemOut]:
    _resolve_deal(db, deal_id, p.workspace.id)
    rows = db.scalars(
        select(DealLineItem)
        .where(DealLineItem.deal_id == deal_id)
        .order_by(DealLineItem.position.asc(), DealLineItem.created_at.asc())
    ).all()
    return [DealLineItemOut.model_validate(r) for r in rows]


@router.post("/deals/{deal_id}/line-items", response_model=DealLineItemOut, status_code=201)
def add_line_item(
    deal_id: str,
    payload: DealLineItemIn,
    db: Session = Depends(get_db),
    p: Principal = Depends(require_role(MemberRole.owner, MemberRole.admin, MemberRole.member)),
) -> DealLineItemOut:
    deal = _resolve_deal(db, deal_id, p.workspace.id)
    snapshot = _materialize_line(payload, db, p.workspace.id)
    line = DealLineItem(deal_id=deal.id, **snapshot)
    db.add(line)
    db.commit()
    db.refresh(line)
    emit(
        db,
        p,
        event_type="deal.line_item_added",
        entity_type=EntityType.deal,
        entity_id=deal.id,
        payload={"line_item_id": line.id, "name": line.name, "amount": float(line.unit_price) * float(line.quantity)},
    )
    return DealLineItemOut.model_validate(line)


@router.patch("/deals/{deal_id}/line-items/{line_id}", response_model=DealLineItemOut)
def patch_line_item(
    deal_id: str,
    line_id: str,
    payload: DealLineItemPatch,
    db: Session = Depends(get_db),
    p: Principal = Depends(require_role(MemberRole.owner, MemberRole.admin, MemberRole.member)),
) -> DealLineItemOut:
    deal = _resolve_deal(db, deal_id, p.workspace.id)
    line = db.get(DealLineItem, line_id)
    if not line or line.deal_id != deal.id:
        raise HTTPException(status_code=404, detail="line item not found")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(line, k, v)
    db.commit()
    db.refresh(line)
    return DealLineItemOut.model_validate(line)


@router.delete("/deals/{deal_id}/line-items/{line_id}", response_model=OkResponse)
def delete_line_item(
    deal_id: str,
    line_id: str,
    db: Session = Depends(get_db),
    p: Principal = Depends(require_role(MemberRole.owner, MemberRole.admin, MemberRole.member)),
) -> OkResponse:
    deal = _resolve_deal(db, deal_id, p.workspace.id)
    line = db.get(DealLineItem, line_id)
    if not line or line.deal_id != deal.id:
        raise HTTPException(status_code=404, detail="line item not found")
    db.delete(line)
    db.commit()
    emit(
        db,
        p,
        event_type="deal.line_item_removed",
        entity_type=EntityType.deal,
        entity_id=deal.id,
        payload={"line_item_id": line_id},
    )
    return OkResponse(message="deleted")
