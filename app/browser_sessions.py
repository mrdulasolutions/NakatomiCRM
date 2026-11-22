"""Server-side browser login sessions. Only a random session identifier leaves the server."""

import secrets
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import BrowserSession, Membership, User
from app.security import hash_api_key

COOKIE = "nk_browser_session"


def public_origin(request: Request) -> str:
    return settings.public_origin or str(request.base_url).rstrip("/")


def require_same_origin(request: Request) -> None:
    if request.headers.get("origin") != public_origin(request):
        raise HTTPException(403, "Same-origin request required")


def session_row(request: Request, db: Session) -> BrowserSession | None:
    token = request.cookies.get(COOKIE)
    row = db.get(BrowserSession, hash_api_key(token)) if token else None
    return row if row and row.expires_at > datetime.now(UTC) else None


def browser_principal(request: Request, db: Session):
    from app.deps import Principal
    from app.models import Workspace
    from app.scopes import default_scopes_for_role

    row = session_row(request, db)
    if not row:
        return None
    user = db.get(User, row.user_id)
    membership = db.scalar(
        select(Membership).where(
            Membership.workspace_id == row.workspace_id, Membership.user_id == row.user_id
        )
    )
    workspace = db.get(Workspace, row.workspace_id)
    if not user or not user.is_active or not membership or not workspace:
        return None
    return Principal(user, None, workspace, membership.role, default_scopes_for_role(membership.role))


def set_session(request: Request, response: Response, db: Session, user_id: str, workspace_id: str) -> None:
    clear_session(request, response, db)
    token = secrets.token_urlsafe(32)
    ttl = timedelta(minutes=settings.JWT_EXPIRE_MINUTES)
    db.add(
        BrowserSession(
            digest=hash_api_key(token),
            user_id=user_id,
            workspace_id=workspace_id,
            expires_at=datetime.now(UTC) + ttl,
        )
    )
    db.commit()
    response.set_cookie(
        COOKIE,
        token,
        max_age=int(ttl.total_seconds()),
        httponly=True,
        secure=public_origin(request).startswith("https://"),
        samesite="lax",
    )
    response.headers["Cache-Control"] = "no-store"


def clear_session(request: Request, response: Response, db: Session) -> None:
    row = session_row(request, db)
    if row:
        db.delete(row)
        db.commit()
    response.delete_cookie(
        COOKIE, httponly=True, samesite="lax", secure=public_origin(request).startswith("https://")
    )
    response.headers["Cache-Control"] = "no-store"
