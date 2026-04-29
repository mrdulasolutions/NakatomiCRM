"""Calendar I/O — iCal (.ics) feed polling.

Why iCal instead of Google/Microsoft Graph push subscriptions:

* Every modern calendar (Google, Microsoft, Fastmail, Hostinger, iCloud,
  Proton) exposes a private .ics URL. Polling that URL is universal —
  no provider OAuth, no per-user webhook bookkeeping.
* Pull is simpler than push for v0.3. Push gets us realtime, but we
  also need to handle channel renewal, signature verification, and
  per-provider quirks. v0.4.

Per-feed state:

* ``last_etag`` — short-circuits when the calendar provider returns
  ``304 Not Modified`` (Google does, Microsoft sometimes doesn't).
* ``seen_uids`` — JSON map of ``{ics_uid: activity_id}`` so we can
  *update* the existing Activity row when an event is edited rather
  than create a duplicate. Trade-off: the map grows unbounded over
  years; v0.4 will GC events older than the feed's ``DTSTART`` floor.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from datetime import UTC, datetime, timedelta
from typing import Iterable

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import SessionLocal
from app.models import Activity, CalendarFeed, Contact, EntityType, TimelineEvent

log = logging.getLogger("nakatomi.calendar")

_DT_RE = re.compile(r"^DT(START|END)(?:;[^:]*)?:(.+)$")
_EMAIL_PARAM_RE = re.compile(r"mailto:([^;\r\n>]+)", re.I)


# ---------------------------------------------------------------------------
# Tiny iCalendar parser
# ---------------------------------------------------------------------------


def _unfold(raw: str) -> Iterable[str]:
    """RFC 5545 line unfolding — continuation lines start with whitespace."""
    out = []
    for line in raw.splitlines():
        if line.startswith((" ", "\t")) and out:
            out[-1] += line[1:]
        else:
            out.append(line)
    return out


def _parse_dt(value: str) -> datetime | None:
    """Parse an iCal DTSTART/DTEND value. Handles UTC (Z), floating, and
    date-only forms. Date-only events become 00:00 UTC."""
    v = value.strip()
    try:
        if v.endswith("Z"):
            return datetime.strptime(v, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
        if "T" in v:
            return datetime.strptime(v, "%Y%m%dT%H%M%S").replace(tzinfo=UTC)
        return datetime.strptime(v, "%Y%m%d").replace(tzinfo=UTC)
    except ValueError:
        return None


def parse_ics(raw: str) -> list[dict]:
    """Pull events out of an .ics body. Returns a list of dicts with the
    fields we care about: uid, summary, dtstart, dtend, location, description,
    attendees (list of email strings), organizer."""
    events: list[dict] = []
    cur: dict | None = None
    for line in _unfold(raw):
        if line == "BEGIN:VEVENT":
            cur = {"attendees": []}
            continue
        if line == "END:VEVENT":
            if cur and cur.get("uid"):
                events.append(cur)
            cur = None
            continue
        if cur is None:
            continue

        if line.startswith("UID:"):
            cur["uid"] = line[4:].strip()
        elif line.startswith("SUMMARY:"):
            cur["summary"] = line[8:].strip()
        elif line.startswith("LOCATION:"):
            cur["location"] = line[9:].strip()
        elif line.startswith("DESCRIPTION:"):
            cur["description"] = line[12:].strip().replace("\\n", "\n").replace("\\,", ",")
        elif line.startswith("ORGANIZER"):
            if m := _EMAIL_PARAM_RE.search(line):
                cur["organizer"] = m.group(1).lower()
        elif line.startswith("ATTENDEE"):
            if m := _EMAIL_PARAM_RE.search(line):
                cur["attendees"].append(m.group(1).lower())
        elif m := _DT_RE.match(line):
            kind, val = m.group(1), m.group(2)
            dt = _parse_dt(val)
            if dt:
                cur[f"dt{kind.lower()}"] = dt
    return events


# ---------------------------------------------------------------------------
# Sync
# ---------------------------------------------------------------------------


def _match_contacts_for_attendees(db: Session, workspace_id: str, addrs: list[str]) -> list[str]:
    if not addrs:
        return []
    rows = db.scalars(
        select(Contact).where(
            Contact.workspace_id == workspace_id,
            Contact.deleted_at.is_(None),
            Contact.email.in_([a.lower() for a in addrs]),
        )
    ).all()
    return [c.id for c in rows]


def sync_feed(feed: CalendarFeed) -> int:
    """Fetch the .ics URL and reconcile its events to Activity rows. Returns
    the count of activities created or updated."""
    headers = {}
    if feed.last_etag:
        headers["If-None-Match"] = feed.last_etag
    try:
        r = httpx.get(feed.ics_url, headers=headers, timeout=20.0, follow_redirects=True)
    except Exception as exc:  # noqa: BLE001
        log.warning("calendar fetch failed feed=%s: %s", feed.id, exc)
        return 0
    if r.status_code == 304:
        return 0
    if r.status_code != 200:
        log.warning("calendar fetch feed=%s returned %s", feed.id, r.status_code)
        return 0

    events = parse_ics(r.text)
    new_etag = r.headers.get("ETag")
    touched = 0

    db = SessionLocal()
    try:
        feed_db = db.get(CalendarFeed, feed.id)
        if not feed_db:
            return 0
        seen = dict(feed_db.seen_uids or {})

        for ev in events:
            if not ev.get("uid"):
                continue
            uid = ev["uid"]
            external_id = f"ics:{feed_db.id}:{uid}"
            attendees = ev.get("attendees", [])
            primary_contact_ids = _match_contacts_for_attendees(db, feed_db.workspace_id, attendees)
            primary_contact_id = primary_contact_ids[0] if primary_contact_ids else None
            occurred_at = ev.get("dtstart") or datetime.now(UTC)
            data = {
                "ics_uid": uid,
                "feed_id": feed_db.id,
                "feed_name": feed_db.name,
                "location": ev.get("location"),
                "organizer": ev.get("organizer"),
                "attendees": attendees,
                "matched_contact_ids": primary_contact_ids,
                "dtstart": ev.get("dtstart").isoformat() if ev.get("dtstart") else None,
                "dtend": ev.get("dtend").isoformat() if ev.get("dtend") else None,
            }

            existing_id = seen.get(uid)
            existing = db.get(Activity, existing_id) if existing_id else None
            if existing is None:
                existing = db.scalar(
                    select(Activity).where(
                        Activity.workspace_id == feed_db.workspace_id,
                        Activity.external_id == external_id,
                    )
                )

            if existing is None:
                act = Activity(
                    workspace_id=feed_db.workspace_id,
                    external_id=external_id,
                    kind="meeting",
                    subject=(ev.get("summary") or "(no title)")[:500],
                    body=(ev.get("description") or "")[:50_000],
                    occurred_at=occurred_at,
                    entity_type=EntityType.contact if primary_contact_id else None,
                    entity_id=primary_contact_id,
                    data=data,
                )
                db.add(act)
                db.flush()
                seen[uid] = act.id
                db.add(
                    TimelineEvent(
                        workspace_id=feed_db.workspace_id,
                        entity_type=EntityType.contact if primary_contact_id else EntityType.activity,
                        entity_id=primary_contact_id or act.id,
                        event_type="meeting.scheduled",
                        actor_user_id=None,
                        actor_api_key_id=None,
                        payload={"activity_id": act.id, "summary": ev.get("summary")},
                    )
                )
                touched += 1
            else:
                # Update — events get edited, attendees added, times shifted.
                existing.subject = (ev.get("summary") or existing.subject)[:500]
                existing.body = (ev.get("description") or existing.body or "")[:50_000]
                existing.occurred_at = occurred_at
                existing.data = data
                if primary_contact_id and not existing.entity_id:
                    existing.entity_type = EntityType.contact
                    existing.entity_id = primary_contact_id
                touched += 1

        feed_db.seen_uids = seen
        feed_db.last_polled_at = datetime.now(UTC)
        if new_etag:
            feed_db.last_etag = new_etag
        db.commit()
    finally:
        db.close()
    return touched


# ---------------------------------------------------------------------------
# Worker
# ---------------------------------------------------------------------------

_stop = threading.Event()
_thread: threading.Thread | None = None


def _worker_loop() -> None:
    interval = max(60, int(getattr(settings, "CALENDAR_POLL_INTERVAL_SECONDS", 600) or 600))
    log.info("calendar poller starting (interval=%ss)", interval)
    while not _stop.is_set():
        try:
            db = SessionLocal()
            try:
                feeds = db.scalars(select(CalendarFeed).where(CalendarFeed.is_active.is_(True))).all()
                feed_ids = [f.id for f in feeds]
            finally:
                db.close()
            for fid in feed_ids:
                if _stop.is_set():
                    break
                db = SessionLocal()
                try:
                    feed = db.get(CalendarFeed, fid)
                    if feed:
                        try:
                            n = sync_feed(feed)
                            if n:
                                log.info("calendar sync feed=%s touched=%s", feed.id, n)
                        except Exception as exc:  # noqa: BLE001
                            log.warning("calendar sync feed=%s failed: %s", feed.id, exc)
                finally:
                    db.close()
        except Exception as exc:  # noqa: BLE001
            log.warning("calendar poller iteration failed: %s", exc)
        for _ in range(interval):
            if _stop.is_set():
                break
            time.sleep(1)
    log.info("calendar poller stopped")


def start_worker() -> None:
    global _thread
    if _thread and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(target=_worker_loop, name="nakatomi-calendar-poller", daemon=True)
    _thread.start()


def stop_worker() -> None:
    _stop.set()
    if _thread is not None:
        _thread.join(timeout=5)
