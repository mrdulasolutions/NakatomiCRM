from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import Pagination, Principal, get_pagination, get_principal, enforce_resource_scope
from app.models import Deal, DealParticipant, DealParticipantRole, DealStatus, EntityType, Pipeline, Stage
from app.schemas import (
    DealIn,
    DealOut,
    DealParticipantIn,
    DealParticipantOut,
    DealPatch,
    OkResponse,
    Page,
)
from app.services.diffs import compute_changes
from app.services.events import emit
from app.services.pagination import apply_cursor, encode_cursor

router = APIRouter(prefix="/deals", tags=["deals"],
    dependencies=[Depends(enforce_resource_scope("deals"))],
)


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
    # Workspace policy (required fields / block rules)
    from app.services.policies import evaluate_write

    stage_slug = None
    if "stage_id" in updates and updates["stage_id"]:
        st = db.get(Stage, updates["stage_id"])
        stage_slug = st.slug if st else None
    check = {
        "amount": updates.get("amount", d.amount),
        "primary_contact_id": updates.get("primary_contact_id", d.primary_contact_id),
        "status": updates.get("status", d.status),
        "stage_id": updates.get("stage_id", d.stage_id),
    }
    if hasattr(check["status"], "value"):
        check["status"] = check["status"].value
    action = "deal.won" if check["status"] == "won" else "deal.updated"
    evaluate_write(p, entity_type="deal", action=action, payload=check, stage_slug=stage_slug)
    for k, v in updates.items():
        setattr(d, k, v)
    if "status" in updates and updates["status"] in (DealStatus.won, DealStatus.lost):
        d.closed_at = datetime.now(UTC)
    # Capture per-field before/after *before* commit — SA's history only has
    # the old values while the session is still dirty.
    changes = compute_changes(d, list(updates.keys()))
    emit(
        db,
        p,
        event_type="deal.updated",
        entity_type=EntityType.deal,
        entity_id=d.id,
        payload={"changes": changes},
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


@router.get("/{deal_id}/participants", response_model=list[DealParticipantOut])
def list_participants(
    deal_id: str,
    db: Session = Depends(get_db),
    p: Principal = Depends(get_principal),
):
    d = db.get(Deal, deal_id)
    if not d or d.workspace_id != p.workspace.id:
        raise HTTPException(status_code=404, detail="not found")
    rows = db.scalars(
        select(DealParticipant).where(
            DealParticipant.deal_id == deal_id,
            DealParticipant.deleted_at.is_(None),
        )
    ).all()
    return [
        DealParticipantOut(
            id=r.id,
            deal_id=r.deal_id,
            contact_id=r.contact_id,
            role=r.role.value if hasattr(r.role, "value") else str(r.role),
            is_primary=r.is_primary,
            data=r.data or {},
            created_at=r.created_at,
        )
        for r in rows
    ]


@router.post("/{deal_id}/participants", response_model=DealParticipantOut, status_code=201)
def add_participant(
    deal_id: str,
    payload: DealParticipantIn,
    db: Session = Depends(get_db),
    p: Principal = Depends(get_principal),
) -> DealParticipantOut:
    d = db.get(Deal, deal_id)
    if not d or d.workspace_id != p.workspace.id:
        raise HTTPException(status_code=404, detail="not found")
    try:
        role = DealParticipantRole(payload.role)
    except ValueError as e:
        raise HTTPException(
            status_code=422,
            detail=f"invalid role: {payload.role}; use champion|economic_buyer|legal|user|influencer|other",
        ) from e
    if payload.is_primary:
        d.primary_contact_id = payload.contact_id
    row = DealParticipant(
        workspace_id=p.workspace.id,
        deal_id=deal_id,
        contact_id=payload.contact_id,
        role=role,
        is_primary=payload.is_primary,
        data=payload.data or {},
    )
    db.add(row)
    try:
        db.commit()
    except Exception as e:  # noqa: BLE001
        db.rollback()
        raise HTTPException(status_code=409, detail=f"conflict: {e.__class__.__name__}") from e
    db.refresh(row)
    return DealParticipantOut(
        id=row.id,
        deal_id=row.deal_id,
        contact_id=row.contact_id,
        role=row.role.value,
        is_primary=row.is_primary,
        data=row.data or {},
        created_at=row.created_at,
    )


@router.delete("/{deal_id}/participants/{participant_id}", response_model=OkResponse)
def remove_participant(
    deal_id: str,
    participant_id: str,
    db: Session = Depends(get_db),
    p: Principal = Depends(get_principal),
) -> OkResponse:
    row = db.get(DealParticipant, participant_id)
    if not row or row.deal_id != deal_id or row.workspace_id != p.workspace.id:
        raise HTTPException(status_code=404, detail="not found")
    row.deleted_at = datetime.now(UTC)
    db.commit()
    return OkResponse(message="deleted")
