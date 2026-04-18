from __future__ import annotations

import hashlib
import io
import uuid
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Form, HTTPException, UploadFile
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import Principal, get_principal
from app.models import EntityType, File
from app.schemas import FileOut, OkResponse
from app.services.events import emit
from app.services.storage import get_storage

router = APIRouter(prefix="/files", tags=["files"])


@router.post("", response_model=FileOut, status_code=201)
async def upload_file(
    background: BackgroundTasks,
    upload: UploadFile,
    entity_type: Optional[EntityType] = Form(None),
    entity_id: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    p: Principal = Depends(get_principal),
) -> FileOut:
    data = await upload.read()
    sha = hashlib.sha256(data).hexdigest()
    key = f"{p.workspace.id}/{uuid.uuid4()}/{upload.filename}"
    storage = get_storage()
    storage.put(key, io.BytesIO(data), upload.content_type or "application/octet-stream")
    f = File(
        workspace_id=p.workspace.id,
        filename=upload.filename or "file",
        content_type=upload.content_type or "application/octet-stream",
        size_bytes=len(data),
        sha256=sha,
        storage_key=key,
        entity_type=entity_type,
        entity_id=entity_id,
        uploaded_by_user_id=p.user_id,
    )
    db.add(f)
    db.flush()
    emit(db, p, event_type="file.uploaded", entity_type=EntityType.file,
         entity_id=f.id, payload={"filename": f.filename, "size": f.size_bytes},
         background=background)
    db.commit()
    db.refresh(f)
    return FileOut.model_validate(f)


@router.get("", response_model=list[FileOut])
def list_files(
    db: Session = Depends(get_db),
    p: Principal = Depends(get_principal),
    entity_type: Optional[EntityType] = None,
    entity_id: Optional[str] = None,
    limit: int = 100,
):
    q = select(File).where(File.workspace_id == p.workspace.id, File.deleted_at.is_(None))
    if entity_type:
        q = q.where(File.entity_type == entity_type)
    if entity_id:
        q = q.where(File.entity_id == entity_id)
    q = q.order_by(File.created_at.desc()).limit(min(limit, 500))
    return [FileOut.model_validate(r) for r in db.scalars(q).all()]


@router.get("/{file_id}")
def download_file(file_id: str, db: Session = Depends(get_db), p: Principal = Depends(get_principal)):
    f = db.get(File, file_id)
    if not f or f.workspace_id != p.workspace.id:
        raise HTTPException(status_code=404, detail="not found")
    storage = get_storage()
    # Prefer presigned URL when available, else stream bytes.
    url = storage.presigned_url(f.storage_key)
    if url:
        return {"url": url, "expires_seconds": 900}
    data = storage.get(f.storage_key)
    return Response(
        content=data,
        media_type=f.content_type,
        headers={"Content-Disposition": f'attachment; filename="{f.filename}"'},
    )


@router.delete("/{file_id}", response_model=OkResponse)
def delete_file(
    file_id: str,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    p: Principal = Depends(get_principal),
) -> OkResponse:
    f = db.get(File, file_id)
    if not f or f.workspace_id != p.workspace.id:
        raise HTTPException(status_code=404, detail="not found")
    storage = get_storage()
    storage.delete(f.storage_key)
    db.delete(f)
    emit(db, p, event_type="file.deleted", entity_type=EntityType.file,
         entity_id=file_id, payload={"filename": f.filename}, background=background)
    db.commit()
    return OkResponse(message="deleted")
