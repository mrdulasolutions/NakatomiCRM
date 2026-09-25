"""HubSpot CRM export-shaped import.

Accepts either:
- ``{ "contacts": [...], "companies": [...], "deals": [...], "notes": [...] }``
- HubSpot v3 list payloads ``{ "results": [ { "id", "properties": {...} } ] }``
  with a top-level ``type`` hint or separate keys.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.deps import Principal
from app.services.importers.base import ImportResult
from app.services.importers.common import add_note, dig, upsert_company, upsert_contact, upsert_deal


def _props(row: dict) -> dict:
    if "properties" in row and isinstance(row["properties"], dict):
        return {**row["properties"], "id": row.get("id")}
    return row


def import_hubspot(
    db: Session,
    p: Principal,
    *,
    payload: dict | list,
    mapping: dict,
    dry_run: bool,
) -> ImportResult:
    result = ImportResult(source="hubspot", dry_run=dry_run)
    if isinstance(payload, list):
        payload = {"contacts": payload}

    companies = payload.get("companies") or payload.get("companies.results") or []
    if isinstance(payload.get("companies"), dict) and "results" in payload["companies"]:
        companies = payload["companies"]["results"]
    contacts = payload.get("contacts") or []
    if isinstance(payload.get("contacts"), dict) and "results" in payload["contacts"]:
        contacts = payload["contacts"]["results"]
    deals = payload.get("deals") or []
    if isinstance(payload.get("deals"), dict) and "results" in payload["deals"]:
        deals = payload["deals"]["results"]
    notes = payload.get("notes") or payload.get("engagements") or []
    if isinstance(notes, dict) and "results" in notes:
        notes = notes["results"]

    company_map: dict[str, str] = {}
    for raw in companies:
        pr = _props(raw)
        ext = str(pr.get("id") or pr.get("hs_object_id") or "")
        cid = upsert_company(
            db,
            p,
            result,
            name=pr.get("name") or pr.get("domain") or "Company",
            domain=pr.get("domain"),
            external_id=f"hs-company-{ext}" if ext else None,
            data={"hubspot": pr},
            dry_run=dry_run,
        )
        if ext and cid:
            company_map[ext] = cid

    contact_map: dict[str, str] = {}
    for raw in contacts:
        pr = _props(raw)
        ext = str(pr.get("id") or pr.get("hs_object_id") or "")
        assoc_company = dig(raw, "associations.companies.results.0.id") or pr.get("associatedcompanyid")
        company_id = company_map.get(str(assoc_company)) if assoc_company else None
        cid = upsert_contact(
            db,
            p,
            result,
            email=pr.get("email"),
            first_name=pr.get("firstname") or pr.get("first_name"),
            last_name=pr.get("lastname") or pr.get("last_name"),
            phone=pr.get("phone"),
            title=pr.get("jobtitle") or pr.get("title"),
            company_id=company_id,
            external_id=f"hs-contact-{ext}" if ext else None,
            data={"hubspot": pr},
            dry_run=dry_run,
        )
        if ext and cid:
            contact_map[ext] = cid

    for raw in deals:
        pr = _props(raw)
        ext = str(pr.get("id") or pr.get("hs_object_id") or "")
        amount = pr.get("amount")
        try:
            amount = float(amount) if amount not in (None, "") else None
        except (TypeError, ValueError):
            amount = None
        stage = (pr.get("dealstage") or pr.get("stage") or "").lower()
        status = (
            "won"
            if "won" in stage or "closedwon" in stage
            else ("lost" if "lost" in stage or "closedlost" in stage else "open")
        )
        upsert_deal(
            db,
            p,
            result,
            name=pr.get("dealname") or pr.get("name") or "HubSpot deal",
            amount=amount,
            external_id=f"hs-deal-{ext}" if ext else None,
            status=status,
            data={"hubspot": pr},
            dry_run=dry_run,
        )

    for raw in notes:
        pr = _props(raw) if isinstance(raw, dict) else {}
        body = pr.get("hs_note_body") or pr.get("body") or pr.get("text") or ""
        # attach to first contact if present
        contact_ids = list(contact_map.values())
        if contact_ids and body:
            add_note(
                db,
                p,
                result,
                body=str(body),
                entity_type="contact",
                entity_id=contact_ids[0],
                dry_run=dry_run,
            )

    if not dry_run:
        db.commit()
    else:
        db.rollback()
    return result
