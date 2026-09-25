"""Salesforce-style import.

Accepts:
- ``{ "Account": [...], "Contact": [...], "Opportunity": [...] }`` (sObject API dumps)
- lower-case keys ``accounts``, ``contacts``, ``opportunities``
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.deps import Principal
from app.services.importers.base import ImportResult
from app.services.importers.common import dig, upsert_company, upsert_contact, upsert_deal


def import_salesforce(
    db: Session,
    p: Principal,
    *,
    payload: dict | list,
    mapping: dict,
    dry_run: bool,
) -> ImportResult:
    result = ImportResult(source="salesforce", dry_run=dry_run)
    if isinstance(payload, list):
        payload = {"Contact": payload}

    accounts = payload.get("Account") or payload.get("accounts") or []
    contacts = payload.get("Contact") or payload.get("contacts") or []
    opps = payload.get("Opportunity") or payload.get("opportunities") or []
    if isinstance(accounts, dict) and "records" in accounts:
        accounts = accounts["records"]
    if isinstance(contacts, dict) and "records" in contacts:
        contacts = contacts["records"]
    if isinstance(opps, dict) and "records" in opps:
        opps = opps["records"]

    acct_map: dict[str, str] = {}
    for a in accounts:
        ext = str(a.get("Id") or a.get("id") or "")
        cid = upsert_company(
            db,
            p,
            result,
            name=a.get("Name") or a.get("name") or "Account",
            domain=dig(a, "Website") or a.get("Site"),
            external_id=f"sf-account-{ext}" if ext else None,
            data={"salesforce": a},
            dry_run=dry_run,
        )
        if ext and cid:
            acct_map[ext] = cid

    for c in contacts:
        ext = str(c.get("Id") or c.get("id") or "")
        acct = str(c.get("AccountId") or c.get("account_id") or "")
        upsert_contact(
            db,
            p,
            result,
            email=c.get("Email") or c.get("email"),
            first_name=c.get("FirstName") or c.get("first_name"),
            last_name=c.get("LastName") or c.get("last_name"),
            phone=c.get("Phone") or c.get("phone"),
            title=c.get("Title") or c.get("title"),
            company_id=acct_map.get(acct),
            external_id=f"sf-contact-{ext}" if ext else None,
            data={"salesforce": c},
            dry_run=dry_run,
        )

    for o in opps:
        ext = str(o.get("Id") or o.get("id") or "")
        stage = (o.get("StageName") or o.get("stage") or "").lower()
        status = (
            "won"
            if "closed won" in stage or stage == "closedwon"
            else ("lost" if "closed lost" in stage or stage == "closedlost" else "open")
        )
        amount = o.get("Amount") or o.get("amount")
        try:
            amount = float(amount) if amount not in (None, "") else None
        except (TypeError, ValueError):
            amount = None
        acct = str(o.get("AccountId") or "")
        upsert_deal(
            db,
            p,
            result,
            name=o.get("Name") or o.get("name") or "Opportunity",
            amount=amount,
            company_id=acct_map.get(acct),
            external_id=f"sf-opp-{ext}" if ext else None,
            status=status,
            data={"salesforce": o},
            dry_run=dry_run,
        )

    if not dry_run:
        db.commit()
    else:
        db.rollback()
    return result
