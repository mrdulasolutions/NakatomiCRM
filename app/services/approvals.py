"""HITL approval helpers — policy lookup and optional auto-execute."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.deps import Principal
from app.models import (
    Activity,
    ApprovalRequest,
    ApprovalStatus,
    Deal,
    DealStatus,
    EmailConfig,
    EntityType,
)
from app.services.events import emit

log = logging.getLogger("nakatomi.approvals")

# Actions the CRM can auto-run after approval.
EXECUTABLE_ACTIONS = frozenset({"email.send", "deal.won", "deal.lost"})


def workspace_approval_policies(workspace_data: dict | None) -> list[dict]:
    """Read ``workspace.data.policies.approvals`` list."""
    if not workspace_data:
        return []
    policies = workspace_data.get("policies") or {}
    raw = policies.get("approvals") or []
    return raw if isinstance(raw, list) else []


def action_requires_approval(workspace_data: dict | None, action: str, payload: dict) -> bool:
    """Return True if workspace policy says this action needs HITL."""
    for rule in workspace_approval_policies(workspace_data):
        if not isinstance(rule, dict):
            continue
        if rule.get("action") != action:
            continue
        if not rule.get("required", True):
            continue
        when = rule.get("when") or {}
        if "amount_gte" in when:
            amount = payload.get("amount")
            try:
                if amount is None or float(amount) < float(when["amount_gte"]):
                    continue
            except (TypeError, ValueError):
                continue
        return True
    return False


def default_expiry(hours: int = 72) -> datetime:
    return datetime.now(UTC) + timedelta(hours=hours)


def create_approval(
    db: Session,
    principal: Principal,
    *,
    action: str,
    payload: dict,
    entity_type: str | None = None,
    entity_id: str | None = None,
    reason: str | None = None,
    expires_at: datetime | None = None,
    data: dict | None = None,
) -> ApprovalRequest:
    row = ApprovalRequest(
        workspace_id=principal.workspace.id,
        action=action,
        payload=payload or {},
        status=ApprovalStatus.pending,
        requested_by_user_id=principal.user_id,
        requested_by_api_key_id=principal.api_key_id,
        entity_type=entity_type,
        entity_id=entity_id,
        reason=reason,
        expires_at=expires_at or default_expiry(),
        data=data or {},
    )
    db.add(row)
    db.flush()
    emit(
        db,
        principal,
        event_type="approval.requested",
        entity_type=EntityType.task,  # nearest polymorphic bucket; payload has real ids
        entity_id=row.id,
        payload={
            "approval_id": row.id,
            "action": action,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "reason": reason,
        },
    )
    db.commit()
    db.refresh(row)
    return row


def _expire_if_needed(row: ApprovalRequest) -> bool:
    if row.status != ApprovalStatus.pending:
        return False
    if row.expires_at and row.expires_at < datetime.now(UTC):
        row.status = ApprovalStatus.expired
        return True
    return False


def decide_approval(
    db: Session,
    principal: Principal,
    row: ApprovalRequest,
    *,
    approve: bool,
    note: str | None = None,
    execute: bool = True,
) -> ApprovalRequest:
    if _expire_if_needed(row):
        db.commit()
        db.refresh(row)
        return row
    if row.status != ApprovalStatus.pending:
        return row

    row.decided_at = datetime.now(UTC)
    row.decided_by_user_id = principal.user_id
    row.decided_by_api_key_id = principal.api_key_id
    row.decision_note = note
    row.status = ApprovalStatus.approved if approve else ApprovalStatus.rejected

    emit(
        db,
        principal,
        event_type="approval.decided",
        entity_type=EntityType.task,
        entity_id=row.id,
        payload={
            "approval_id": row.id,
            "action": row.action,
            "status": row.status.value,
            "note": note,
        },
    )

    if approve and execute and row.action in EXECUTABLE_ACTIONS:
        try:
            result = execute_approval_action(db, principal, row)
            row.result = result or {}
            row.status = ApprovalStatus.executed
            emit(
                db,
                principal,
                event_type="approval.executed",
                entity_type=EntityType.task,
                entity_id=row.id,
                payload={"approval_id": row.id, "action": row.action, "result": row.result},
            )
        except Exception as exc:  # noqa: BLE001
            log.exception("approval execute failed")
            row.result = {"error": str(exc)}
            # stay approved so a human can retry / inspect
            row.status = ApprovalStatus.approved

    # Resume linked A2A tasks (P1 HITL bridge)
    _sync_linked_a2a_task(db, principal, row, approved=approve)

    db.commit()
    db.refresh(row)
    return row


def _sync_linked_a2a_task(db: Session, principal: Principal, row: ApprovalRequest, *, approved: bool) -> None:
    """When an approval is tied to an A2A task, complete or fail that task."""
    from app.models import A2ATask, A2ATaskStatus

    a2a_id = (row.payload or {}).get("a2a_task_id")
    if not a2a_id:
        # reverse lookup by linked_approval_id
        task = db.scalar(select(A2ATask).where(A2ATask.linked_approval_id == row.id))
    else:
        task = db.get(A2ATask, a2a_id)
    if not task or task.workspace_id != principal.workspace.id:
        return
    if task.status not in (A2ATaskStatus.input_required, A2ATaskStatus.working, A2ATaskStatus.submitted):
        return
    if approved:
        task.status = A2ATaskStatus.working
        msgs = list(task.messages or [])
        msgs.append(
            {
                "role": "system",
                "parts": [{"type": "text", "text": "approval granted — resume work"}],
                "at": datetime.now(UTC).isoformat(),
            }
        )
        task.messages = msgs
    else:
        task.status = A2ATaskStatus.failed
        task.completed_at = datetime.now(UTC)
        task.result = {"error": "approval rejected", "approval_id": row.id}
    emit(
        db,
        principal,
        event_type="a2a.task.updated",
        entity_type=EntityType.task,
        entity_id=task.id,
        payload={"a2a_task_id": task.id, "status": task.status.value, "via": "approval"},
    )


def execute_approval_action(db: Session, principal: Principal, row: ApprovalRequest) -> dict[str, Any]:
    """Run a known action. Raises on failure."""
    action = row.action
    payload = row.payload or {}

    if action == "email.send":
        from app.services.email_io import send_email

        cfg = db.scalar(select(EmailConfig).where(EmailConfig.workspace_id == principal.workspace.id))
        if cfg is None or not cfg.smtp_host:
            raise RuntimeError("email SMTP not configured")
        to_addrs = payload.get("to") or []
        if isinstance(to_addrs, str):
            to_addrs = [to_addrs]
        cc = payload.get("cc") or []
        bcc = payload.get("bcc") or []
        if isinstance(cc, str):
            cc = [cc]
        if isinstance(bcc, str):
            bcc = [bcc]
        send_email(
            cfg,
            to=to_addrs,
            subject=payload.get("subject") or "",
            body=payload.get("body") or "",
            body_html=payload.get("body_html"),
            cc=cc,
            bcc=bcc,
        )
        entity_type = None
        entity_id = payload.get("entity_id") or payload.get("contact_id") or payload.get("deal_id")
        if payload.get("entity_type"):
            entity_type = EntityType(payload["entity_type"])
        elif payload.get("contact_id"):
            entity_type = EntityType.contact
        elif payload.get("deal_id"):
            entity_type = EntityType.deal
        act = Activity(
            workspace_id=principal.workspace.id,
            kind="email_outbound",
            subject=(payload.get("subject") or "")[:500],
            body=(payload.get("body") or "")[:50_000],
            entity_type=entity_type,
            entity_id=entity_id,
            data={"approval_id": row.id, "to": to_addrs},
        )
        db.add(act)
        db.flush()
        return {"activity_id": act.id, "sent": True}

    if action in ("deal.won", "deal.lost"):
        deal_id = payload.get("deal_id") or row.entity_id
        if not deal_id:
            raise RuntimeError("deal_id required")
        deal = db.get(Deal, deal_id)
        if not deal or deal.workspace_id != principal.workspace.id:
            raise RuntimeError("deal not found")
        deal.status = DealStatus.won if action == "deal.won" else DealStatus.lost
        deal.closed_at = datetime.now(UTC)
        db.flush()
        return {"deal_id": deal.id, "status": deal.status.value}

    raise RuntimeError(f"action not executable: {action}")
