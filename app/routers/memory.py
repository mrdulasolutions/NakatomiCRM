from __future__ import annotations

import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import Pagination, Principal, get_pagination, get_principal
from app.models import EntityType, MemoryLink
from app.schemas import (
    MemoryLinkIn,
    MemoryLinkOut,
    MemoryRecallIn,
    MemoryRecallItem,
    MemoryRecallOut,
    OkResponse,
    Page,
)
from app.services.events import emit
from app.services.memory import enabled_connectors, get_connector
from app.services.pagination import apply_cursor, encode_cursor

router = APIRouter(prefix="/memory", tags=["memory"])
log = logging.getLogger("nakatomi.memory")


@router.get("/connectors", response_model=list[str])
def list_connectors(_: Principal = Depends(get_principal)) -> list[str]:
    return list(enabled_connectors().keys())


@router.get("/links", response_model=Page[MemoryLinkOut])
def list_links(
    connector: str | None = Query(None, description="filter by connector name"),
    entity_type: EntityType | None = None,
    entity_id: str | None = None,
    db: Session = Depends(get_db),
    p: Principal = Depends(get_principal),
    page: Pagination = Depends(get_pagination),
) -> Page[MemoryLinkOut]:
    """List every cross-link between a CRM entity and an external memory in
    this workspace. Paginated via cursor. Filter by connector, entity type,
    or specific entity id for drill-down.

    For a focused view of one entity, prefer ``GET /memory/trace/{type}/{id}``
    — same data, one hop.
    """
    q = select(MemoryLink).where(MemoryLink.workspace_id == p.workspace.id)
    if connector:
        q = q.where(MemoryLink.connector == connector)
    if entity_type:
        q = q.where(MemoryLink.crm_entity_type == entity_type)
    if entity_id:
        q = q.where(MemoryLink.crm_entity_id == entity_id)

    total = db.scalar(select(func.count()).select_from(q.subquery())) or 0
    q = apply_cursor(q, model=MemoryLink, cursor=page.cursor)
    q = q.order_by(MemoryLink.created_at.desc(), MemoryLink.id.desc()).limit(page.limit + 1)
    rows = db.scalars(q).all()
    next_cursor = None
    if len(rows) > page.limit:
        last = rows[page.limit - 1]
        next_cursor = encode_cursor(last.created_at, last.id)
        rows = rows[: page.limit]
    return Page[MemoryLinkOut](
        items=[MemoryLinkOut.model_validate(r) for r in rows],
        next_cursor=next_cursor,
        count=total,
    )


@router.post("/recall", response_model=MemoryRecallOut)
def recall(
    req: MemoryRecallIn,
    db: Session = Depends(get_db),
    p: Principal = Depends(get_principal),
) -> MemoryRecallOut:
    targets = req.connectors or list(enabled_connectors().keys())
    items: list[MemoryRecallItem] = []
    for name in targets:
        connector = get_connector(name)
        if not connector:
            continue
        try:
            got = connector.recall(
                workspace_id=p.workspace.id,
                query=req.query,
                crm_entity_type=req.entity_type.value if req.entity_type else None,
                crm_entity_id=req.entity_id,
                limit=req.limit,
            )
        except Exception as e:  # noqa: BLE001
            log.warning("recall on '%s' failed: %s", name, e)
            continue
        for m in got:
            links = db.scalars(
                select(MemoryLink).where(
                    MemoryLink.workspace_id == p.workspace.id,
                    MemoryLink.connector == name,
                    MemoryLink.external_id == m.external_id,
                )
            ).all()
            items.append(
                MemoryRecallItem(
                    connector=m.connector,
                    external_id=m.external_id,
                    text=m.text,
                    score=m.score,
                    metadata=m.metadata,
                    crm_links=[
                        f"{link.crm_entity_type.value if hasattr(link.crm_entity_type, 'value') else link.crm_entity_type}:{link.crm_entity_id}"
                        for link in links
                    ],
                )
            )
    items.sort(key=lambda x: x.score, reverse=True)
    return MemoryRecallOut(items=items[: req.limit])


@router.post("/link", response_model=MemoryLinkOut, status_code=201)
def create_link(
    req: MemoryLinkIn,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    p: Principal = Depends(get_principal),
) -> MemoryLinkOut:
    link = MemoryLink(
        workspace_id=p.workspace.id,
        connector=req.connector,
        external_id=req.external_id,
        crm_entity_type=req.crm_entity_type,
        crm_entity_id=req.crm_entity_id,
        note=req.note,
        data=req.data,
    )
    db.add(link)
    try:
        db.flush()
    except Exception:
        db.rollback()
        raise HTTPException(status_code=409, detail="link already exists")
    emit(
        db,
        p,
        event_type="memory.linked",
        entity_type=req.crm_entity_type,
        entity_id=req.crm_entity_id,
        payload={
            "connector": req.connector,
            "external_id": req.external_id,
        },
        background=background,
    )
    db.commit()
    db.refresh(link)
    return MemoryLinkOut.model_validate(link)


@router.delete("/link/{link_id}", response_model=OkResponse)
def delete_link(
    link_id: str,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    p: Principal = Depends(get_principal),
) -> OkResponse:
    link = db.get(MemoryLink, link_id)
    if not link or link.workspace_id != p.workspace.id:
        raise HTTPException(status_code=404, detail="not found")
    crm_et, crm_id, conn, ext = link.crm_entity_type, link.crm_entity_id, link.connector, link.external_id
    db.delete(link)
    emit(
        db,
        p,
        event_type="memory.unlinked",
        entity_type=crm_et,
        entity_id=crm_id,
        payload={"connector": conn, "external_id": ext},
        background=background,
    )
    db.commit()
    return OkResponse(message="unlinked")


@router.get("/trace/{entity_type}/{entity_id}", response_model=list[MemoryLinkOut])
def trace(
    entity_type: EntityType,
    entity_id: str,
    db: Session = Depends(get_db),
    p: Principal = Depends(get_principal),
):
    rows = db.scalars(
        select(MemoryLink).where(
            MemoryLink.workspace_id == p.workspace.id,
            MemoryLink.crm_entity_type == entity_type,
            MemoryLink.crm_entity_id == entity_id,
        )
    ).all()
    return [MemoryLinkOut.model_validate(r) for r in rows]


@router.post("/webhook/{connector}", response_model=OkResponse)
async def inbound_webhook(
    connector: str,
    request: Request,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    p: Principal = Depends(get_principal),
) -> OkResponse:
    adapter = get_connector(connector)
    if not adapter:
        raise HTTPException(status_code=404, detail=f"connector '{connector}' not enabled")
    body = await request.body()
    headers = {k.lower(): v for k, v in request.headers.items()}
    if not adapter.verify_webhook(headers, body):
        raise HTTPException(status_code=401, detail="webhook signature failed")
    try:
        parsed = adapter.parse_webhook(headers, await request.json())
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"could not parse: {e}")

    for item in parsed:
        ext_id = item.get("external_id") or ""
        for ref in item.get("crm_refs") or []:
            et = ref.get("type")
            eid = ref.get("id")
            if not (et and eid):
                continue
            try:
                link_et = EntityType(et)
            except ValueError:
                continue
            exists = db.scalar(
                select(MemoryLink).where(
                    MemoryLink.workspace_id == p.workspace.id,
                    MemoryLink.connector == connector,
                    MemoryLink.external_id == ext_id,
                    MemoryLink.crm_entity_type == link_et,
                    MemoryLink.crm_entity_id == eid,
                )
            )
            if exists:
                continue
            db.add(
                MemoryLink(
                    workspace_id=p.workspace.id,
                    connector=connector,
                    external_id=ext_id,
                    crm_entity_type=link_et,
                    crm_entity_id=eid,
                    note="via inbound webhook",
                    data={"text": item.get("text", "")[:2000]},
                )
            )
            emit(
                db,
                p,
                event_type="memory.linked",
                entity_type=link_et,
                entity_id=eid,
                payload={"connector": connector, "external_id": ext_id},
                background=background,
            )
    db.commit()
    return OkResponse(message="ingested")
