"""Audit search + entity time-travel."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import Principal, get_principal, require_scopes
from app.services.forensics import entity_as_of, search_audit

router = APIRouter(tags=["forensics"])


@router.get("/entities/{entity_type}/{entity_id}/as-of")
def as_of(
    entity_type: str,
    entity_id: str,
    ts: datetime = Query(..., description="ISO timestamp to reconstruct state as-of"),
    db: Session = Depends(get_db),
    p: Principal = Depends(require_scopes("timeline:read")),
):
    try:
        return entity_as_of(db, p.workspace.id, entity_type, entity_id, ts)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.get("/audit")
def audit_search(
    db: Session = Depends(get_db),
    p: Principal = Depends(require_scopes("timeline:read")),
    action: str | None = None,
    entity_type: str | None = None,
    entity_id: str | None = None,
    actor_user_id: str | None = None,
    actor_api_key_id: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int = Query(50, ge=1, le=500),
):
    return {
        "items": search_audit(
            db,
            p.workspace.id,
            actor_user_id=actor_user_id,
            actor_api_key_id=actor_api_key_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            since=since,
            until=until,
            limit=limit,
        )
    }
