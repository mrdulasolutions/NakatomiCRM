from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import Principal, get_principal, require_role
from app.models import MemberRole, Webhook, WebhookDelivery
from app.schemas import (
    OkResponse,
    WebhookCreatedOut,
    WebhookDeliveryOut,
    WebhookIn,
    WebhookOut,
    WebhookPatch,
)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.get("", response_model=list[WebhookOut])
def list_webhooks(db: Session = Depends(get_db), p: Principal = Depends(get_principal)):
    rows = db.scalars(select(Webhook).where(Webhook.workspace_id == p.workspace.id)).all()
    return [WebhookOut.model_validate(r) for r in rows]


@router.post("", response_model=WebhookCreatedOut, status_code=201)
def create_webhook(
    payload: WebhookIn,
    db: Session = Depends(get_db),
    p: Principal = Depends(require_role(MemberRole.owner, MemberRole.admin, MemberRole.member)),
) -> WebhookCreatedOut:
    secret = secrets.token_urlsafe(32)
    hook = Webhook(
        workspace_id=p.workspace.id,
        secret=secret,
        **payload.model_dump(),
    )
    db.add(hook)
    db.commit()
    db.refresh(hook)
    base = WebhookOut.model_validate(hook).model_dump()
    return WebhookCreatedOut(**base, secret=secret)


@router.patch("/{webhook_id}", response_model=WebhookOut)
def patch_webhook(
    webhook_id: str,
    payload: WebhookPatch,
    db: Session = Depends(get_db),
    p: Principal = Depends(require_role(MemberRole.owner, MemberRole.admin, MemberRole.member)),
):
    hook = db.get(Webhook, webhook_id)
    if not hook or hook.workspace_id != p.workspace.id:
        raise HTTPException(status_code=404, detail="not found")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(hook, k, v)
    db.commit()
    db.refresh(hook)
    return WebhookOut.model_validate(hook)


@router.delete("/{webhook_id}", response_model=OkResponse)
def delete_webhook(
    webhook_id: str,
    db: Session = Depends(get_db),
    p: Principal = Depends(require_role(MemberRole.owner, MemberRole.admin)),
):
    hook = db.get(Webhook, webhook_id)
    if not hook or hook.workspace_id != p.workspace.id:
        raise HTTPException(status_code=404, detail="not found")
    db.delete(hook)
    db.commit()
    return OkResponse(message="deleted")


@router.get("/{webhook_id}/deliveries", response_model=list[WebhookDeliveryOut])
def list_deliveries(
    webhook_id: str,
    db: Session = Depends(get_db),
    p: Principal = Depends(get_principal),
    limit: int = 50,
):
    hook = db.get(Webhook, webhook_id)
    if not hook or hook.workspace_id != p.workspace.id:
        raise HTTPException(status_code=404, detail="not found")
    rows = db.scalars(
        select(WebhookDelivery)
        .where(WebhookDelivery.webhook_id == webhook_id)
        .order_by(WebhookDelivery.created_at.desc())
        .limit(limit)
    ).all()
    return [WebhookDeliveryOut.model_validate(r) for r in rows]
