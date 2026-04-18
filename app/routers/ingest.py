from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import Principal, get_principal
from app.models import IngestRun
from app.schemas import IngestDiagnostic, IngestIn, IngestOut
from app.services.events import emit
from app.services.ingest import adapters  # noqa: F401  — registers adapters
from app.services.ingest.base import run_ingest

router = APIRouter(prefix="/ingest", tags=["ingest"])


@router.post("", response_model=IngestOut)
def ingest(
    req: IngestIn,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    p: Principal = Depends(get_principal),
) -> IngestOut:
    result = run_ingest(
        db,
        p,
        fmt=req.format.lower(),
        payload=req.payload,
        mapping=req.mapping,
        dry_run=req.dry_run,
    )
    run = IngestRun(
        workspace_id=p.workspace.id,
        source=req.source,
        format=req.format,
        actor_user_id=p.user_id,
        actor_api_key_id=p.api_key_id,
        record_count=result.record_count,
        created_count=len(result.created_ids),
        updated_count=len(result.updated_ids),
        error_count=result.error_count,
        diagnostics={"items": result.diagnostics},
    )
    db.add(run)
    db.flush()

    # Emit ingest.completed once per run.
    emit(
        db,
        p,
        event_type="ingest.completed",
        entity_type="file",  # ingest doesn't attach to one entity; file is the closest generic bucket
        entity_id=run.id,
        payload={
            "source": req.source,
            "format": req.format,
            "record_count": result.record_count,
            "created": len(result.created_ids),
            "updated": len(result.updated_ids),
            "errors": result.error_count,
        },
        background=background,
    )

    if not req.dry_run:
        db.commit()
    else:
        db.rollback()

    return IngestOut(
        run_id=run.id,
        record_count=result.record_count,
        created=len(result.created_ids),
        updated=len(result.updated_ids),
        errors=result.error_count,
        created_ids=result.created_ids,
        updated_ids=result.updated_ids,
        diagnostics=[IngestDiagnostic(**d) for d in result.diagnostics],
    )
