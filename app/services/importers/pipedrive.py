"""Pipedrive export-shaped import.

Accepts ``{ "persons": [...], "organizations": [...], "deals": [...] }``
or Pipedrive API list wrappers with ``data`` arrays.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.deps import Principal
from app.services.importers.base import ImportResult
from app.services.importers.common import dig, upsert_company, upsert_contact, upsert_deal


def _list(payload: dict, *keys: str) -> list:
    for k in keys:
        v = payload.get(k)
        if isinstance(v, list):
            return v
        if isinstance(v, dict) and isinstance(v.get("data"), list):
            return v["data"]
    return []


def import_pipedrive(
    db: Session,
    p: Principal,
    *,
    payload: dict | list,
    mapping: dict,
    dry_run: bool,
) -> ImportResult:
    result = ImportResult(source="pipedrive", dry_run=dry_run)
    if isinstance(payload, list):
        payload = {"persons": payload}

    orgs = _list(payload, "organizations", "orgs")
    persons = _list(payload, "persons", "people")
    deals = _list(payload, "deals")

    org_map: dict[str, str] = {}
    for o in orgs:
        ext = str(o.get("id") or "")
        cid = upsert_company(
            db,
            p,
            result,
            name=o.get("name") or "Org",
            domain=dig(o, "cc_email") or None,
            external_id=f"pd-org-{ext}" if ext else None,
            data={"pipedrive": o},
            dry_run=dry_run,
        )
        if ext and cid:
            org_map[ext] = cid

    person_map: dict[str, str] = {}
    for pe in persons:
        ext = str(pe.get("id") or "")
        email = None
        emails = pe.get("email") or []
        if isinstance(emails, list) and emails:
            email = emails[0].get("value") if isinstance(emails[0], dict) else emails[0]
        elif isinstance(emails, str):
            email = emails
        phone = None
        phones = pe.get("phone") or []
        if isinstance(phones, list) and phones:
            phone = phones[0].get("value") if isinstance(phones[0], dict) else phones[0]
        org_id = str(pe.get("org_id") or dig(pe, "org_id.value") or "")
        cid = upsert_contact(
            db,
            p,
            result,
            email=email,
            first_name=(pe.get("first_name") or (pe.get("name") or "").split(" ")[0] or None),
            last_name=pe.get("last_name"),
            phone=phone,
            company_id=org_map.get(org_id),
            external_id=f"pd-person-{ext}" if ext else None,
            data={"pipedrive": pe},
            dry_run=dry_run,
        )
        if ext and cid:
            person_map[ext] = cid

    for d in deals:
        ext = str(d.get("id") or "")
        status_raw = (d.get("status") or "open").lower()
        status = "won" if status_raw == "won" else ("lost" if status_raw == "lost" else "open")
        amount = d.get("value") or d.get("amount")
        try:
            amount = float(amount) if amount not in (None, "") else None
        except (TypeError, ValueError):
            amount = None
        org_id = str(d.get("org_id") or dig(d, "org_id.value") or "")
        person_id = str(d.get("person_id") or dig(d, "person_id.value") or "")
        upsert_deal(
            db,
            p,
            result,
            name=d.get("title") or d.get("name") or "Pipedrive deal",
            amount=amount,
            company_id=org_map.get(org_id),
            contact_id=person_map.get(person_id),
            external_id=f"pd-deal-{ext}" if ext else None,
            status=status,
            data={"pipedrive": d},
            dry_run=dry_run,
        )

    if not dry_run:
        db.commit()
    else:
        db.rollback()
    return result
