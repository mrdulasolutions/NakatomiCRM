"""One-shot CRM imports (HubSpot, Salesforce, Pipedrive, Attio, generic)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import Principal, enforce_resource_scope, get_principal
from app.services.importers import run_crm_import

router = APIRouter(
    prefix="/import",
    tags=["import"],
    dependencies=[Depends(enforce_resource_scope("export"))],  # import uses export:write
)


class CrmImportRequest(BaseModel):
    source: str = Field(description="hubspot | salesforce | pipedrive | attio | generic")
    payload: dict | list
    mapping: dict | None = Field(
        default=None,
        description="optional field remaps for generic source, e.g. contacts.email -> Email",
    )
    dry_run: bool = False


@router.post("/crm")
def import_crm(
    req: CrmImportRequest,
    db: Session = Depends(get_db),
    p: Principal = Depends(get_principal),
):
    """Agent-driven CRM migration. No UI mapping — agents shape the payload."""
    # Prefer write scope for mutations
    if not p.can("export:write") and not p.can("*"):
        from fastapi import HTTPException

        raise HTTPException(
            status_code=403,
            detail="missing scopes: ['export:write']; suggestion: mint a key with export:write",
        )
    result = run_crm_import(
        db,
        p,
        source=req.source,
        payload=req.payload,
        mapping=req.mapping,
        dry_run=req.dry_run,
    )
    return {
        "source": result.source,
        "dry_run": result.dry_run,
        "created": result.created,
        "updated": result.updated,
        "skipped": result.skipped,
        "errors": result.errors,
        "id_map_sample": dict(list(result.id_map.items())[:20]),
        "diagnostics": result.diagnostics,
    }
