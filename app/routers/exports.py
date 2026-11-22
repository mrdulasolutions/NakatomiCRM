from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Form, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import Principal, require_role_and_scopes
from app.models import MemberRole, Workspace
from app.schemas import ImportRequest, ImportResponse
from app.services.export import build_export
from app.services.export_archive import build_archive, validate_download_grant
from app.services.importer import apply_import

router = APIRouter(tags=["export-import"])


@router.get("/export")
def export_workspace(
    include_timeline: bool = False,
    db: Session = Depends(get_db),
    p: Principal = Depends(
        require_role_and_scopes(MemberRole.owner, MemberRole.admin, scopes=("export:read",))
    ),
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
    p: Principal = Depends(
        require_role_and_scopes(MemberRole.owner, MemberRole.admin, scopes=("export:write",))
    ),
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


_ARCHIVE_PAGE = """<!doctype html>
<html lang="en">
<meta charset="utf-8">
<title>Download Nakatomi workspace ZIP</title>
<h1>Download workspace ZIP</h1>
<p id="status" role="status"></p>
<form method="post" action="/export/archive/download">
  <input type="hidden" name="token" id="token">
  <button type="submit" id="download" disabled>Download ZIP</button>
</form>
<script>
  const token = location.hash.slice(1);
  if (token) {
    history.replaceState(null, "", location.pathname);
    document.getElementById("token").value = token;
    document.getElementById("download").disabled = false;
  } else {
    document.getElementById("status").textContent = "Ask your agent for a fresh download link.";
  }
</script>
</html>
"""


@router.get("/export/archive", response_class=HTMLResponse, include_in_schema=False)
def archive_landing() -> HTMLResponse:
    return HTMLResponse(
        _ARCHIVE_PAGE,
        headers={
            "Cache-Control": "no-store",
            "Referrer-Policy": "no-referrer",
            "X-Frame-Options": "DENY",
        },
    )


@router.post("/export/archive/download", include_in_schema=False)
def download_archive(token: str = Form(...), db: Session = Depends(get_db)) -> StreamingResponse:
    claims = validate_download_grant(db, token)
    if not claims:
        raise HTTPException(403, "This export link is invalid or expired. Ask your agent for a fresh link.")
    workspace = db.get(Workspace, claims["workspace"])
    if not workspace:
        raise HTTPException(404, "Workspace unavailable")
    try:
        archive = build_archive(
            db,
            workspace,
            target=claims["target"],
            include_files=claims["files"],
            include_timeline=claims["timeline"],
        )
    except (OSError, ValueError):
        raise HTTPException(409, "An attachment could not be exported. Try again without attachments.")
    filename = f"nakatomi-{workspace.id}-{datetime.now(UTC).date().isoformat()}.zip"

    def chunks():
        with archive:
            while chunk := archive.read(1024 * 1024):
                yield chunk

    return StreamingResponse(
        chunks(),
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "private, no-store",
            "Referrer-Policy": "no-referrer",
        },
    )
