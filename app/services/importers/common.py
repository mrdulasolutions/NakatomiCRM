"""Shared upsert helpers for CRM importers."""

from __future__ import annotations

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
    Note,
    Pipeline,
    Stage,
)
from app.services.events import emit
from app.services.importers.base import ImportResult


def upsert_company(
    db: Session,
    p: Principal,
    result: ImportResult,
    *,
    name: str,
    domain: str | None = None,
    external_id: str | None = None,
    data: dict | None = None,
    dry_run: bool = False,
) -> str | None:
    if not name and not domain and not external_id:
        return None
    existing = None
    if external_id:
        existing = db.scalar(
            select(Company).where(
                Company.workspace_id == p.workspace.id,
                Company.external_id == external_id,
            )
        )
    if existing is None and domain:
        existing = db.scalar(
            select(Company).where(
                Company.workspace_id == p.workspace.id,
                func.lower(Company.domain) == domain.lower(),
            )
        )
    if existing:
        if not dry_run:
            if name:
                existing.name = name
            if domain:
                existing.domain = domain
            if data:
                existing.data = {**(existing.data or {}), **data}
        result.updated["companies"] = result.updated.get("companies", 0) + 1
        if external_id:
            result.id_map[f"company:{external_id}"] = existing.id
        return existing.id
    if dry_run:
        result.created["companies"] = result.created.get("companies", 0) + 1
        return f"dry-company-{external_id or name}"
    row = Company(
        workspace_id=p.workspace.id,
        name=name or domain or "Imported company",
        domain=domain,
        external_id=external_id,
        data=data or {},
    )
    db.add(row)
    db.flush()
    emit(
        db,
        p,
        event_type="company.created",
        entity_type=EntityType.company,
        entity_id=row.id,
        payload={"via": "import", "external_id": external_id},
    )
    result.created["companies"] = result.created.get("companies", 0) + 1
    if external_id:
        result.id_map[f"company:{external_id}"] = row.id
    return row.id


def upsert_contact(
    db: Session,
    p: Principal,
    result: ImportResult,
    *,
    email: str | None = None,
    first_name: str | None = None,
    last_name: str | None = None,
    phone: str | None = None,
    title: str | None = None,
    company_id: str | None = None,
    external_id: str | None = None,
    data: dict | None = None,
    dry_run: bool = False,
) -> str | None:
    existing = None
    if external_id:
        existing = db.scalar(
            select(Contact).where(
                Contact.workspace_id == p.workspace.id,
                Contact.external_id == external_id,
            )
        )
    if existing is None and email:
        existing = db.scalar(
            select(Contact).where(
                Contact.workspace_id == p.workspace.id,
                func.lower(Contact.email) == email.lower(),
            )
        )
    if existing:
        if not dry_run:
            for k, v in {
                "first_name": first_name,
                "last_name": last_name,
                "phone": phone,
                "title": title,
                "company_id": company_id,
                "email": email,
            }.items():
                if v is not None:
                    setattr(existing, k, v)
            if data:
                existing.data = {**(existing.data or {}), **data}
        result.updated["contacts"] = result.updated.get("contacts", 0) + 1
        if external_id:
            result.id_map[f"contact:{external_id}"] = existing.id
        return existing.id
    if dry_run:
        result.created["contacts"] = result.created.get("contacts", 0) + 1
        return f"dry-contact-{external_id or email}"
    row = Contact(
        workspace_id=p.workspace.id,
        email=email,
        first_name=first_name,
        last_name=last_name,
        phone=phone,
        title=title,
        company_id=company_id if company_id and not str(company_id).startswith("dry-") else None,
        external_id=external_id,
        data=data or {},
    )
    db.add(row)
    db.flush()
    emit(
        db,
        p,
        event_type="contact.created",
        entity_type=EntityType.contact,
        entity_id=row.id,
        payload={"via": "import", "external_id": external_id},
    )
    result.created["contacts"] = result.created.get("contacts", 0) + 1
    if external_id:
        result.id_map[f"contact:{external_id}"] = row.id
    return row.id


def ensure_default_pipeline(db: Session, p: Principal, dry_run: bool) -> tuple[str | None, str | None]:
    pipe = db.scalar(
        select(Pipeline)
        .where(Pipeline.workspace_id == p.workspace.id)
        .order_by(Pipeline.is_default.desc())
        .limit(1)
    )
    if pipe:
        stage = db.scalar(select(Stage).where(Stage.pipeline_id == pipe.id).order_by(Stage.position).limit(1))
        return pipe.id, stage.id if stage else None
    if dry_run:
        return "dry-pipe", "dry-stage"
    pipe = Pipeline(
        workspace_id=p.workspace.id,
        name="Imported",
        slug="imported",
        is_default=True,
    )
    db.add(pipe)
    db.flush()
    stage = Stage(pipeline_id=pipe.id, name="Open", slug="open", position=0, probability=50)
    db.add(stage)
    db.flush()
    return pipe.id, stage.id


def upsert_deal(
    db: Session,
    p: Principal,
    result: ImportResult,
    *,
    name: str,
    amount: float | None = None,
    external_id: str | None = None,
    company_id: str | None = None,
    contact_id: str | None = None,
    pipeline_id: str | None = None,
    stage_id: str | None = None,
    status: str = "open",
    data: dict | None = None,
    dry_run: bool = False,
) -> str | None:
    existing = None
    if external_id:
        existing = db.scalar(
            select(Deal).where(
                Deal.workspace_id == p.workspace.id,
                Deal.external_id == external_id,
            )
        )
    if existing:
        if not dry_run:
            existing.name = name or existing.name
            if amount is not None:
                existing.amount = amount
            if company_id and not str(company_id).startswith("dry-"):
                existing.company_id = company_id
            if contact_id and not str(contact_id).startswith("dry-"):
                existing.primary_contact_id = contact_id
        result.updated["deals"] = result.updated.get("deals", 0) + 1
        if external_id:
            result.id_map[f"deal:{external_id}"] = existing.id
        return existing.id

    if dry_run:
        result.created["deals"] = result.created.get("deals", 0) + 1
        return f"dry-deal-{external_id or name}"

    if not pipeline_id or str(pipeline_id).startswith("dry-"):
        pipeline_id, stage_id = ensure_default_pipeline(db, p, dry_run=False)
    try:
        st = DealStatus(status) if status in ("open", "won", "lost") else DealStatus.open
    except ValueError:
        st = DealStatus.open
    row = Deal(
        workspace_id=p.workspace.id,
        name=name or "Imported deal",
        amount=amount,
        external_id=external_id,
        company_id=company_id if company_id and not str(company_id).startswith("dry-") else None,
        primary_contact_id=contact_id if contact_id and not str(contact_id).startswith("dry-") else None,
        pipeline_id=pipeline_id,
        stage_id=stage_id,
        status=st,
        data=data or {},
    )
    db.add(row)
    db.flush()
    emit(
        db,
        p,
        event_type="deal.created",
        entity_type=EntityType.deal,
        entity_id=row.id,
        payload={"via": "import", "external_id": external_id},
    )
    result.created["deals"] = result.created.get("deals", 0) + 1
    if external_id:
        result.id_map[f"deal:{external_id}"] = row.id
    return row.id


def add_note(
    db: Session,
    p: Principal,
    result: ImportResult,
    *,
    body: str,
    entity_type: str,
    entity_id: str,
    dry_run: bool = False,
) -> None:
    if not body or not entity_id or str(entity_id).startswith("dry-"):
        result.skipped["notes"] = result.skipped.get("notes", 0) + 1
        return
    if dry_run:
        result.created["notes"] = result.created.get("notes", 0) + 1
        return
    try:
        et = EntityType(entity_type)
    except ValueError:
        et = EntityType.contact
    note = Note(
        workspace_id=p.workspace.id,
        body=body,
        entity_type=et,
        entity_id=entity_id,
        data={"via": "import"},
    )
    db.add(note)
    db.flush()
    result.created["notes"] = result.created.get("notes", 0) + 1


def dig(obj: Any, *paths: str, default=None):
    """Try multiple dotted paths; return first hit."""
    for path in paths:
        cur = obj
        ok = True
        for part in path.split("."):
            if isinstance(cur, dict) and part in cur:
                cur = cur[part]
            else:
                ok = False
                break
        if ok and cur is not None:
            return cur
    return default
