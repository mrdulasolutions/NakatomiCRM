from __future__ import annotations

from datetime import UTC

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import Principal, get_principal, require_role
from app.models import ApiKey, MemberRole, Membership, User, Workspace
from app.schemas import (
    ApiKeyCreate,
    ApiKeyCreatedOut,
    ApiKeyOut,
    InviteRequest,
    MembershipOut,
    OkResponse,
    WorkspaceOut,
    WorkspaceUpdate,
)
from app.security import generate_api_key

router = APIRouter(prefix="/workspace", tags=["workspace"])


@router.get("", response_model=WorkspaceOut)
def get_current(p: Principal = Depends(get_principal)) -> WorkspaceOut:
    return WorkspaceOut.model_validate(p.workspace)


@router.patch("", response_model=WorkspaceOut)
def update_current(
    req: WorkspaceUpdate,
    db: Session = Depends(get_db),
    p: Principal = Depends(require_role(MemberRole.owner, MemberRole.admin)),
) -> WorkspaceOut:
    ws = db.get(Workspace, p.workspace.id)
    if not ws:
        raise HTTPException(status_code=404, detail="workspace vanished")
    if req.name is not None:
        ws.name = req.name
    if req.data is not None:
        ws.data = req.data
    db.commit()
    db.refresh(ws)
    return WorkspaceOut.model_validate(ws)


@router.get("/members", response_model=list[MembershipOut])
def list_members(db: Session = Depends(get_db), p: Principal = Depends(get_principal)):
    rows = db.scalars(select(Membership).where(Membership.workspace_id == p.workspace.id)).all()
    return [MembershipOut.model_validate(m) for m in rows]


@router.post("/members", response_model=MembershipOut, status_code=201)
def invite_member(
    req: InviteRequest,
    db: Session = Depends(get_db),
    p: Principal = Depends(require_role(MemberRole.owner, MemberRole.admin)),
) -> MembershipOut:
    user = db.scalar(select(User).where(User.email == req.email.lower()))
    if not user:
        raise HTTPException(status_code=404, detail="user not found (signup required first)")
    existing = db.scalar(
        select(Membership).where(Membership.workspace_id == p.workspace.id, Membership.user_id == user.id)
    )
    if existing:
        raise HTTPException(status_code=409, detail="already a member")
    m = Membership(workspace_id=p.workspace.id, user_id=user.id, role=req.role)
    db.add(m)
    db.commit()
    db.refresh(m)
    return MembershipOut.model_validate(m)


@router.delete("/members/{user_id}", response_model=OkResponse)
def remove_member(
    user_id: str,
    db: Session = Depends(get_db),
    p: Principal = Depends(require_role(MemberRole.owner, MemberRole.admin)),
) -> OkResponse:
    m = db.scalar(
        select(Membership).where(Membership.workspace_id == p.workspace.id, Membership.user_id == user_id)
    )
    if not m:
        raise HTTPException(status_code=404, detail="not a member")
    if m.role == MemberRole.owner and p.role != MemberRole.owner:
        raise HTTPException(status_code=403, detail="only an owner can remove another owner")
    db.delete(m)
    db.commit()
    return OkResponse()


# ---------- API keys ----------
@router.get("/api-keys", response_model=list[ApiKeyOut])
def list_keys(db: Session = Depends(get_db), p: Principal = Depends(get_principal)):
    rows = db.scalars(select(ApiKey).where(ApiKey.workspace_id == p.workspace.id)).all()
    return [ApiKeyOut.model_validate(k) for k in rows]


@router.post("/api-keys", response_model=ApiKeyCreatedOut, status_code=201)
def create_key(
    req: ApiKeyCreate,
    db: Session = Depends(get_db),
    p: Principal = Depends(require_role(MemberRole.owner, MemberRole.admin)),
) -> ApiKeyCreatedOut:
    full, prefix, digest = generate_api_key()
    key = ApiKey(
        workspace_id=p.workspace.id,
        user_id=req.user_id,
        name=req.name,
        prefix=prefix,
        key_hash=digest,
        role=req.role,
        expires_at=req.expires_at,
        rate_limit_per_minute=req.rate_limit_per_minute,
    )
    db.add(key)
    db.commit()
    db.refresh(key)
    # ApiKeyCreatedOut extends ApiKeyOut; the SA row has no ``key`` attr, so
    # build the base and splice the plaintext key in once.
    base = ApiKeyOut.model_validate(key).model_dump()
    return ApiKeyCreatedOut(**base, key=full)


@router.delete("/api-keys/{key_id}", response_model=OkResponse)
def revoke_key(
    key_id: str,
    db: Session = Depends(get_db),
    p: Principal = Depends(require_role(MemberRole.owner, MemberRole.admin)),
) -> OkResponse:
    from datetime import datetime

    key = db.get(ApiKey, key_id)
    if not key or key.workspace_id != p.workspace.id:
        raise HTTPException(status_code=404, detail="not found")
    key.revoked_at = datetime.now(UTC)
    db.commit()
    return OkResponse(message="revoked")
