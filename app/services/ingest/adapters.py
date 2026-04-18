"""Built-in ingest adapters: csv, vcard, json, text."""

from __future__ import annotations

import csv
import io
import re
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.deps import Principal
from app.models import Company, Contact, EntityType, Note
from app.services.ingest.base import (
    IngestResult,
    norm_domain,
    norm_email,
    norm_phone,
    norm_str,
    norm_tags,
    norm_url,
    register_adapter,
)


# ---------- CSV ----------


@register_adapter("csv")
def ingest_csv(
    db: Session, p: Principal, payload: Any, mapping: dict | None, dry_run: bool
) -> IngestResult:
    if not isinstance(payload, str):
        return IngestResult(
            error_count=1,
            diagnostics=[{"level": "error", "message": "csv payload must be a string"}],
        )
    mapping = mapping or {}
    target = (mapping.get("_entity") or "contact").lower()
    reader = csv.DictReader(io.StringIO(payload))
    result = IngestResult()
    for i, row in enumerate(reader):
        mapped = {tgt: row.get(src) for src, tgt in mapping.items() if src != "_entity"}
        # When no mapping is provided, fall back to column-name matching.
        if not mapping:
            mapped = {k.lower().strip(): v for k, v in row.items()}
        try:
            if target == "company":
                _upsert_company(db, p, mapped, result, dry_run, row_index=i)
            else:
                _upsert_contact(db, p, mapped, result, dry_run, row_index=i)
        except Exception as e:  # noqa: BLE001
            result.error_count += 1
            result.diagnostics.append(
                {"level": "error", "message": str(e), "row": i}
            )
        result.record_count += 1
    return result


# ---------- JSON (list of dicts) ----------


@register_adapter("json")
def ingest_json(
    db: Session, p: Principal, payload: Any, mapping: dict | None, dry_run: bool
) -> IngestResult:
    if isinstance(payload, dict):
        payload = [payload]
    if not isinstance(payload, list):
        return IngestResult(
            error_count=1,
            diagnostics=[{"level": "error", "message": "json payload must be a dict or list of dicts"}],
        )
    mapping = mapping or {}
    target = (mapping.get("_entity") or "contact").lower()
    result = IngestResult()
    for i, row in enumerate(payload):
        if not isinstance(row, dict):
            result.error_count += 1
            result.diagnostics.append(
                {"level": "error", "message": "row is not a dict", "row": i}
            )
            continue
        if mapping:
            mapped = {tgt: row.get(src) for src, tgt in mapping.items() if src != "_entity"}
        else:
            mapped = {k.lower(): v for k, v in row.items()}
        try:
            if target == "company":
                _upsert_company(db, p, mapped, result, dry_run, row_index=i)
            else:
                _upsert_contact(db, p, mapped, result, dry_run, row_index=i)
        except Exception as e:  # noqa: BLE001
            result.error_count += 1
            result.diagnostics.append(
                {"level": "error", "message": str(e), "row": i}
            )
        result.record_count += 1
    return result


# ---------- vCard ----------

_VCARD_RE = re.compile(r"^(?P<key>[A-Z]+)(?:;[^:]*)?:(?P<value>.*)$")


def _parse_vcards(blob: str) -> list[dict]:
    cards: list[dict] = []
    current: dict | None = None
    for raw in blob.splitlines():
        line = raw.rstrip("\r")
        if line == "BEGIN:VCARD":
            current = {}
            continue
        if line == "END:VCARD":
            if current is not None:
                cards.append(current)
            current = None
            continue
        if current is None:
            continue
        m = _VCARD_RE.match(line)
        if not m:
            continue
        key, value = m.group("key"), m.group("value")
        current.setdefault(key, []).append(value)
    return cards


@register_adapter("vcard")
def ingest_vcard(
    db: Session, p: Principal, payload: Any, mapping: dict | None, dry_run: bool
) -> IngestResult:
    if not isinstance(payload, str):
        return IngestResult(
            error_count=1,
            diagnostics=[{"level": "error", "message": "vcard payload must be a string"}],
        )
    result = IngestResult()
    cards = _parse_vcards(payload)
    for i, card in enumerate(cards):
        fn = (card.get("FN") or [""])[0]
        n = (card.get("N") or [""])[0]
        last, first = "", fn
        if n and ";" in n:
            parts = n.split(";")
            last = parts[0]
            first = parts[1] if len(parts) > 1 else first
        mapped = {
            "first_name": first,
            "last_name": last,
            "email": (card.get("EMAIL") or [None])[0],
            "phone": (card.get("TEL") or [None])[0],
            "title": (card.get("TITLE") or [None])[0],
            "data": {"vcard": {k: v for k, v in card.items()}},
        }
        try:
            _upsert_contact(db, p, mapped, result, dry_run, row_index=i)
        except Exception as e:  # noqa: BLE001
            result.error_count += 1
            result.diagnostics.append(
                {"level": "error", "message": str(e), "row": i}
            )
        result.record_count += 1
    return result


# ---------- Text ----------
# For text blobs, we don't parse entities (that's the agent's job). We attach
# the text as a Note on a caller-specified entity, or bail if no entity hint.


@register_adapter("text")
def ingest_text(
    db: Session, p: Principal, payload: Any, mapping: dict | None, dry_run: bool
) -> IngestResult:
    if not isinstance(payload, str):
        return IngestResult(
            error_count=1,
            diagnostics=[{"level": "error", "message": "text payload must be a string"}],
        )
    mapping = mapping or {}
    et_raw = mapping.get("entity_type")
    eid = mapping.get("entity_id")
    if not et_raw or not eid:
        return IngestResult(
            error_count=1,
            diagnostics=[
                {
                    "level": "error",
                    "message": "text ingest requires mapping.entity_type and mapping.entity_id",
                }
            ],
        )
    try:
        et = EntityType(et_raw)
    except ValueError:
        return IngestResult(
            error_count=1,
            diagnostics=[{"level": "error", "message": f"unknown entity_type '{et_raw}'"}],
        )
    result = IngestResult(record_count=1)
    if dry_run:
        result.diagnostics.append(
            {"level": "info", "message": f"would attach a note ({len(payload)} chars) to {et.value}:{eid}"}
        )
        return result
    n = Note(
        workspace_id=p.workspace.id,
        author_user_id=p.user_id,
        entity_type=et,
        entity_id=eid,
        body=payload,
    )
    db.add(n)
    db.flush()
    result.created_ids.append(n.id)
    return result


# ---------- helpers ----------


def _upsert_contact(
    db: Session,
    p: Principal,
    row: dict,
    result: IngestResult,
    dry_run: bool,
    *,
    row_index: int,
) -> None:
    email = norm_email(row.get("email"))
    external_id = norm_str(row.get("external_id"))
    if not (email or external_id or row.get("first_name") or row.get("last_name")):
        result.error_count += 1
        result.diagnostics.append(
            {"level": "error", "message": "row needs email, external_id, or a name", "row": row_index}
        )
        return
    existing = None
    if external_id:
        existing = db.scalar(
            select(Contact).where(
                Contact.workspace_id == p.workspace.id, Contact.external_id == external_id
            )
        )
    if not existing and email:
        existing = db.scalar(
            select(Contact).where(
                Contact.workspace_id == p.workspace.id, func.lower(Contact.email) == email
            )
        )
    fields = {
        "first_name": norm_str(row.get("first_name")),
        "last_name": norm_str(row.get("last_name")),
        "email": email,
        "phone": norm_phone(row.get("phone")),
        "title": norm_str(row.get("title")),
        "external_id": external_id,
        "tags": norm_tags(row.get("tags")),
        "data": row.get("data") or {},
    }
    fields = {k: v for k, v in fields.items() if v not in (None, [], {})}

    if dry_run:
        result.diagnostics.append(
            {"level": "info", "message": f"would {'update' if existing else 'create'} contact", "row": row_index}
        )
        return
    if existing:
        for k, v in fields.items():
            setattr(existing, k, v)
        result.updated_ids.append(existing.id)
    else:
        c = Contact(workspace_id=p.workspace.id, **fields)
        db.add(c)
        db.flush()
        result.created_ids.append(c.id)


def _upsert_company(
    db: Session,
    p: Principal,
    row: dict,
    result: IngestResult,
    dry_run: bool,
    *,
    row_index: int,
) -> None:
    name = norm_str(row.get("name"))
    domain = norm_domain(row.get("domain"))
    external_id = norm_str(row.get("external_id"))
    if not (name or domain or external_id):
        result.error_count += 1
        result.diagnostics.append(
            {"level": "error", "message": "row needs name, domain, or external_id", "row": row_index}
        )
        return
    existing = None
    if external_id:
        existing = db.scalar(
            select(Company).where(
                Company.workspace_id == p.workspace.id, Company.external_id == external_id
            )
        )
    if not existing and domain:
        existing = db.scalar(
            select(Company).where(
                Company.workspace_id == p.workspace.id, func.lower(Company.domain) == domain
            )
        )
    fields = {
        "name": name or domain or f"untitled-{row_index}",
        "domain": domain,
        "website": norm_url(row.get("website") or domain),
        "industry": norm_str(row.get("industry")),
        "description": norm_str(row.get("description")),
        "external_id": external_id,
        "tags": norm_tags(row.get("tags")),
        "data": row.get("data") or {},
    }
    fields = {k: v for k, v in fields.items() if v not in (None, [], {})}

    if dry_run:
        result.diagnostics.append(
            {"level": "info", "message": f"would {'update' if existing else 'create'} company", "row": row_index}
        )
        return
    if existing:
        for k, v in fields.items():
            setattr(existing, k, v)
        result.updated_ids.append(existing.id)
    else:
        c = Company(workspace_id=p.workspace.id, **fields)
        db.add(c)
        db.flush()
        result.created_ids.append(c.id)
