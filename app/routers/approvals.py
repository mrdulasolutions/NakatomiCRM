"""Human-in-the-loop approval requests."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import Principal, require_scopes
from app.models import ApprovalRequest, ApprovalStatus
from app.schemas import ApprovalCreate, ApprovalDecide, ApprovalOut
from app.services.approvals import create_approval, decide_approval

router = APIRouter(prefix="/approvals", tags=["approvals"])


def _out(row: ApprovalRequest) -> ApprovalOut:
    return ApprovalOut(
        id=row.id,
        action=row.action,
        payload=row.payload or {},
        status=row.status.value if hasattr(row.status, "value") else str(row.status),
        requested_by_user_id=row.requested_by_user_id,
        requested_by_api_key_id=row.requested_by_api_key_id,
        decided_by_user_id=row.decided_by_user_id,
        decided_by_api_key_id=row.decided_by_api_key_id,
        decided_at=row.decided_at,
        expires_at=row.expires_at,
        entity_type=row.entity_type,
        entity_id=row.entity_id,
        reason=row.reason,
        decision_note=row.decision_note,
        result=row.result or {},
        data=row.data or {},
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.get("", response_model=list[ApprovalOut])
def list_approvals(
    db: Session = Depends(get_db),
    p: Principal = Depends(require_scopes("approvals:read")),
    status_filter: str | None = Query(None, alias="status"),
    limit: int = Query(50, ge=1, le=200),
):
    q = select(ApprovalRequest).where(
        ApprovalRequest.workspace_id == p.workspace.id,
        ApprovalRequest.deleted_at.is_(None),
    )
    if status_filter:
        q = q.where(ApprovalRequest.status == status_filter)
    q = q.order_by(ApprovalRequest.created_at.desc()).limit(limit)
    rows = db.scalars(q).all()
    # lazy-expire pending past expires_at
    now = datetime.now(UTC)
    dirty = False
    for r in rows:
        if r.status == ApprovalStatus.pending and r.expires_at and r.expires_at < now:
            r.status = ApprovalStatus.expired
            dirty = True
    if dirty:
        db.commit()
    return [_out(r) for r in rows]


@router.post("", response_model=ApprovalOut, status_code=201)
def propose(
    payload: ApprovalCreate,
    db: Session = Depends(get_db),
    p: Principal = Depends(require_scopes("approvals:write")),
) -> ApprovalOut:
    if not payload.action or not payload.action.strip():
        raise HTTPException(status_code=422, detail="action is required")
    row = create_approval(
        db,
        p,
        action=payload.action.strip(),
        payload=payload.payload,
        entity_type=payload.entity_type,
        entity_id=payload.entity_id,
        reason=payload.reason,
        expires_at=payload.expires_at,
        data=payload.data,
    )
    return _out(row)


@router.get("/{approval_id}", response_model=ApprovalOut)
def get_one(
    approval_id: str,
    db: Session = Depends(get_db),
    p: Principal = Depends(require_scopes("approvals:read")),
) -> ApprovalOut:
    row = db.get(ApprovalRequest, approval_id)
    if not row or row.workspace_id != p.workspace.id or row.deleted_at:
        raise HTTPException(status_code=404, detail="not found")
    return _out(row)


@router.post("/{approval_id}/decide", response_model=ApprovalOut)
def decide(
    approval_id: str,
    payload: ApprovalDecide,
    db: Session = Depends(get_db),
    p: Principal = Depends(require_scopes("approvals:write")),
) -> ApprovalOut:
    # Deciding is a privileged act: require owner/admin role OR admin:keys scope
    # so a low-privilege agent cannot self-approve.
    from app.models import MemberRole
    from app.scopes import has_scope

    if p.role not in (MemberRole.owner, MemberRole.admin) and not has_scope(p.scopes, "admin:keys"):
        raise HTTPException(
            status_code=403,
            detail=(
                "deciding approvals requires owner/admin role or admin:keys scope; "
                "suggestion: have a human decide via JWT or an elevated API key"
            ),
        )
    row = db.get(ApprovalRequest, approval_id)
    if not row or row.workspace_id != p.workspace.id or row.deleted_at:
        raise HTTPException(status_code=404, detail="not found")
    if row.status != ApprovalStatus.pending:
        raise HTTPException(
            status_code=409,
            detail=f"approval is already {row.status.value}; only pending can be decided",
        )
    row = decide_approval(
        db,
        p,
        row,
        approve=payload.approve,
        note=payload.note,
        execute=payload.execute,
    )
    return _out(row)
