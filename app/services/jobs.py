"""Async job runner — in-process background for bulk work."""

from __future__ import annotations

import logging
import threading
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import Job, JobStatus

log = logging.getLogger("nakatomi.jobs")


def create_job(
    db: Session,
    *,
    workspace_id: str,
    job_type: str,
    input_data: dict,
    actor_user_id: str | None = None,
    actor_api_key_id: str | None = None,
) -> Job:
    job = Job(
        workspace_id=workspace_id,
        job_type=job_type,
        status=JobStatus.pending,
        input=input_data or {},
        actor_user_id=actor_user_id,
        actor_api_key_id=actor_api_key_id,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def enqueue(job_id: str) -> None:
    """Fire-and-forget thread to process the job."""
    t = threading.Thread(target=_run_job, args=(job_id,), daemon=True, name=f"job-{job_id[:8]}")
    t.start()


def _run_job(job_id: str) -> None:
    db = SessionLocal()
    try:
        job = db.get(Job, job_id)
        if not job:
            return
        job.status = JobStatus.running
        job.started_at = datetime.now(UTC)
        job.progress = 5
        db.commit()

        result = _dispatch(db, job)
        job = db.get(Job, job_id)
        if not job:
            return
        job.result = result or {}
        job.progress = 100
        job.status = JobStatus.completed
        job.completed_at = datetime.now(UTC)
        db.commit()
        log.info("job completed id=%s type=%s", job_id, job.job_type)
    except Exception as exc:  # noqa: BLE001
        log.exception("job failed id=%s", job_id)
        try:
            job = db.get(Job, job_id)
            if job:
                job.status = JobStatus.failed
                job.error = str(exc)
                job.completed_at = datetime.now(UTC)
                db.commit()
        except Exception:  # noqa: BLE001
            db.rollback()
    finally:
        db.close()


def _dispatch(db: Session, job: Job) -> dict[str, Any]:
    jt = job.job_type
    inp = job.input or {}

    if jt == "export":
        from app.models import Workspace
        from app.services.export import build_export

        ws = db.get(Workspace, job.workspace_id)
        if not ws:
            raise RuntimeError("workspace vanished")
        job.progress = 40
        db.commit()
        doc = build_export(db, ws, include_timeline=bool(inp.get("include_timeline")))
        # Don't store full dump in result if huge — store counts
        counts = {k: len(v) if isinstance(v, list) else 1 for k, v in (doc or {}).items() if k != "meta"}
        return {
            "export_keys": list((doc or {}).keys()),
            "counts": counts,
            "note": "use GET /export for full dump",
        }

    if jt == "ingest":
        from app.deps import Principal
        from app.models import ApiKey, User, Workspace
        from app.services.ingest.base import run_ingest

        job.progress = 20
        db.commit()
        ws = db.get(Workspace, job.workspace_id)
        if not ws:
            raise RuntimeError("workspace vanished")
        user = db.get(User, job.actor_user_id) if job.actor_user_id else None
        key = db.get(ApiKey, job.actor_api_key_id) if job.actor_api_key_id else None
        from app.models import MemberRole
        from app.scopes import normalize_scopes

        principal = Principal(
            user=user,
            api_key=key,
            workspace=ws,
            role=key.role if key else MemberRole.member,
            scopes=normalize_scopes(key.scopes if key else ["*"]),
        )
        out = run_ingest(
            db,
            principal,
            fmt=inp.get("format") or inp.get("fmt") or "json",
            payload=inp.get("payload"),
            mapping=inp.get("mapping"),
            dry_run=bool(inp.get("dry_run")),
        )
        if hasattr(out, "record_count"):
            return {
                "record_count": out.record_count,
                "created_ids": getattr(out, "created_ids", []),
                "updated_ids": getattr(out, "updated_ids", []),
                "error_count": out.error_count,
                "diagnostics": out.diagnostics,
            }
        if isinstance(out, dict):
            return out
        return {"result": str(out)}

    if jt == "merge":
        return {
            "note": "merge jobs expect winner_id/loser_id; use POST /contacts/merge or /companies/merge for sync",
            "input": inp,
        }

    if jt == "custom":
        return {"echo": inp, "note": "custom jobs are no-ops until a handler is registered"}

    raise RuntimeError(f"unknown job_type: {jt}")
