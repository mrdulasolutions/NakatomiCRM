"""Dispatch CRM imports by source."""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.deps import Principal


@dataclass
class ImportResult:
    source: str
    dry_run: bool
    created: dict[str, int] = field(default_factory=dict)
    updated: dict[str, int] = field(default_factory=dict)
    skipped: dict[str, int] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    id_map: dict[str, str] = field(default_factory=dict)  # external → nakatomi id
    diagnostics: list[dict] = field(default_factory=list)


def run_crm_import(
    db: Session,
    principal: Principal,
    *,
    source: str,
    payload: dict | list,
    mapping: dict | None = None,
    dry_run: bool = False,
) -> ImportResult:
    # Lazy imports avoid circular dependency with source modules.
    from app.services.importers import attio, generic, hubspot, pipedrive, salesforce

    handlers = {
        "hubspot": hubspot.import_hubspot,
        "salesforce": salesforce.import_salesforce,
        "pipedrive": pipedrive.import_pipedrive,
        "attio": attio.import_attio,
        "generic": generic.import_generic,
    }
    src = (source or "").lower().strip()
    handler = handlers.get(src)
    if not handler:
        result = ImportResult(source=src or "unknown", dry_run=dry_run)
        result.errors.append(f"unknown source '{source}'; use hubspot|salesforce|pipedrive|attio|generic")
        return result
    return handler(db, principal, payload=payload, mapping=mapping or {}, dry_run=dry_run)
