"""Attio-shaped import.

Accepts ``{ "companies": [...], "people": [...], "deals": [...] }`` where
records look like ``{ "id": {"record_id": "..."}, "values": { "name": [{"value": "..."}] } }``
or already-flattened dicts.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.deps import Principal
from app.services.importers.base import ImportResult
from app.services.importers.common import upsert_company, upsert_contact, upsert_deal


def _val(values: dict, key: str) -> Any:
    raw = values.get(key)
    if raw is None:
        return None
    if isinstance(raw, list) and raw:
        item = raw[0]
        if isinstance(item, dict):
            return item.get("value") or item.get("original_email_address") or item.get("domain")
        return item
    return raw


def _id(row: dict) -> str:
    rid = row.get("id")
    if isinstance(rid, dict):
        return str(rid.get("record_id") or rid.get("object_id") or "")
    return str(rid or "")


def import_attio(
    db: Session,
    p: Principal,
    *,
    payload: dict | list,
    mapping: dict,
    dry_run: bool,
) -> ImportResult:
    result = ImportResult(source="attio", dry_run=dry_run)
    if isinstance(payload, list):
        payload = {"people": payload}

    companies = payload.get("companies") or payload.get("records") or []
    people = payload.get("people") or payload.get("persons") or []
    deals = payload.get("deals") or []

    company_map: dict[str, str] = {}
    for row in companies:
        values = row.get("values") if isinstance(row.get("values"), dict) else row
        ext = _id(row)
        name = _val(values, "name") or row.get("name") or "Company"
        domain = _val(values, "domains") or _val(values, "domain") or row.get("domain")
        cid = upsert_company(
            db,
            p,
            result,
            name=str(name),
            domain=str(domain) if domain else None,
            external_id=f"attio-company-{ext}" if ext else None,
            data={"attio": row},
            dry_run=dry_run,
        )
        if ext and cid:
            company_map[ext] = cid

    for row in people:
        values = row.get("values") if isinstance(row.get("values"), dict) else row
        ext = _id(row)
        email = _val(values, "email_addresses") or _val(values, "email") or row.get("email")
        first = _val(values, "name") or row.get("first_name")
        # Attio name can be object
        if isinstance(first, dict):
            first_name = first.get("first_name")
            last_name = first.get("last_name")
        else:
            first_name = first
            last_name = row.get("last_name")
        upsert_contact(
            db,
            p,
            result,
            email=str(email) if email else None,
            first_name=str(first_name) if first_name else None,
            last_name=str(last_name) if last_name else None,
            external_id=f"attio-person-{ext}" if ext else None,
            data={"attio": row},
            dry_run=dry_run,
        )

    for row in deals:
        values = row.get("values") if isinstance(row.get("values"), dict) else row
        ext = _id(row)
        name = _val(values, "name") or row.get("name") or "Attio deal"
        amount = _val(values, "value") or row.get("amount")
        try:
            amount = float(amount) if amount not in (None, "") else None
        except (TypeError, ValueError):
            amount = None
        upsert_deal(
            db,
            p,
            result,
            name=str(name),
            amount=amount,
            external_id=f"attio-deal-{ext}" if ext else None,
            data={"attio": row},
            dry_run=dry_run,
        )

    if not dry_run:
        db.commit()
    else:
        db.rollback()
    return result
