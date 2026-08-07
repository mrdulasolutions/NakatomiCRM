"""Declarative workspace policies stored in ``workspace.data.policies``.

Shape::

    {
      "approvals": [{"action": "email.send", "required": true, "when": {"amount_gte": 50000}}],
      "required_fields": {
        "deal": {"stage:negotiation": ["amount", "primary_contact_id"]},
        "lead": {"status:qualified": ["email", "company_name"]}
      },
      "auto_tasks": [
        {"on": "lead.created", "title": "Qualify lead", "entity": "lead"}
      ],
      "block": [
        {"action": "deal.won", "when": {"missing": ["primary_contact_id"]}, "message": "…"}
      ]
    }
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.deps import Principal
from app.models import Task, TaskStatus, Workspace
from app.services.approvals import action_requires_approval


def get_policies(workspace: Workspace) -> dict[str, Any]:
    data = workspace.data or {}
    policies = data.get("policies") or {}
    return policies if isinstance(policies, dict) else {}


def set_policies(db: Session, workspace: Workspace, policies: dict[str, Any]) -> dict[str, Any]:
    data = dict(workspace.data or {})
    data["policies"] = policies
    workspace.data = data
    db.commit()
    db.refresh(workspace)
    return get_policies(workspace)


def evaluate_write(
    principal: Principal,
    *,
    entity_type: str,
    action: str,
    payload: dict,
    stage_slug: str | None = None,
    db: Session | None = None,
) -> None:
    """Raise 422 if a block policy or required_fields rule fails.

    Approval-required actions are *not* hard-blocked here — callers use
    action_requires_approval separately.
    """
    ws = principal.workspace
    if db is not None:
        fresh = db.get(Workspace, principal.workspace.id)
        if fresh:
            ws = fresh
    policies = get_policies(ws)
    # block rules
    for rule in policies.get("block") or []:
        if not isinstance(rule, dict):
            continue
        if rule.get("action") != action:
            continue
        when = rule.get("when") or {}
        if _when_matches(when, payload):
            raise HTTPException(
                status_code=422,
                detail=(
                    f"policy blocked: {rule.get('message') or action}; "
                    f"suggestion: {rule.get('suggestion') or 'adjust fields or ask an admin'}"
                ),
            )

    # required fields by entity + optional stage key
    required = (policies.get("required_fields") or {}).get(entity_type) or {}
    keys_to_check: list[str] = []
    if isinstance(required, dict):
        keys_to_check.extend(required.get("*") or required.get("always") or [])
        if stage_slug:
            keys_to_check.extend(required.get(f"stage:{stage_slug}") or [])
        # status-based for leads
        status = payload.get("status")
        if status:
            keys_to_check.extend(required.get(f"status:{status}") or [])
    elif isinstance(required, list):
        keys_to_check = list(required)

    missing = [f for f in keys_to_check if _is_missing(payload.get(f))]
    if missing:
        raise HTTPException(
            status_code=422,
            detail=(
                f"policy required_fields missing: {missing}; "
                f"suggestion: set {missing} before {action}"
            ),
        )


def _is_missing(v: Any) -> bool:
    return v is None or v == "" or v == []


def _when_matches(when: dict, payload: dict) -> bool:
    if not when:
        return True
    if "amount_gte" in when:
        try:
            if float(payload.get("amount") or 0) < float(when["amount_gte"]):
                return False
        except (TypeError, ValueError):
            return False
    if "missing" in when:
        fields = when["missing"] if isinstance(when["missing"], list) else [when["missing"]]
        if not any(_is_missing(payload.get(f)) for f in fields):
            return False
    if "field_eq" in when and isinstance(when["field_eq"], dict):
        for k, v in when["field_eq"].items():
            if payload.get(k) != v:
                return False
    return True


def apply_auto_tasks(
    db: Session,
    principal: Principal,
    *,
    event: str,
    entity_type: str | None,
    entity_id: str | None,
    title_fallback: str | None = None,
) -> list[str]:
    """Create CRM tasks from auto_tasks policy rules. Returns created task ids."""
    fresh = db.get(Workspace, principal.workspace.id)
    policies = get_policies(fresh or principal.workspace)
    created: list[str] = []
    for rule in policies.get("auto_tasks") or []:
        if not isinstance(rule, dict):
            continue
        if rule.get("on") != event:
            continue
        title = rule.get("title") or title_fallback or f"Follow up: {event}"
        from app.models import EntityType

        et = None
        if entity_type:
            try:
                et = EntityType(entity_type)
            except ValueError:
                et = None
        t = Task(
            workspace_id=principal.workspace.id,
            title=title,
            description=rule.get("description"),
            status=TaskStatus.open,
            entity_type=et,
            entity_id=entity_id,
            data={"via": "policy.auto_tasks", "event": event},
        )
        db.add(t)
        db.flush()
        created.append(t.id)
    return created


def needs_approval(principal: Principal, action: str, payload: dict) -> bool:
    return action_requires_approval(principal.workspace.data, action, payload)
