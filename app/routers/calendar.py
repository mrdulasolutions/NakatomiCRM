"""Calendar feed config + manual sync.

Each workspace can attach any number of iCal (.ics) feed URLs — typical
shape is one per source calendar. The poller hits each ``is_active``
feed on the global interval; ``POST /calendar/feeds/{id}/sync`` runs an
on-demand sync for one feed (useful for testing and for "I just added a
new event, refresh now" flows).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import Principal, get_principal, require_role
from app.models import CalendarFeed, MemberRole
from app.schemas import (
    CalendarFeedIn,
    CalendarFeedOut,
    CalendarFeedPatch,
    OkResponse,
)
from app.services.calendar_io import sync_feed

router = APIRouter(prefix="/calendar", tags=["calendar"])


@router.get("/feeds", response_model=list[CalendarFeedOut])
def list_feeds(db: Session = Depends(get_db), p: Principal = Depends(get_principal)) -> list[CalendarFeedOut]:
    rows = db.scalars(
        select(CalendarFeed).where(CalendarFeed.workspace_id == p.workspace.id)
    ).all()
    return [CalendarFeedOut.model_validate(r) for r in rows]


@router.post("/feeds", response_model=CalendarFeedOut, status_code=201)
def create_feed(
    payload: CalendarFeedIn,
    db: Session = Depends(get_db),
    p: Principal = Depends(require_role(MemberRole.owner, MemberRole.admin)),
) -> CalendarFeedOut:
    feed = CalendarFeed(workspace_id=p.workspace.id, **payload.model_dump())
    db.add(feed)
    db.commit()
    db.refresh(feed)
    return CalendarFeedOut.model_validate(feed)


@router.get("/feeds/{feed_id}", response_model=CalendarFeedOut)
def get_feed(feed_id: str, db: Session = Depends(get_db), p: Principal = Depends(get_principal)) -> CalendarFeedOut:
    feed = db.get(CalendarFeed, feed_id)
    if not feed or feed.workspace_id != p.workspace.id:
        raise HTTPException(status_code=404, detail="not found")
    return CalendarFeedOut.model_validate(feed)


@router.patch("/feeds/{feed_id}", response_model=CalendarFeedOut)
def patch_feed(
    feed_id: str,
    payload: CalendarFeedPatch,
    db: Session = Depends(get_db),
    p: Principal = Depends(require_role(MemberRole.owner, MemberRole.admin)),
) -> CalendarFeedOut:
    feed = db.get(CalendarFeed, feed_id)
    if not feed or feed.workspace_id != p.workspace.id:
        raise HTTPException(status_code=404, detail="not found")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(feed, k, v)
    db.commit()
    db.refresh(feed)
    return CalendarFeedOut.model_validate(feed)


@router.delete("/feeds/{feed_id}", response_model=OkResponse)
def delete_feed(
    feed_id: str,
    db: Session = Depends(get_db),
    p: Principal = Depends(require_role(MemberRole.owner, MemberRole.admin)),
) -> OkResponse:
    feed = db.get(CalendarFeed, feed_id)
    if not feed or feed.workspace_id != p.workspace.id:
        raise HTTPException(status_code=404, detail="not found")
    db.delete(feed)
    db.commit()
    return OkResponse(message="deleted")


@router.post("/feeds/{feed_id}/sync")
def sync_now(
    feed_id: str,
    db: Session = Depends(get_db),
    p: Principal = Depends(require_role(MemberRole.owner, MemberRole.admin, MemberRole.member)),
) -> dict:
    feed = db.get(CalendarFeed, feed_id)
    if not feed or feed.workspace_id != p.workspace.id:
        raise HTTPException(status_code=404, detail="not found")
    try:
        n = sync_feed(feed)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"sync failed: {exc}") from exc
    return {"feed_id": feed_id, "events_touched": n}
