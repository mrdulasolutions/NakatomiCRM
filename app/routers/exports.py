from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import Principal, require_role
from app.models import MemberRole, Workspace
from app.schemas import ImportRequest, ImportResponse
from app.services.export import build_export
from app.services.importer import apply_import

router = APIRouter(tags=["export-import"])


@router.get("/export")
def export_workspace(
    include_timeline: bool = False,
    db: Session = Depends(get_db),
    p: Principal = Depends(require_role(MemberRole.owner, MemberRole.admin)),
) -> JSONResponse:
    """Return a JSON dump of the entire workspace (minus operational state).

    File bytes are NOT included — fetch them via ``GET /files/{id}`` using the
    manifest in ``export["files"]``. Secrets on webhooks are redacted; mint new
    ones on import.
    """
    ws = db.get(Workspace, p.workspace.id)
    if not ws:
        raise HTTPException(status_code=404, detail="workspace vanished")
    body = build_export(db, ws, include_timeline=include_timeline)
    filename = f"nakatomi-{ws.slug}-{datetime.now(UTC).date().isoformat()}.json"
    return JSONResponse(
        content=body,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/import", response_model=ImportResponse)
def import_workspace(
    req: ImportRequest,
    db: Session = Depends(get_db),
    p: Principal = Depends(require_role(MemberRole.owner, MemberRole.admin)),
) -> ImportResponse:
    """Merge-upsert from an export document into the *current* workspace.

    Natural keys drive the match (``external_id`` first, then email/domain/slug).
    IDs in the source doc are translated to fresh UUIDs on this side; cross-row
    references (relationship edges, polymorphic entity_id on notes/tasks/etc.)
    are rewritten as each row lands.

    ``dry_run=true`` runs the full import against a savepoint and rolls it back,
    returning the counts and warnings you'd have gotten.
    """
    try:
        result = apply_import(db, p.workspace.id, req.doc, dry_run=req.dry_run)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    # apply_import releases its SAVEPOINT to the outer transaction but doesn't
    # commit — the route owns the outer commit. For dry_run the savepoint was
    # rolled back, so committing here is a no-op on write state.
    db.commit()
    return ImportResponse(
        created=result.created,
        updated=result.updated,
        skipped=result.skipped,
        warnings=result.warnings,
        dry_run=req.dry_run,
    )
