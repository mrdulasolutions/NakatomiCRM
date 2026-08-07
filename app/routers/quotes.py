"""Versioned quotes on deals."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import Principal, enforce_resource_scope, get_principal
from app.models import Deal, EntityType, Product, Quote, QuoteLineItem, QuoteStatus
from app.schemas import QuoteIn, QuoteLineIn, QuoteLineOut, QuoteOut, QuoteStatusPatch
from app.services.events import emit

router = APIRouter(
    prefix="/quotes",
    tags=["quotes"],
    dependencies=[Depends(enforce_resource_scope("quotes"))],
)


def _recalc(db: Session, quote: Quote) -> None:
    lines = db.scalars(select(QuoteLineItem).where(QuoteLineItem.quote_id == quote.id)).all()
    sub = sum(float(li.quantity or 0) * float(li.unit_price or 0) for li in lines)
    quote.subtotal = sub
    quote.total = sub


def _line_out(li: QuoteLineItem) -> QuoteLineOut:
    return QuoteLineOut(
        id=li.id,
        quote_id=li.quote_id,
        product_id=li.product_id,
        name=li.name,
        sku=li.sku,
        quantity=float(li.quantity),
        unit_price=float(li.unit_price),
        currency=li.currency,
        position=li.position,
        data=li.data or {},
    )


def _out(db: Session, row: Quote, with_lines: bool = True) -> QuoteOut:
    lines = []
    if with_lines:
        lis = db.scalars(
            select(QuoteLineItem).where(QuoteLineItem.quote_id == row.id).order_by(QuoteLineItem.position)
        ).all()
        lines = [_line_out(li) for li in lis]
    return QuoteOut(
        id=row.id,
        deal_id=row.deal_id,
        external_id=row.external_id,
        name=row.name,
        version=row.version,
        status=row.status.value if hasattr(row.status, "value") else str(row.status),
        currency=row.currency,
        subtotal=float(row.subtotal or 0),
        total=float(row.total or 0),
        valid_until=row.valid_until,
        sent_at=row.sent_at,
        accepted_at=row.accepted_at,
        file_id=row.file_id,
        notes=row.notes,
        data=row.data or {},
        created_at=row.created_at,
        updated_at=row.updated_at,
        lines=lines,
    )


def _materialize_line(db: Session, workspace_id: str, line: QuoteLineIn) -> dict:
    name = line.name
    unit_price = line.unit_price
    sku = line.sku
    if line.product_id:
        prod = db.get(Product, line.product_id)
        if not prod or prod.workspace_id != workspace_id:
            raise HTTPException(status_code=404, detail=f"product not found: {line.product_id}")
        name = name or prod.name
        unit_price = unit_price if unit_price is not None else float(prod.unit_price or 0)
        sku = sku or prod.sku
    if not name:
        raise HTTPException(status_code=422, detail="name is required when no product_id")
    if unit_price is None:
        unit_price = 0
    return {
        "product_id": line.product_id,
        "name": name,
        "sku": sku,
        "quantity": line.quantity,
        "unit_price": unit_price,
        "currency": line.currency,
        "position": line.position,
        "data": line.data or {},
    }


@router.get("")
def list_quotes(
    db: Session = Depends(get_db),
    p: Principal = Depends(get_principal),
    deal_id: str | None = None,
    status: str | None = None,
    limit: int = Query(50, ge=1, le=200),
) -> list[QuoteOut]:
    q = select(Quote).where(Quote.workspace_id == p.workspace.id, Quote.deleted_at.is_(None))
    if deal_id:
        q = q.where(Quote.deal_id == deal_id)
    if status:
        q = q.where(Quote.status == status)
    q = q.order_by(Quote.created_at.desc()).limit(limit)
    return [_out(db, r) for r in db.scalars(q).all()]


@router.post("", response_model=QuoteOut, status_code=201)
def create_quote(
    payload: QuoteIn,
    db: Session = Depends(get_db),
    p: Principal = Depends(get_principal),
) -> QuoteOut:
    deal = db.get(Deal, payload.deal_id)
    if not deal or deal.workspace_id != p.workspace.id:
        raise HTTPException(status_code=404, detail="deal not found")
    # next version for this deal
    max_v = db.scalar(
        select(func.coalesce(func.max(Quote.version), 0)).where(
            Quote.deal_id == deal.id, Quote.deleted_at.is_(None)
        )
    )
    row = Quote(
        workspace_id=p.workspace.id,
        deal_id=deal.id,
        name=payload.name,
        version=int(max_v or 0) + 1,
        currency=payload.currency,
        valid_until=payload.valid_until,
        notes=payload.notes,
        external_id=payload.external_id,
        data=payload.data or {},
    )
    db.add(row)
    db.flush()
    for line in payload.lines:
        fields = _materialize_line(db, p.workspace.id, line)
        db.add(QuoteLineItem(quote_id=row.id, **fields))
    db.flush()
    _recalc(db, row)
    emit(
        db,
        p,
        event_type="quote.created",
        entity_type=EntityType.quote,
        entity_id=row.id,
        payload={"quote_id": row.id, "deal_id": deal.id, "version": row.version},
    )
    db.commit()
    db.refresh(row)
    return _out(db, row)


@router.get("/{quote_id}", response_model=QuoteOut)
def get_quote(quote_id: str, db: Session = Depends(get_db), p: Principal = Depends(get_principal)):
    row = db.get(Quote, quote_id)
    if not row or row.workspace_id != p.workspace.id:
        raise HTTPException(status_code=404, detail="not found")
    return _out(db, row)


@router.post("/{quote_id}/status", response_model=QuoteOut)
def set_status(
    quote_id: str,
    payload: QuoteStatusPatch,
    db: Session = Depends(get_db),
    p: Principal = Depends(get_principal),
) -> QuoteOut:
    row = db.get(Quote, quote_id)
    if not row or row.workspace_id != p.workspace.id:
        raise HTTPException(status_code=404, detail="not found")
    try:
        st = QuoteStatus(payload.status)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=f"invalid status: {payload.status}") from e
    row.status = st
    now = datetime.now(UTC)
    if st == QuoteStatus.sent:
        row.sent_at = now
    if st == QuoteStatus.accepted:
        row.accepted_at = now
        if payload.sync_deal_amount:
            deal = db.get(Deal, row.deal_id)
            if deal:
                deal.amount = row.total
                deal.currency = row.currency
    emit(
        db,
        p,
        event_type="quote.status_changed",
        entity_type=EntityType.quote,
        entity_id=row.id,
        payload={"status": st.value, "deal_id": row.deal_id},
    )
    db.commit()
    db.refresh(row)
    return _out(db, row)


@router.post("/{quote_id}/lines", response_model=QuoteLineOut, status_code=201)
def add_line(
    quote_id: str,
    payload: QuoteLineIn,
    db: Session = Depends(get_db),
    p: Principal = Depends(get_principal),
) -> QuoteLineOut:
    row = db.get(Quote, quote_id)
    if not row or row.workspace_id != p.workspace.id:
        raise HTTPException(status_code=404, detail="not found")
    if row.status not in (QuoteStatus.draft,):
        raise HTTPException(status_code=409, detail="only draft quotes accept new lines")
    fields = _materialize_line(db, p.workspace.id, payload)
    li = QuoteLineItem(quote_id=row.id, **fields)
    db.add(li)
    db.flush()
    _recalc(db, row)
    db.commit()
    db.refresh(li)
    return _line_out(li)
