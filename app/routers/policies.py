"""Workspace policy documents."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import Principal, get_principal, require_role_and_scopes
from app.models import MemberRole, Workspace
from app.services.policies import get_policies, set_policies

router = APIRouter(prefix="/policies", tags=["policies"])


class PoliciesBody(BaseModel):
    policies: dict = Field(
        default_factory=dict,
        description="Full policies document (approvals, required_fields, auto_tasks, block)",
    )


@router.get("")
def list_policies(p: Principal = Depends(get_principal)) -> dict:
    """Read workspace policies (any authenticated principal)."""
    return {
        "workspace_id": p.workspace.id,
        "policies": get_policies(p.workspace),
    }


@router.put("")
def put_policies(
    body: PoliciesBody,
    db: Session = Depends(get_db),
    p: Principal = Depends(
        require_role_and_scopes(MemberRole.owner, MemberRole.admin, scopes=("workspace:write",))
    ),
) -> dict:
    ws = db.get(Workspace, p.workspace.id)
    assert ws is not None
    policies = set_policies(db, ws, body.policies)
    # refresh principal workspace cache isn't automatic — next request reloads
    return {"workspace_id": ws.id, "policies": policies}
