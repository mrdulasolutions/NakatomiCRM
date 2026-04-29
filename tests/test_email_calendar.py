"""Email + calendar v0.3 contract tests.

Network calls (IMAP, SMTP, HTTP) are mocked. The point is to exercise
the data path — config CRUD, ICS parsing, attendee→contact matching —
without flapping CI on every Hostinger SSL cert renewal.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.services.calendar_io import parse_ics

# ---------------------------------------------------------------------------
# Calendar — pure parser
# ---------------------------------------------------------------------------

_SAMPLE_ICS = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Test//EN
BEGIN:VEVENT
UID:abc-123@example.com
DTSTAMP:20260420T120000Z
DTSTART:20260420T140000Z
DTEND:20260420T150000Z
SUMMARY:Discovery call with Sarah
LOCATION:Zoom
ORGANIZER;CN=Matt:mailto:matt@example.com
ATTENDEE;CN=Sarah Lee:mailto:sarah@acme.com
ATTENDEE;CN=Bob:mailto:bob@beta.com
DESCRIPTION:Quick chat\\,ndiscuss pricing
END:VEVENT
BEGIN:VEVENT
UID:no-end@example.com
DTSTART:20260421
SUMMARY:All-day kickoff
END:VEVENT
END:VCALENDAR
"""


def test_parse_ics_extracts_events():
    events = parse_ics(_SAMPLE_ICS)
    assert len(events) == 2
    e = events[0]
    assert e["uid"] == "abc-123@example.com"
    assert e["summary"] == "Discovery call with Sarah"
    assert e["location"] == "Zoom"
    assert e["organizer"] == "matt@example.com"
    assert "sarah@acme.com" in e["attendees"]
    assert "bob@beta.com" in e["attendees"]
    assert e["dtstart"].isoformat() == "2026-04-20T14:00:00+00:00"
    assert e["dtend"].isoformat() == "2026-04-20T15:00:00+00:00"


def test_parse_ics_handles_date_only():
    events = parse_ics(_SAMPLE_ICS)
    e = events[1]
    assert e["uid"] == "no-end@example.com"
    assert e["dtstart"].isoformat() == "2026-04-21T00:00:00+00:00"


# ---------------------------------------------------------------------------
# Calendar feed CRUD
# ---------------------------------------------------------------------------


def test_calendar_feed_crud(client, workspace):
    h = workspace["headers"]
    r = client.post(
        "/calendar/feeds",
        headers=h,
        json={"name": "Personal", "ics_url": "https://example.com/feed.ics"},
    )
    assert r.status_code == 201, r.text
    fid = r.json()["id"]

    r = client.get("/calendar/feeds", headers=h)
    assert r.status_code == 200
    assert any(f["id"] == fid for f in r.json())

    r = client.patch(f"/calendar/feeds/{fid}", headers=h, json={"is_active": False})
    assert r.status_code == 200
    assert r.json()["is_active"] is False

    r = client.delete(f"/calendar/feeds/{fid}", headers=h)
    assert r.status_code == 200


def test_calendar_sync_creates_meeting_activity(client, workspace, monkeypatch):
    """End-to-end sync via mocked HTTP — verifies events become activities
    and attendees match contacts by email."""
    h = workspace["headers"]
    # contact Sarah at acme.com — should match the attendee email
    client.post(
        "/contacts",
        headers=h,
        json={"first_name": "Sarah", "last_name": "Lee", "email": "sarah@acme.com"},
    )
    r = client.post(
        "/calendar/feeds",
        headers=h,
        json={"name": "Work", "ics_url": "https://example.com/feed.ics"},
    )
    feed_id = r.json()["id"]

    class _Resp:
        status_code = 200
        text = _SAMPLE_ICS
        headers = {"ETag": '"deadbeef"'}

    with patch("app.services.calendar_io.httpx.get", return_value=_Resp()):
        r = client.post(f"/calendar/feeds/{feed_id}/sync", headers=h)
    assert r.status_code == 200
    assert r.json()["events_touched"] == 2

    r = client.get("/activities", headers=h, params={"kind": "meeting"})
    assert r.status_code == 200
    items = r.json()["items"]
    subjects = [a["subject"] for a in items]
    assert "Discovery call with Sarah" in subjects

    sarah_meeting = next(a for a in items if a["subject"] == "Discovery call with Sarah")
    assert sarah_meeting["entity_type"] == "contact"
    assert "matched_contact_ids" in sarah_meeting["data"]
    assert len(sarah_meeting["data"]["matched_contact_ids"]) == 1


# ---------------------------------------------------------------------------
# Email — config CRUD + send (mocked SMTP)
# ---------------------------------------------------------------------------


def test_email_config_crud(client, workspace):
    h = workspace["headers"]
    r = client.get("/email/config", headers=h)
    assert r.status_code == 200
    assert r.json() is None

    r = client.put(
        "/email/config",
        headers=h,
        json={
            "imap_host": "imap.example.com",
            "imap_user": "me@example.com",
            "imap_password": "secret",
            "smtp_host": "smtp.example.com",
            "smtp_user": "me@example.com",
            "smtp_password": "secret",
            "from_address": "me@example.com",
        },
    )
    assert r.status_code == 200
    assert r.json()["imap_host"] == "imap.example.com"

    # PUT is idempotent — should update, not duplicate
    r = client.put(
        "/email/config",
        headers=h,
        json={
            "imap_host": "imap2.example.com",
            "smtp_host": "smtp.example.com",
            "smtp_user": "me@example.com",
            "smtp_password": "secret",
        },
    )
    assert r.json()["imap_host"] == "imap2.example.com"


def test_email_send_requires_smtp_config(client, workspace):
    h = workspace["headers"]
    r = client.post(
        "/email/send",
        headers=h,
        json={"to": ["a@example.com"], "subject": "Hi", "body": "yo"},
    )
    assert r.status_code == 400


def test_email_send_persists_activity(client, workspace, monkeypatch):
    h = workspace["headers"]
    client.put(
        "/email/config",
        headers=h,
        json={
            "smtp_host": "smtp.example.com",
            "smtp_user": "me@example.com",
            "smtp_password": "secret",
            "from_address": "me@example.com",
        },
    )
    with patch("app.services.email_io.send_email") as mock_send:
        r = client.post(
            "/email/send",
            headers=h,
            json={"to": ["x@example.com"], "subject": "Hi", "body": "yo"},
        )
    assert r.status_code == 200, r.text
    assert mock_send.called

    activity_id = r.json()["activity_id"]
    r = client.get("/activities", headers=h, params={"kind": "email_outbound"})
    assert any(a["id"] == activity_id for a in r.json()["items"])
