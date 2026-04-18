from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import Pagination, Principal, get_pagination, get_principal
from app.models import Deal, DealStatus, EntityType, Pipeline, Stage
from app.schemas import DealIn, DealOut, DealPatch, OkResponse, Page
from app.services.events import emit
from app.services.pagination import apply_cursor, encode_cursor

router = APIRouter(prefix="/deals", tags=["deals"])


def _default_pipeline(db: Session, workspace_id: str) -> Pipeline | None:
    return db.scalar(
        select(Pipeline)
        .where(Pipeline.workspace_id == workspace_id)
        .order_by(Pipeline.is_default.desc(), Pipeline.created_at.asc())
        .limit(1)
    )


@router.get("", response_model=Page[DealOut])
def list_deals(
    db: Session = Depends(get_db),
    p: Principal = Depends(get_principal),
    page: Pagination = Depends(get_pagination),
    q: str | None = Query(None),
    status: DealStatus | None = None,
    pipeline_id: str | None = None,
    stage_id: str | None = None,
    company_id: str | None = None,
    owner_user_id: str | None = None,
    include_deleted: bool = False,
):
    query = select(Deal).where(Deal.workspace_id == p.workspace.id)
    if not include_deleted:
        query = query.where(Deal.deleted_at.is_(None))
    if q:
        like = f"%{q.lower()}%"
        query = query.where(func.lower(Deal.name).like(like))
    if status:
        query = query.where(Deal.status == status)
    if pipeline_id:
        query = query.where(Deal.pipeline_id == pipeline_id)
    if stage_id:
        query = query.where(Deal.stage_id == stage_id)
    if company_id:
        query = query.where(Deal.company_id == company_id)
    if owner_user_id:
        query = query.where(Deal.owner_user_id == owner_user_id)

    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    query = apply_cursor(query, model=Deal, cursor=page.cursor)
    query = query.order_by(Deal.created_at.desc(), Deal.id.desc()).limit(page.limit + 1)

    rows = db.scalars(query).all()
    next_cursor = None
    if len(rows) > page.limit:
        last = rows[page.limit - 1]
        next_cursor = encode_cursor(last.created_at, last.id)
        rows = rows[: page.limit]
    return Page[DealOut](
        items=[DealOut.model_validate(r) for r in rows],
        next_cursor=next_cursor,
        count=total,
    )


@router.post("", response_model=DealOut, status_code=201)
def create_deal(
    payload: DealIn,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    p: Principal = Depends(get_principal),
) -> DealOut:
    pipeline_id = payload.pipeline_id
    stage_id = payload.stage_id
    if not pipeline_id:
        pipe = _default_pipeline(db, p.workspace.id)
        if not pipe:
            raise HTTPException(
                status_code=400,
                detail="no pipelines configured; create one via POST /pipelines first",
            )
        pipeline_id = pipe.id
    if not stage_id:
        stage = db.scalar(
            select(Stage).where(Stage.pipeline_id == pipeline_id).order_by(Stage.position).limit(1)
        )
        if not stage:
            raise HTTPException(status_code=400, detail="pipeline has no stages")
        stage_id = stage.id

    body = payload.model_dump()
    body["pipeline_id"] = pipeline_id
    body["stage_id"] = stage_id
    d = Deal(workspace_id=p.workspace.id, **body)
    db.add(d)
    try:
        db.flush()
    except Exception as e:  # noqa: BLE001
        db.rollback()
        raise HTTPException(status_code=409, detail=f"conflict: {e.__class__.__name__}")
    emit(
        db,
        p,
        event_type="deal.created",
        entity_type=EntityType.deal,
        entity_id=d.id,
        payload={"deal_id": d.id, "stage_id": stage_id},
        background=background,
    )
    db.commit()
    db.refresh(d)
    return DealOut.model_validate(d)


@router.get("/{deal_id}", response_model=DealOut)
def get_deal(deal_id: str, db: Session = Depends(get_db), p: Principal = Depends(get_principal)):
    d = db.get(Deal, deal_id)
    if not d or d.workspace_id != p.workspace.id:
        raise HTTPException(status_code=404, detail="not found")
    return DealOut.model_validate(d)


@router.patch("/{deal_id}", response_model=DealOut)
def patch_deal(
    deal_id: str,
    payload: DealPatch,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    p: Principal = Depends(get_principal),
) -> DealOut:
    d = db.get(Deal, deal_id)
    if not d or d.workspace_id != p.workspace.id:
        raise HTTPException(status_code=404, detail="not found")
    updates = payload.model_dump(exclude_unset=True)
    old_stage = d.stage_id
    old_status = d.status
    for k, v in updates.items():
        setattr(d, k, v)
    if "status" in updates and updates["status"] in (DealStatus.won, DealStatus.lost):
        d.closed_at = datetime.now(UTC)
    emit(
        db,
        p,
        event_type="deal.updated",
        entity_type=EntityType.deal,
        entity_id=d.id,
        payload={"changes": list(updates.keys())},
        background=background,
    )
    if "stage_id" in updates and updates["stage_id"] != old_stage:
        emit(
            db,
            p,
            event_type="deal.stage_changed",
            entity_type=EntityType.deal,
            entity_id=d.id,
            payload={"from_stage_id": old_stage, "to_stage_id": d.stage_id},
            background=background,
        )
    if "status" in updates and updates["status"] != old_status:
        new_status = updates["status"]
        status_name = new_status.value if hasattr(new_status, "value") else str(new_status)
        emit(
            db,
            p,
            event_type=f"deal.{status_name}",
            entity_type=EntityType.deal,
            entity_id=d.id,
            payload={"amount": float(d.amount) if d.amount else None},
            background=background,
        )
    db.commit()
    db.refresh(d)
    return DealOut.model_validate(d)


@router.delete("/{deal_id}", response_model=OkResponse)
def delete_deal(
    deal_id: str,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    p: Principal = Depends(get_principal),
    hard: bool = False,
) -> OkResponse:
    d = db.get(Deal, deal_id)
    if not d or d.workspace_id != p.workspace.id:
        raise HTTPException(status_code=404, detail="not found")
    if hard:
        db.delete(d)
    else:
        d.deleted_at = datetime.now(UTC)
    emit(
        db,
        p,
        event_type="deal.deleted",
        entity_type=EntityType.deal,
        entity_id=d.id,
        payload={"hard": hard},
        background=background,
    )
    db.commit()
    return OkResponse(message="deleted")
