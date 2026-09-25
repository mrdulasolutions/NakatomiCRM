"""P5 Agent OS compounds — REST parity for entity_context, agent_activity, handoffs."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import Principal, require_scopes
from app.services.agent_activity import build_agent_activity, list_workspace_agents
from app.services.entity_context import build_entity_context
from app.services.explain_change import explain_change

router = APIRouter(prefix="/agent", tags=["agent-os"])


@router.get("/entity-context")
def get_entity_context(
    entity_type: str = Query(..., description="company | contact | deal | lead"),
    entity_ref: str = Query(..., description="UUID or human ref (name, domain, email)"),
    timeline_limit: int = Query(40, ge=1, le=100),
    db: Session = Depends(get_db),
    p: Principal = Depends(require_scopes("timeline:read")),
):
    """Coherent business-state bundle for one entity (P5.1)."""
    try:
        return build_entity_context(
            db,
            p.workspace.id,
            entity_type,
            entity_ref,
            scopes=p.scopes,
            timeline_limit=timeline_limit,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.get("/activity")
def get_agent_activity(
    since: datetime = Query(..., description="ISO timestamp — aggregate timeline since then"),
    until: datetime | None = None,
    agent_api_key_id: str | None = None,
    entity_type: str | None = None,
    event_type_prefix: str | None = None,
    db: Session = Depends(get_db),
    p: Principal = Depends(require_scopes("timeline:read")),
):
    """Structured workforce facts from timeline (P5.6) — not orchestration analytics."""
    try:
        return build_agent_activity(
            db,
            p.workspace.id,
            since=since,
            until=until,
            agent_api_key_id=agent_api_key_id,
            entity_type=entity_type,
            event_type_prefix=event_type_prefix,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/agents")
def get_agents(
    db: Session = Depends(get_db),
    p: Principal = Depends(require_scopes("workspace:read")),
):
    """Workspace agent roster from API keys (P5.3)."""
    return {"agents": list_workspace_agents(db, p.workspace.id)}


@router.get("/explain-change")
def get_explain_change(
    entity_type: str,
    entity_id: str,
    event_id: int | None = None,
    since: datetime | None = None,
    limit: int = Query(20, ge=1, le=50),
    db: Session = Depends(get_db),
    p: Principal = Depends(require_scopes("timeline:read")),
):
    """Evidence chain for entity changes (P5.5)."""
    try:
        return explain_change(
            db,
            p.workspace.id,
            entity_type,
            entity_id,
            event_id=event_id,
            since=since,
            limit=limit,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


class HandoffIn(BaseModel):
    """P5.4 — machine-readable handoff payload (store in A2A task input or task.data)."""

    entity_type: str
    entity_ref: str
    from_agent_api_key_id: str | None = None
    to_agent_api_key_id: str | None = None
    summary: str = Field(..., max_length=4000)
    next_steps: list[str] = Field(default_factory=list)


@router.post("/handoff")
def post_handoff(
    body: HandoffIn,
    db: Session = Depends(get_db),
    p: Principal = Depends(require_scopes("a2a:invoke", "timeline:read")),
):
    """Validate handoff + return entity_context snapshot for the receiving agent."""
    try:
        ctx = build_entity_context(db, p.workspace.id, body.entity_type, body.entity_ref, scopes=p.scopes)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return {
        "protocol": "nakatomi.handoff/v1",
        "handoff": body.model_dump(),
        "entity_context": ctx,
        "suggestion": "Receiver should call entity_context at session start; optional A2A task carries this payload.",
    }
