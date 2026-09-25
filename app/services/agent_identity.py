"""Agent Identity helpers — display names and external id maps on ApiKey rows."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ApiKey, User


def agent_display_name(key: ApiKey | None, user: User | None = None) -> str | None:
    """Human-readable actor label for timeline and workforce views."""
    if key is None and user is None:
        return None
    if key is not None:
        data = key.data or {}
        if isinstance(data.get("display_name"), str) and data["display_name"].strip():
            return data["display_name"].strip()
        if key.name and key.name.strip():
            return key.name.strip()
    if user is not None:
        if user.display_name and user.display_name.strip():
            return user.display_name.strip()
        if user.email:
            return user.email
    if key is not None:
        return key.prefix or key.id[:8]
    return None


def agent_profile_from_key(key: ApiKey) -> dict[str, Any]:
    """Serialize Agent Identity conventions (P5.3) for roster APIs."""
    data = key.data or {}
    return {
        "id": key.id,
        "name": key.name,
        "prefix": key.prefix,
        "display_name": agent_display_name(key),
        "role": data.get("agent_role"),
        "capabilities": data.get("capabilities"),
        "status": data.get("status", "active"),
        "scopes": key.scopes,
        "external_identities": data.get("external_identities") or {},
        "revoked": key.revoked_at is not None,
    }


def load_actor_labels(
    db: Session,
    workspace_id: str,
    api_key_ids: set[str],
    user_ids: set[str],
) -> tuple[dict[str, str], dict[str, str]]:
    """Batch-resolve actor_api_key_id and actor_user_id to display strings."""
    key_labels: dict[str, str] = {}
    user_labels: dict[str, str] = {}
    if api_key_ids:
        keys = db.scalars(
            select(ApiKey).where(
                ApiKey.workspace_id == workspace_id,
                ApiKey.id.in_(api_key_ids),
            )
        ).all()
        for k in keys:
            label = agent_display_name(k)
            if label:
                key_labels[k.id] = label
    if user_ids:
        users = db.scalars(select(User).where(User.id.in_(user_ids))).all()
        for u in users:
            label = agent_display_name(None, u)
            if label:
                user_labels[u.id] = label
    return key_labels, user_labels
