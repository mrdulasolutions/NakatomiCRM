"""Lead conversion — contact + optional company + optional deal."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.deps import Principal
from app.models import (
    Company,
    Contact,
    Deal,
    DealStatus,
    EntityType,
    Lead,
    LeadStatus,
    Pipeline,
    Stage,
)
from app.services.events import emit


def convert_lead(
    db: Session,
    principal: Principal,
    lead: Lead,
    *,
    create_company: bool = True,
    create_deal: bool = False,
    deal_name: str | None = None,
    pipeline_id: str | None = None,
    stage_id: str | None = None,
    amount: float | None = None,
    link_existing_contact: bool = True,
) -> dict[str, Any]:
    """Convert lead → contact (+ company/deal). Idempotent if already converted."""
    if lead.status == LeadStatus.converted and lead.converted_contact_id:
        return {
            "lead_id": lead.id,
            "contact_id": lead.converted_contact_id,
            "company_id": lead.converted_company_id,
            "deal_id": lead.converted_deal_id,
            "already_converted": True,
        }

    ws = principal.workspace.id
    contact = None
    if link_existing_contact and lead.email:
        contact = db.scalar(
            select(Contact).where(
                Contact.workspace_id == ws,
                func.lower(Contact.email) == lead.email.lower(),
                Contact.deleted_at.is_(None),
            )
        )

    company = None
    if create_company and (lead.company_name or lead.company_domain):
        if lead.company_domain:
            company = db.scalar(
                select(Company).where(
                    Company.workspace_id == ws,
                    func.lower(Company.domain) == lead.company_domain.lower(),
                    Company.deleted_at.is_(None),
                )
            )
        if company is None and lead.company_name:
            company = Company(
                workspace_id=ws,
                name=lead.company_name,
                domain=lead.company_domain,
            )
            db.add(company)
            db.flush()
            emit(
                db,
                principal,
                event_type="company.created",
                entity_type=EntityType.company,
                entity_id=company.id,
                payload={"via": "lead.convert", "lead_id": lead.id},
            )

    if contact is None:
        contact = Contact(
            workspace_id=ws,
            first_name=lead.first_name,
            last_name=lead.last_name,
            email=lead.email,
            phone=lead.phone,
            title=lead.title,
            company_id=company.id if company else None,
            tags=list(lead.tags or []),
            data={**(lead.data or {}), "converted_from_lead_id": lead.id},
        )
        db.add(contact)
        db.flush()
        emit(
            db,
            principal,
            event_type="contact.created",
            entity_type=EntityType.contact,
            entity_id=contact.id,
            payload={"via": "lead.convert", "lead_id": lead.id},
        )
    else:
        if company and not contact.company_id:
            contact.company_id = company.id

    deal = None
    if create_deal:
        pipe = None
        if pipeline_id:
            pipe = db.get(Pipeline, pipeline_id)
        if pipe is None:
            pipe = db.scalar(
                select(Pipeline)
                .where(Pipeline.workspace_id == ws)
                .order_by(Pipeline.is_default.desc(), Pipeline.created_at.asc())
                .limit(1)
            )
        if pipe is None:
            raise ValueError("no pipeline — create a pipeline before converting to a deal")
        st = None
        if stage_id:
            st = db.get(Stage, stage_id)
        if st is None:
            st = db.scalar(
                select(Stage).where(Stage.pipeline_id == pipe.id).order_by(Stage.position).limit(1)
            )
        if st is None:
            raise ValueError("pipeline has no stages")
        name = deal_name or (
            f"{lead.company_name or (lead.first_name or 'Lead')}"
            + (f" — {lead.last_name}" if lead.last_name else "")
        )
        deal = Deal(
            workspace_id=ws,
            name=name.strip(" —") or "Converted lead",
            pipeline_id=pipe.id,
            stage_id=st.id,
            status=DealStatus.open,
            amount=amount,
            primary_contact_id=contact.id,
            company_id=company.id if company else contact.company_id,
            owner_user_id=lead.owner_user_id,
            data={"converted_from_lead_id": lead.id},
        )
        db.add(deal)
        db.flush()
        emit(
            db,
            principal,
            event_type="deal.created",
            entity_type=EntityType.deal,
            entity_id=deal.id,
            payload={"via": "lead.convert", "lead_id": lead.id},
        )

    lead.status = LeadStatus.converted
    lead.converted_contact_id = contact.id
    lead.converted_company_id = company.id if company else None
    lead.converted_deal_id = deal.id if deal else None
    lead.converted_at = datetime.now(UTC)
    emit(
        db,
        principal,
        event_type="lead.converted",
        entity_type=EntityType.lead,
        entity_id=lead.id,
        payload={
            "contact_id": contact.id,
            "company_id": company.id if company else None,
            "deal_id": deal.id if deal else None,
        },
    )
    db.commit()
    return {
        "lead_id": lead.id,
        "contact_id": contact.id,
        "company_id": company.id if company else None,
        "deal_id": deal.id if deal else None,
        "already_converted": False,
    }
