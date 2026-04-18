"""FastAPI dependencies: auth (user JWT or workspace API key), pagination, idempotency."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.models import (
    ApiKey,
    IdempotencyKey,
    MemberRole,
    Membership,
    User,
    Workspace,
)
from app.security import decode_access_token, hash_api_key


@dataclass
class Principal:
    """Who is making the request."""

    user: User | None
    api_key: ApiKey | None
    workspace: Workspace
    role: MemberRole

    @property
    def user_id(self) -> str | None:
        return self.user.id if self.user else None

    @property
    def api_key_id(self) -> str | None:
        return self.api_key.id if self.api_key else None


def _auth_error(msg: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=msg)


def _forbidden(msg: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=msg)


def _enforce_rate_limit(db: Session, key: ApiKey) -> None:
    """Fixed 60-second window per key. 429 when the window's count exceeds the limit.

    Per-key ``rate_limit_per_minute`` overrides the global default. Zero/None
    disables the limit. Uses a single atomic UPDATE so two concurrent requests
    can't both sneak under the cap.
    """
    limit = key.rate_limit_per_minute or settings.API_KEY_RATE_LIMIT_PER_MINUTE
    if not limit or limit <= 0:
        # Still bump last_used_at so operators can see activity.
        key.last_used_at = datetime.now(UTC)
        db.commit()
        return

    from sqlalchemy import text

    row = db.execute(
        text(
            """
            UPDATE api_keys
               SET usage_window_start = CASE
                     WHEN usage_window_start IS NULL
                          OR now() - usage_window_start >= interval '60 seconds'
                     THEN now()
                     ELSE usage_window_start END,
                   usage_count = CASE
                     WHEN usage_window_start IS NULL
                          OR now() - usage_window_start >= interval '60 seconds'
                     THEN 1
                     ELSE usage_count + 1 END,
                   last_used_at = now()
             WHERE id = :key_id
             RETURNING usage_count, usage_window_start
            """
        ),
        {"key_id": key.id},
    ).one()
    count, window_start = row
    db.commit()
    if count > limit:
        # Retry-After: seconds remaining in this window.
        remaining = 60 - int((datetime.now(UTC) - window_start).total_seconds())
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"rate limit exceeded ({limit}/min); try again shortly",
            headers={"Retry-After": str(max(1, remaining))},
        )


def _looks_like_uuid(v: str) -> bool:
    try:
        uuid.UUID(v)
        return True
    except (ValueError, AttributeError):
        return False


def _extract_bearer(authorization: str | None) -> str | None:
    if not authorization:
        return None
    parts = authorization.split()
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1]
    return None


def get_principal(
    request: Request,
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None),
    x_workspace: str | None = Header(default=None, alias="X-Workspace"),
) -> Principal:
    """Resolve the caller into a Principal.

    - API keys (``nk_...``) identify a workspace directly; X-Workspace is ignored.
    - User JWTs require X-Workspace header (slug or id) to pick a workspace.
    """
    token = _extract_bearer(authorization)
    if not token:
        raise _auth_error("missing bearer token")

    # API key path
    if token.startswith("nk_"):
        digest = hash_api_key(token)
        key = db.scalar(select(ApiKey).where(ApiKey.key_hash == digest))
        if not key or key.revoked_at is not None:
            raise _auth_error("invalid api key")
        if key.expires_at and key.expires_at < datetime.now(UTC):
            raise _auth_error("api key expired")
        _enforce_rate_limit(db, key)
        ws = db.get(Workspace, key.workspace_id)
        if not ws:
            raise _auth_error("workspace not found")
        user = db.get(User, key.user_id) if key.user_id else None
        return Principal(user=user, api_key=key, workspace=ws, role=key.role)

    # User JWT path
    payload = decode_access_token(token)
    if not payload or not payload.get("sub"):
        raise _auth_error("invalid token")
    user = db.get(User, payload["sub"])
    if not user or not user.is_active:
        raise _auth_error("user not found")
    workspace_ref = x_workspace or payload.get("ws")
    if not workspace_ref:
        raise _auth_error("X-Workspace header required when using user tokens")
    # Avoid `WHERE id = :ref OR slug = :ref`: Postgres rejects a non-UUID string
    # bound to a UUID column before it can fall through to the slug branch.
    if _looks_like_uuid(workspace_ref):
        ws = db.get(Workspace, workspace_ref)
    else:
        ws = db.scalar(select(Workspace).where(Workspace.slug == workspace_ref))
    if not ws:
        raise _auth_error("workspace not found")
    mem = db.scalar(select(Membership).where(Membership.workspace_id == ws.id, Membership.user_id == user.id))
    if not mem:
        raise _forbidden("not a member of this workspace")
    return Principal(user=user, api_key=None, workspace=ws, role=mem.role)


def require_role(*allowed: MemberRole):
    def _dep(p: Principal = Depends(get_principal)) -> Principal:
        if p.role not in allowed:
            raise _forbidden(f"requires one of: {[r.value for r in allowed]}")
        return p

    return _dep


# ---------- Pagination ----------
@dataclass
class Pagination:
    limit: int
    cursor: str | None  # base64 of (created_at_iso, id)


def get_pagination(
    limit: int = 50,
    cursor: str | None = None,
) -> Pagination:
    if limit < 1 or limit > 500:
        raise HTTPException(status_code=400, detail="limit must be 1..500")
    return Pagination(limit=limit, cursor=cursor)


# ---------- Idempotency ----------
def request_fingerprint(method: str, path: str, body: bytes) -> str:
    h = hashlib.sha256()
    h.update(method.encode())
    h.update(b"|")
    h.update(path.encode())
    h.update(b"|")
    h.update(body)
    return h.hexdigest()


def check_idempotency(
    db: Session, workspace_id: str, key: str, method: str, path: str, body_bytes: bytes
) -> IdempotencyKey | None:
    """Return stored record if key was already used — caller should replay its response."""
    fp = request_fingerprint(method, path, body_bytes)
    existing = db.scalar(
        select(IdempotencyKey).where(
            IdempotencyKey.workspace_id == workspace_id,
            IdempotencyKey.key == key,
        )
    )
    if not existing:
        return None
    if existing.request_hash != fp:
        raise HTTPException(
            status_code=409,
            detail="idempotency key reused with a different request body",
        )
    return existing


def save_idempotency(
    db: Session,
    workspace_id: str,
    key: str,
    method: str,
    path: str,
    body_bytes: bytes,
    status_code: int,
    response: dict,
) -> None:
    rec = IdempotencyKey(
        workspace_id=workspace_id,
        key=key,
        method=method,
        path=path,
        request_hash=request_fingerprint(method, path, body_bytes),
        status_code=status_code,
        response_body=response,
    )
    db.add(rec)
    db.commit()


def json_bytes(d: dict) -> bytes:
    return json.dumps(d, sort_keys=True, separators=(",", ":")).encode()
