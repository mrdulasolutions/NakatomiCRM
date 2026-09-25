"""Generic mapped import.

Payload::

    {
      "companies": [ {"name": "...", "domain": "...", "external_id": "..."} ],
      "contacts": [ {"email": "...", "first_name": "...", "company_external_id": "..."} ],
      "deals": [ {"name": "...", "amount": 1, "contact_external_id": "..."} ]
    }

Optional ``mapping`` remaps field names: ``{"contacts.email": "Email Address"}``.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.deps import Principal
from app.services.importers.base import ImportResult
from app.services.importers.common import upsert_company, upsert_contact, upsert_deal


def _map_row(row: dict, mapping: dict, prefix: str) -> dict:
    out = dict(row)
    for target, source in mapping.items():
        if not target.startswith(prefix + "."):
            continue
        field = target.split(".", 1)[1]
        if source in row:
            out[field] = row[source]
    return out


def import_generic(
    db: Session,
    p: Principal,
    *,
    payload: dict | list,
    mapping: dict,
    dry_run: bool,
) -> ImportResult:
    result = ImportResult(source="generic", dry_run=dry_run)
    if isinstance(payload, list):
        payload = {"contacts": payload}

    company_by_ext: dict[str, str] = {}
    for raw in payload.get("companies") or []:
        row = _map_row(raw, mapping, "companies")
        ext = row.get("external_id")
        cid = upsert_company(
            db,
            p,
            result,
            name=row.get("name") or "Company",
            domain=row.get("domain"),
            external_id=ext,
            data=row.get("data") or {},
            dry_run=dry_run,
        )
        if ext and cid:
            company_by_ext[str(ext)] = cid

    contact_by_ext: dict[str, str] = {}
    for raw in payload.get("contacts") or []:
        row = _map_row(raw, mapping, "contacts")
        ext = row.get("external_id")
        company_ext = row.get("company_external_id")
        company_id = company_by_ext.get(str(company_ext)) if company_ext else row.get("company_id")
        cid = upsert_contact(
            db,
            p,
            result,
            email=row.get("email"),
            first_name=row.get("first_name"),
            last_name=row.get("last_name"),
            phone=row.get("phone"),
            title=row.get("title"),
            company_id=company_id,
            external_id=ext,
            data=row.get("data") or {},
            dry_run=dry_run,
        )
        if ext and cid:
            contact_by_ext[str(ext)] = cid

    for raw in payload.get("deals") or []:
        row = _map_row(raw, mapping, "deals")
        ext = row.get("external_id")
        company_ext = row.get("company_external_id")
        contact_ext = row.get("contact_external_id")
        amount = row.get("amount")
        try:
            amount = float(amount) if amount not in (None, "") else None
        except (TypeError, ValueError):
            amount = None
        upsert_deal(
            db,
            p,
            result,
            name=row.get("name") or "Deal",
            amount=amount,
            company_id=company_by_ext.get(str(company_ext)) if company_ext else row.get("company_id"),
            contact_id=contact_by_ext.get(str(contact_ext)) if contact_ext else row.get("primary_contact_id"),
            external_id=ext,
            status=row.get("status") or "open",
            data=row.get("data") or {},
            dry_run=dry_run,
        )

    if not dry_run:
        db.commit()
    else:
        db.rollback()
    return result
