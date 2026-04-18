from __future__ import annotations

import hashlib
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import Principal, get_principal
from app.models import EntityType, File
from app.schemas import FileOut, OkResponse
from app.services.events import emit
from app.services.storage import get_storage

router = APIRouter(prefix="/files", tags=["files"])

_CHUNK = 1 << 20  # 1 MB


@router.post("", response_model=FileOut, status_code=201)
async def upload_file(
    background: BackgroundTasks,
    upload: UploadFile,
    entity_type: EntityType | None = Form(None),
    entity_id: str | None = Form(None),
    db: Session = Depends(get_db),
    p: Principal = Depends(get_principal),
) -> FileOut:
    """Stream the upload to storage — never buffers the whole file in memory.

    Starlette's UploadFile wraps a SpooledTemporaryFile (spills to disk at
    ~1 MB). We read it once in chunks to compute SHA-256 and size, seek back
    to 0, and hand the underlying file object to storage.put() — which both
    LocalStorage and S3Storage consume as a streaming source.
    """
    sha = hashlib.sha256()
    size = 0
    while chunk := await upload.read(_CHUNK):
        sha.update(chunk)
        size += len(chunk)
    await upload.seek(0)

    key = f"{p.workspace.id}/{uuid.uuid4()}/{upload.filename or 'file'}"
    storage = get_storage()
    storage.put(key, upload.file, upload.content_type or "application/octet-stream")

    f = File(
        workspace_id=p.workspace.id,
        filename=upload.filename or "file",
        content_type=upload.content_type or "application/octet-stream",
        size_bytes=size,
        sha256=sha.hexdigest(),
        storage_key=key,
        entity_type=entity_type,
        entity_id=entity_id,
        uploaded_by_user_id=p.user_id,
    )
    db.add(f)
    db.flush()
    emit(
        db,
        p,
        event_type="file.uploaded",
        entity_type=EntityType.file,
        entity_id=f.id,
        payload={"filename": f.filename, "size": f.size_bytes},
        background=background,
    )
    db.commit()
    db.refresh(f)
    return FileOut.model_validate(f)


@router.get("", response_model=list[FileOut])
def list_files(
    db: Session = Depends(get_db),
    p: Principal = Depends(get_principal),
    entity_type: EntityType | None = None,
    entity_id: str | None = None,
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
    # Prefer a presigned URL when the backend offers one — the client hits
    # object storage directly and we don't relay the bytes.
    url = storage.presigned_url(f.storage_key)
    if url:
        return {"url": url, "expires_seconds": 900}
    # Otherwise stream the body. iter_chunks closes the stream when exhausted.
    return StreamingResponse(
        storage.iter_chunks(f.storage_key),
        media_type=f.content_type,
        headers={
            "Content-Disposition": f'attachment; filename="{f.filename}"',
            "Content-Length": str(f.size_bytes),
        },
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
    emit(
        db,
        p,
        event_type="file.deleted",
        entity_type=EntityType.file,
        entity_id=file_id,
        payload={"filename": f.filename},
        background=background,
    )
    db.commit()
    return OkResponse(message="deleted")
