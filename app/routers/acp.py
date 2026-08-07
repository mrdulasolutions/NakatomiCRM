"""ACP — Agent Context Protocol endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import Principal, get_principal
from app.services.context_pack import build_context_pack

router = APIRouter(prefix="/acp", tags=["acp"])


@router.get("/context")
def get_context(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    p: Principal = Depends(get_principal),
    sections: str | None = Query(
        None,
        description="comma-separated: schema,custom_fields,pipelines,views,policies,open_work,event_types,mcp,a2a,memory_connectors,hints",
    ),
    if_none_match: str | None = Header(default=None, alias="If-None-Match"),
):
    """Return the workspace ACP context pack (scope-aware)."""
    sec_set = None
    if sections:
        sec_set = {s.strip() for s in sections.split(",") if s.strip()}
    pack = build_context_pack(db, p, sections=sec_set)
    etag = pack.get("etag") or ""
    # Clients may send ETag with or without quotes
    inm = (if_none_match or "").strip().strip('"')
    if inm and etag and inm == etag:
        return Response(status_code=304, headers={"ETag": f'"{etag}"'})
    response.headers["ETag"] = f'"{etag}"'
    response.headers["Cache-Control"] = "private, max-age=30"
    return pack
