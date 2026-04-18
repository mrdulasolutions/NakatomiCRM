from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.deps import Principal, get_principal
from app.models import MemberRole, Membership, User, Workspace
from app.schemas import LoginRequest, SignupRequest, TokenResponse, UserOut
from app.security import create_access_token, hash_password, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/signup", response_model=TokenResponse)
def signup(req: SignupRequest, db: Session = Depends(get_db)) -> TokenResponse:
    if db.scalar(select(User).where(User.email == req.email.lower())):
        raise HTTPException(status_code=409, detail="email already registered")
    if db.scalar(select(Workspace).where(Workspace.slug == req.workspace_slug)):
        raise HTTPException(status_code=409, detail="workspace slug taken")

    user = User(
        email=req.email.lower(),
        password_hash=hash_password(req.password),
        display_name=req.display_name,
    )
    ws = Workspace(name=req.workspace_name, slug=req.workspace_slug)
    db.add(user)
    db.add(ws)
    db.flush()
    db.add(Membership(workspace_id=ws.id, user_id=user.id, role=MemberRole.owner))
    db.commit()
    db.refresh(user)
    db.refresh(ws)

    token = create_access_token(user.id, extra={"ws": ws.id})
    return TokenResponse(
        access_token=token,
        user_id=user.id,
        workspace_id=ws.id,
        workspace_slug=ws.slug,
        expires_in_seconds=settings.JWT_EXPIRE_MINUTES * 60,
    )


@router.post("/login", response_model=TokenResponse)
def login(req: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    user = db.scalar(select(User).where(User.email == req.email.lower()))
    if not user or not verify_password(req.password, user.password_hash) or not user.is_active:
        raise HTTPException(status_code=401, detail="invalid credentials")
    mem = db.scalar(select(Membership).where(Membership.user_id == user.id))
    if not mem:
        raise HTTPException(status_code=403, detail="user has no workspace")
    ws = db.get(Workspace, mem.workspace_id)
    if not ws:
        raise HTTPException(status_code=500, detail="membership references missing workspace")
    token = create_access_token(user.id, extra={"ws": ws.id})
    return TokenResponse(
        access_token=token,
        user_id=user.id,
        workspace_id=ws.id,
        workspace_slug=ws.slug,
        expires_in_seconds=settings.JWT_EXPIRE_MINUTES * 60,
    )


@router.get("/me", response_model=UserOut)
def me(p: Principal = Depends(get_principal)) -> UserOut:
    if not p.user:
        raise HTTPException(status_code=400, detail="this token does not resolve to a user")
    return UserOut.model_validate(p.user)
