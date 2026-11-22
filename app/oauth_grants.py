"""Workspace permissions and lifecycle for delegated MCP credentials."""

from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import ApiKey, MemberRole, Membership, User
from app.scopes import all_read_scopes, all_write_scopes, default_scopes_for_role, has_scope
from app.security import hash_api_key


def oauth_metadata(key: ApiKey) -> dict:
    value = (key.data or {}).get("oauth")
    return value if isinstance(value, dict) else {}


def oauth_scopes(scope: str, role: MemberRole) -> list[str]:
    allowed = set(all_read_scopes()) - {"workspace:read", "email:read"}
    if "mcp:write" in scope.split():
        allowed.update(set(all_write_scopes()) - {"workspace:write", "webhooks:write", "email:write"})
    role_scopes = default_scopes_for_role(role)
    return ["mcp", *sorted(item for item in allowed if has_scope(role_scopes, item))]


def active_membership(db: Session, key: ApiKey) -> Membership | None:
    if not key.user_id:
        return None
    return db.scalar(
        select(Membership)
        .join(User)
        .where(Membership.user_id == key.user_id, Membership.workspace_id == key.workspace_id, User.is_active)
    )


def bearer_key(
    db: Session, token: str, *, resource: str | None = None
) -> tuple[ApiKey, MemberRole, list | None] | None:
    key = db.scalar(select(ApiKey).where(ApiKey.key_hash == hash_api_key(token)))
    if not key or key.revoked_at or (key.expires_at and key.expires_at <= datetime.now(UTC)):
        return None
    grant = oauth_metadata(key)
    if not grant:
        return key, key.role, key.scopes
    if grant.get("kind") != "access" or not resource or resource != grant.get("resource"):
        return None
    membership = active_membership(db, key)
    if not membership:
        return None
    allowed = oauth_scopes(grant.get("scope", "mcp"), membership.role)
    return key, membership.role, [scope for scope in allowed if scope in (key.scopes or [])]


def locked_token(db: Session, token: str) -> ApiKey | None:
    digest = hash_api_key(token)
    key = db.scalar(select(ApiKey).where(ApiKey.key_hash == digest))
    if not key or not oauth_metadata(key):
        return None
    lock_grant(db, key)
    return db.scalar(
        select(ApiKey).where(ApiKey.id == key.id).with_for_update().execution_options(populate_existing=True)
    )


def lock_grant(db: Session, key: ApiKey) -> None:
    grant_id = oauth_metadata(key).get("grant_id") or key.id
    db.execute(select(func.pg_advisory_xact_lock(func.hashtextextended(grant_id, 0))))


def revoke_grant(db: Session, key: ApiKey) -> None:
    lock_grant(db, key)
    grant_id = oauth_metadata(key).get("grant_id")
    if grant_id:
        keys = db.scalars(
            select(ApiKey).where(
                ApiKey.workspace_id == key.workspace_id,
                ApiKey.data["oauth"]["grant_id"].astext == grant_id,
            )
        )
    else:
        keys = [key]
    now = datetime.now(UTC)
    for item in keys:
        item.revoked_at = item.revoked_at or now
