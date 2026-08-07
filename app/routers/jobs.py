"""Async jobs API."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import Principal, enforce_resource_scope, get_principal
from app.models import Job, JobStatus
from app.services.jobs import create_job, enqueue

router = APIRouter(
    prefix="/jobs",
    tags=["jobs"],
    dependencies=[Depends(enforce_resource_scope("jobs"))],
)


class JobCreate(BaseModel):
    job_type: str = Field(description="ingest | export | merge | custom")
    input: dict = Field(default_factory=dict)
    run_async: bool = True


def _out(job: Job) -> dict:
    return {
        "id": job.id,
        "job_type": job.job_type,
        "status": job.status.value if hasattr(job.status, "value") else str(job.status),
        "progress": float(job.progress or 0),
        "input": job.input or {},
        "result": job.result or {},
        "error": job.error,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        "created_at": job.created_at.isoformat() if job.created_at else None,
    }


@router.get("")
def list_jobs(
    db: Session = Depends(get_db),
    p: Principal = Depends(get_principal),
    status: str | None = None,
    limit: int = Query(50, ge=1, le=200),
):
    q = select(Job).where(Job.workspace_id == p.workspace.id, Job.deleted_at.is_(None))
    if status:
        q = q.where(Job.status == status)
    q = q.order_by(Job.created_at.desc()).limit(limit)
    return [_out(j) for j in db.scalars(q).all()]


@router.post("", status_code=201)
def start_job(
    payload: JobCreate,
    db: Session = Depends(get_db),
    p: Principal = Depends(get_principal),
):
    if payload.job_type not in ("ingest", "export", "merge", "custom", "a2a_batch"):
        raise HTTPException(
            status_code=422,
            detail="job_type must be ingest|export|merge|custom|a2a_batch",
        )
    job = create_job(
        db,
        workspace_id=p.workspace.id,
        job_type=payload.job_type,
        input_data=payload.input,
        actor_user_id=p.user_id,
        actor_api_key_id=p.api_key_id,
    )
    if payload.run_async:
        enqueue(job.id)
    else:
        from app.services.jobs import _run_job

        _run_job(job.id)
        db.refresh(job)
    return _out(job)


@router.get("/{job_id}")
def get_job(job_id: str, db: Session = Depends(get_db), p: Principal = Depends(get_principal)):
    job = db.get(Job, job_id)
    if not job or job.workspace_id != p.workspace.id:
        raise HTTPException(status_code=404, detail="not found")
    return _out(job)


@router.post("/{job_id}/cancel")
def cancel_job(job_id: str, db: Session = Depends(get_db), p: Principal = Depends(get_principal)):
    job = db.get(Job, job_id)
    if not job or job.workspace_id != p.workspace.id:
        raise HTTPException(status_code=404, detail="not found")
    if job.status in (JobStatus.completed, JobStatus.failed, JobStatus.canceled):
        raise HTTPException(status_code=409, detail=f"already {job.status.value}")
    if job.status == JobStatus.running:
        raise HTTPException(status_code=409, detail="cannot cancel running job; wait for completion")
    job.status = JobStatus.canceled
    db.commit()
    db.refresh(job)
    return _out(job)
