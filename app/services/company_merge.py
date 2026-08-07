"""Merge two companies — rewrite FKs from loser → winner."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.deps import Principal
from app.models import (
    Company,
    Contact,
    Deal,
    EntityType,
    Lead,
)
from app.services.events import emit


def merge_companies(
    db: Session,
    principal: Principal,
    *,
    winner_id: str,
    loser_id: str,
    dry_run: bool = False,
) -> dict[str, Any]:
    if winner_id == loser_id:
        raise ValueError("winner and loser must differ")
    ws = principal.workspace.id
    winner = db.get(Company, winner_id)
    loser = db.get(Company, loser_id)
    if not winner or winner.workspace_id != ws or winner.deleted_at:
        raise ValueError("winner not found")
    if not loser or loser.workspace_id != ws or loser.deleted_at:
        raise ValueError("loser not found")

    rewrites = {"contacts": 0, "deals": 0, "leads": 0, "child_companies": 0}
    for c in db.query(Contact).filter(Contact.company_id == loser_id).all() if False else []:
        pass  # use select
    from sqlalchemy import select, update

    contacts = db.scalars(select(Contact).where(Contact.company_id == loser_id)).all()
    deals = db.scalars(select(Deal).where(Deal.company_id == loser_id)).all()
    leads = db.scalars(select(Lead).where(Lead.converted_company_id == loser_id)).all()
    children = db.scalars(select(Company).where(Company.parent_company_id == loser_id)).all()
    rewrites["contacts"] = len(contacts)
    rewrites["deals"] = len(deals)
    rewrites["leads"] = len(leads)
    rewrites["child_companies"] = len(children)

    changes: dict[str, dict] = {}
    for field in ("domain", "website", "industry", "description"):
        wv, lv = getattr(winner, field), getattr(loser, field)
        if wv in (None, "") and lv not in (None, ""):
            changes[field] = {"from": wv, "to": lv}

    if dry_run:
        return {
            "winner_id": winner_id,
            "loser_id": loser_id,
            "changes": changes,
            "references_rewritten": rewrites,
            "dry_run": True,
        }

    for field, ch in changes.items():
        setattr(winner, field, ch["to"])
    # merge tags
    winner.tags = list({*(winner.tags or []), *(loser.tags or [])})

    for c in contacts:
        c.company_id = winner_id
    for d in deals:
        d.company_id = winner_id
    for lead in leads:
        lead.converted_company_id = winner_id
    for child in children:
        child.parent_company_id = winner_id

    loser.deleted_at = datetime.now(UTC)
    loser.data = {**(loser.data or {}), "merged_into": winner_id}
    emit(
        db,
        principal,
        event_type="company.merged",
        entity_type=EntityType.company,
        entity_id=winner_id,
        payload={"winner_id": winner_id, "loser_id": loser_id, "rewrites": rewrites},
    )
    db.commit()
    return {
        "winner_id": winner_id,
        "loser_id": loser_id,
        "changes": changes,
        "references_rewritten": rewrites,
        "dry_run": False,
    }
