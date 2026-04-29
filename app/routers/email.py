"""Email config + outbound send.

Per-workspace IMAP/SMTP credentials live in ``EmailConfig``. Either half
can be left unset — workspaces that only need outbound (agents sending)
fill SMTP only and leave IMAP blank, and the inbound poller skips them.

Outbound is synchronous (``POST /email/send`` blocks on SMTP). For
fire-and-forget sends, push the call into a background task on the
caller side — we don't wrap that here to keep the contract honest.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import Principal, get_principal, require_role
from app.models import Activity, EmailConfig, EntityType, MemberRole
from app.schemas import (
    EmailConfigIn,
    EmailConfigOut,
    EmailSendRequest,
    EmailSendResponse,
    OkResponse,
)
from app.services.email_io import send_email
from app.services.events import emit

router = APIRouter(prefix="/email", tags=["email"])


@router.get("/config", response_model=EmailConfigOut | None)
def get_config(db: Session = Depends(get_db), p: Principal = Depends(get_principal)) -> EmailConfigOut | None:
    cfg = db.scalar(select(EmailConfig).where(EmailConfig.workspace_id == p.workspace.id))
    return EmailConfigOut.model_validate(cfg) if cfg else None


@router.put("/config", response_model=EmailConfigOut)
def put_config(
    payload: EmailConfigIn,
    db: Session = Depends(get_db),
    p: Principal = Depends(require_role(MemberRole.owner, MemberRole.admin)),
) -> EmailConfigOut:
    cfg = db.scalar(select(EmailConfig).where(EmailConfig.workspace_id == p.workspace.id))
    fields = payload.model_dump()
    if cfg is None:
        cfg = EmailConfig(workspace_id=p.workspace.id, **fields)
        db.add(cfg)
    else:
        for k, v in fields.items():
            setattr(cfg, k, v)
    db.commit()
    db.refresh(cfg)
    return EmailConfigOut.model_validate(cfg)


@router.delete("/config", response_model=OkResponse)
def delete_config(
    db: Session = Depends(get_db),
    p: Principal = Depends(require_role(MemberRole.owner, MemberRole.admin)),
) -> OkResponse:
    cfg = db.scalar(select(EmailConfig).where(EmailConfig.workspace_id == p.workspace.id))
    if cfg:
        db.delete(cfg)
        db.commit()
    return OkResponse(message="deleted")


@router.post("/send", response_model=EmailSendResponse)
def send(
    payload: EmailSendRequest,
    db: Session = Depends(get_db),
    p: Principal = Depends(require_role(MemberRole.owner, MemberRole.admin, MemberRole.member)),
) -> EmailSendResponse:
    cfg = db.scalar(select(EmailConfig).where(EmailConfig.workspace_id == p.workspace.id))
    if cfg is None or not cfg.smtp_host:
        raise HTTPException(status_code=400, detail="SMTP not configured for this workspace")
    if not payload.to:
        raise HTTPException(status_code=422, detail="`to` must contain at least one recipient")

    try:
        send_email(
            cfg,
            to=payload.to,
            cc=payload.cc,
            bcc=payload.bcc,
            subject=payload.subject,
            body=payload.body,
            body_html=payload.body_html,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"smtp send failed: {exc}") from exc

    sent_at = datetime.now(UTC)
    entity_type = None
    entity_id = None
    if payload.contact_id:
        entity_type, entity_id = EntityType.contact, payload.contact_id
    elif payload.deal_id:
        entity_type, entity_id = EntityType.deal, payload.deal_id

    activity = Activity(
        workspace_id=p.workspace.id,
        kind="email_outbound",
        subject=payload.subject[:500],
        body=payload.body[:50_000],
        occurred_at=sent_at,
        entity_type=entity_type,
        entity_id=entity_id,
        data={
            "to": payload.to,
            "cc": payload.cc,
            "bcc": payload.bcc,
            "from": cfg.from_address or cfg.smtp_user,
        },
    )
    db.add(activity)
    db.flush()
    if entity_id:
        emit(
            db,
            p,
            event_type="email.sent",
            entity_type=entity_type,
            entity_id=entity_id,
            payload={"activity_id": activity.id, "subject": payload.subject},
        )
    db.commit()
    db.refresh(activity)
    return EmailSendResponse(activity_id=activity.id, sent_at=sent_at, to=payload.to, subject=payload.subject)
