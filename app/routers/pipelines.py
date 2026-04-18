from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import Principal, get_principal, require_role
from app.models import MemberRole, Pipeline, Stage
from app.schemas import OkResponse, PipelineIn, PipelineOut

router = APIRouter(prefix="/pipelines", tags=["pipelines"])


@router.get("", response_model=list[PipelineOut])
def list_pipelines(db: Session = Depends(get_db), p: Principal = Depends(get_principal)):
    rows = db.scalars(select(Pipeline).where(Pipeline.workspace_id == p.workspace.id)).all()
    return [PipelineOut.model_validate(r) for r in rows]


@router.post("", response_model=PipelineOut, status_code=201)
def create_pipeline(
    payload: PipelineIn,
    db: Session = Depends(get_db),
    p: Principal = Depends(require_role(MemberRole.owner, MemberRole.admin, MemberRole.member)),
) -> PipelineOut:
    pipe = Pipeline(
        workspace_id=p.workspace.id,
        name=payload.name,
        slug=payload.slug,
        is_default=payload.is_default,
        data=payload.data,
    )
    db.add(pipe)
    db.flush()
    for s in payload.stages:
        db.add(Stage(pipeline_id=pipe.id, **s.model_dump()))
    if payload.is_default:
        # clear other defaults
        others = db.scalars(
            select(Pipeline).where(Pipeline.workspace_id == p.workspace.id, Pipeline.id != pipe.id)
        ).all()
        for o in others:
            o.is_default = False
    db.commit()
    db.refresh(pipe)
    return PipelineOut.model_validate(pipe)


@router.get("/{pipeline_id}", response_model=PipelineOut)
def get_pipeline(pipeline_id: str, db: Session = Depends(get_db), p: Principal = Depends(get_principal)):
    pipe = db.get(Pipeline, pipeline_id)
    if not pipe or pipe.workspace_id != p.workspace.id:
        raise HTTPException(status_code=404, detail="not found")
    return PipelineOut.model_validate(pipe)


@router.delete("/{pipeline_id}", response_model=OkResponse)
def delete_pipeline(
    pipeline_id: str,
    db: Session = Depends(get_db),
    p: Principal = Depends(require_role(MemberRole.owner, MemberRole.admin)),
) -> OkResponse:
    pipe = db.get(Pipeline, pipeline_id)
    if not pipe or pipe.workspace_id != p.workspace.id:
        raise HTTPException(status_code=404, detail="not found")
    db.delete(pipe)
    db.commit()
    return OkResponse(message="deleted")
