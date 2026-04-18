"""Durable webhook queue: enqueue, process, retry, mark dead."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from sqlalchemy import select

from app.db import SessionLocal
from app.models import Contact, EntityType, TimelineEvent, WebhookDelivery
from app.services import webhook_delivery


def _make_webhook(client, h, url: str = "https://example.invalid/hook") -> dict:
    r = client.post(
        "/webhooks",
        headers=h,
        json={"name": "test-hook", "url": url, "events": ["*"], "is_active": True},
    )
    assert r.status_code == 201, r.text
    return r.json()


class _FakeResponse:
    def __init__(self, status_code: int = 200, text: str = "ok"):
        self.status_code = status_code
        self.text = text


class _FakeClient:
    """Drop-in for ``httpx.Client(...).__enter__()`` returning a stubbed ``post``."""

    def __init__(self, response: _FakeResponse):
        self._response = response

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def post(self, *_args, **_kwargs):
        return self._response


def test_creating_a_contact_enqueues_pending_delivery(client, workspace):
    h = workspace["headers"]
    _make_webhook(client, h)

    r = client.post("/contacts", headers=h, json={"first_name": "Ada"})
    assert r.status_code == 201

    db = SessionLocal()
    try:
        rows = db.scalars(select(WebhookDelivery)).all()
        assert len(rows) == 1
        d = rows[0]
        assert d.status == "pending"
        assert d.attempts == 0
        assert d.event_type == "contact.created"
        assert d.next_attempt_at is not None
    finally:
        db.close()


def test_worker_marks_succeeded_on_2xx(client, workspace):
    h = workspace["headers"]
    _make_webhook(client, h)
    client.post("/contacts", headers=h, json={"first_name": "Ada"})

    with patch("app.services.webhook_delivery.httpx.Client") as mock_client:
        mock_client.return_value = _FakeClient(_FakeResponse(200, "ok"))
        n = webhook_delivery.process_pending_deliveries(limit=10)
    assert n == 1

    db = SessionLocal()
    try:
        d = db.scalars(select(WebhookDelivery)).one()
        assert d.status == "succeeded"
        assert d.succeeded is True
        assert d.attempts == 1
        assert d.next_attempt_at is None
        assert d.status_code == 200
    finally:
        db.close()


def test_worker_retries_on_failure_and_marks_dead_after_max(client, workspace):
    h = workspace["headers"]
    _make_webhook(client, h)
    client.post("/contacts", headers=h, json={"first_name": "Ada"})

    # First attempt: 500 → should stay pending with next_attempt_at in the future.
    with patch("app.services.webhook_delivery.httpx.Client") as mock_client:
        mock_client.return_value = _FakeClient(_FakeResponse(500, "boom"))
        webhook_delivery.process_pending_deliveries(limit=10)

    db = SessionLocal()
    try:
        d = db.scalars(select(WebhookDelivery)).one()
        assert d.status == "pending"
        assert d.attempts == 1
        assert d.next_attempt_at > datetime.now(UTC)
        # Force it due so the next process call picks it up.
        d.next_attempt_at = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()
    finally:
        db.close()

    # Drain it until it dies. WEBHOOK_MAX_RETRIES defaults to 3.
    for _ in range(5):
        db = SessionLocal()
        try:
            d = db.scalars(select(WebhookDelivery)).one()
            if d.status != "pending":
                break
            d.next_attempt_at = datetime.now(UTC) - timedelta(seconds=1)
            db.commit()
        finally:
            db.close()
        with patch("app.services.webhook_delivery.httpx.Client") as mock_client:
            mock_client.return_value = _FakeClient(_FakeResponse(500, "boom"))
            webhook_delivery.process_pending_deliveries(limit=10)

    db = SessionLocal()
    try:
        d = db.scalars(select(WebhookDelivery)).one()
        assert d.status == "dead"
        assert d.attempts >= 3
        assert d.next_attempt_at is None
        assert d.error is not None
    finally:
        db.close()


def test_worker_skips_disabled_webhook(client, workspace):
    h = workspace["headers"]
    hook = _make_webhook(client, h)
    client.post("/contacts", headers=h, json={"first_name": "Ada"})

    # Disable before the worker runs.
    r = client.patch(f"/webhooks/{hook['id']}", headers=h, json={"is_active": False})
    assert r.status_code == 200

    n = webhook_delivery.process_pending_deliveries(limit=10)
    assert n == 1

    db = SessionLocal()
    try:
        d = db.scalars(select(WebhookDelivery)).one()
        assert d.status == "dead"
        assert "disabled" in (d.error or "")
        # No HTTP call was made — the handler short-circuited.
        assert d.status_code is None
    finally:
        db.close()


def test_timeline_still_written_when_webhooks_absent(client, workspace):
    """Sanity: the old BackgroundTasks path would have dropped events silently
    if the worker thread died. With the durable queue, emit() writes the
    timeline synchronously before any delivery logic runs."""
    h = workspace["headers"]
    r = client.post("/contacts", headers=h, json={"first_name": "Ada"})
    contact_id = r.json()["id"]

    db = SessionLocal()
    try:
        events = db.scalars(
            select(TimelineEvent).where(
                TimelineEvent.entity_type == EntityType.contact,
                TimelineEvent.entity_id == contact_id,
            )
        ).all()
        assert any(e.event_type == "contact.created" for e in events)
        assert db.scalars(select(Contact).where(Contact.id == contact_id)).one()
    finally:
        db.close()
