from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import Pagination, Principal, get_pagination, get_principal
from app.models import EntityType, Relationship
from app.schemas import OkResponse, Page, RelationshipIn, RelationshipOut
from app.services.events import emit
from app.services.pagination import apply_cursor, encode_cursor

router = APIRouter(prefix="/relationships", tags=["relationships"])


@router.get("", response_model=Page[RelationshipOut])
def list_relationships(
    db: Session = Depends(get_db),
    p: Principal = Depends(get_principal),
    page: Pagination = Depends(get_pagination),
    entity_type: EntityType | None = Query(None, description="filter edges touching this entity"),
    entity_id: str | None = None,
    relation_type: str | None = None,
    direction: str = Query("both", pattern=r"^(out|in|both)$"),
):
    query = select(Relationship).where(Relationship.workspace_id == p.workspace.id)
    if relation_type:
        query = query.where(Relationship.relation_type == relation_type)
    if entity_type and entity_id:
        if direction == "out":
            query = query.where(Relationship.source_type == entity_type, Relationship.source_id == entity_id)
        elif direction == "in":
            query = query.where(Relationship.target_type == entity_type, Relationship.target_id == entity_id)
        else:
            query = query.where(
                or_(
                    (Relationship.source_type == entity_type) & (Relationship.source_id == entity_id),
                    (Relationship.target_type == entity_type) & (Relationship.target_id == entity_id),
                )
            )
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    query = apply_cursor(query, model=Relationship, cursor=page.cursor)
    query = query.order_by(Relationship.created_at.desc(), Relationship.id.desc()).limit(page.limit + 1)
    rows = db.scalars(query).all()
    next_cursor = None
    if len(rows) > page.limit:
        last = rows[page.limit - 1]
        next_cursor = encode_cursor(last.created_at, last.id)
        rows = rows[: page.limit]
    return Page[RelationshipOut](
        items=[RelationshipOut.model_validate(r) for r in rows],
        next_cursor=next_cursor,
        count=total,
    )


@router.post("", response_model=RelationshipOut, status_code=201)
def create_relationship(
    payload: RelationshipIn,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    p: Principal = Depends(get_principal),
) -> RelationshipOut:
    r = Relationship(workspace_id=p.workspace.id, **payload.model_dump())
    db.add(r)
    try:
        db.flush()
    except Exception:
        db.rollback()
        raise HTTPException(status_code=409, detail="edge already exists")
    emit(
        db,
        p,
        event_type="relationship.created",
        entity_type=payload.source_type,
        entity_id=payload.source_id,
        payload={
            "target_type": payload.target_type.value,
            "target_id": payload.target_id,
            "relation_type": payload.relation_type,
        },
        background=background,
    )
    db.commit()
    db.refresh(r)
    return RelationshipOut.model_validate(r)


@router.delete("/{relationship_id}", response_model=OkResponse)
def delete_relationship(
    relationship_id: str,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    p: Principal = Depends(get_principal),
) -> OkResponse:
    r = db.get(Relationship, relationship_id)
    if not r or r.workspace_id != p.workspace.id:
        raise HTTPException(status_code=404, detail="not found")
    src_type, src_id, rtype = r.source_type, r.source_id, r.relation_type
    db.delete(r)
    emit(
        db,
        p,
        event_type="relationship.deleted",
        entity_type=src_type,
        entity_id=src_id,
        payload={"relation_type": rtype},
        background=background,
    )
    db.commit()
    return OkResponse(message="deleted")


@router.get("/neighbors", response_model=list[RelationshipOut])
def neighbors(
    entity_type: EntityType,
    entity_id: str,
    relation_type: str | None = None,
    depth: int = Query(1, ge=1, le=2),
    db: Session = Depends(get_db),
    p: Principal = Depends(get_principal),
):
    """BFS up to ``depth`` hops from (entity_type, entity_id). Returns the edges visited."""
    seen_edges: dict[str, Relationship] = {}
    frontier: set[tuple[EntityType, str]] = {(entity_type, entity_id)}
    for _ in range(depth):
        if not frontier:
            break
        next_frontier: set[tuple[EntityType, str]] = set()
        conds = []
        for et, eid in frontier:
            conds.append((Relationship.source_type == et) & (Relationship.source_id == eid))
            conds.append((Relationship.target_type == et) & (Relationship.target_id == eid))
        q = select(Relationship).where(Relationship.workspace_id == p.workspace.id, or_(*conds))
        if relation_type:
            q = q.where(Relationship.relation_type == relation_type)
        for edge in db.scalars(q).all():
            if edge.id in seen_edges:
                continue
            seen_edges[edge.id] = edge
            next_frontier.add((edge.source_type, edge.source_id))
            next_frontier.add((edge.target_type, edge.target_id))
        frontier = next_frontier - {(entity_type, entity_id)}
    return [RelationshipOut.model_validate(e) for e in seen_edges.values()]
