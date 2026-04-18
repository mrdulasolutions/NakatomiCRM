"""Durable webhook delivery.

Each CRM event inserts a ``WebhookDelivery`` row with ``status="pending"``. A
background worker loop picks up pending rows whose ``next_attempt_at`` has
passed, attempts delivery, and either marks them ``succeeded`` (on any 2xx) or
schedules the next retry. After ``WEBHOOK_MAX_RETRIES`` attempts the row is
marked ``dead`` and stops being retried.

The worker lives in-process. It starts in FastAPI's ``lifespan`` context and
stops when the app shuts down. Running multiple app processes is fine — the
``SELECT ... FOR UPDATE SKIP LOCKED`` claim prevents two workers from picking
the same row.
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import db_session
from app.models import Webhook, WebhookDelivery
from app.security import hmac_sign

log = logging.getLogger("nakatomi.webhooks")

# Backoff schedule per retry attempt (seconds). Index = attempt number.
# attempt=1 → 2s, 2 → 8s, 3 → 30s, ... Keeps the worker draining fast when a
# target recovers while still backing off the truly broken ones.
_BACKOFF_SECONDS = [2, 8, 30, 120, 300]


def enqueue(db: Session, *, workspace_id: str, webhook_id: str, event_type: str, payload: dict) -> None:
    """Insert a pending delivery row. Safe to call from any request handler."""
    db.add(
        WebhookDelivery(
            workspace_id=workspace_id,
            webhook_id=webhook_id,
            event_type=event_type,
            payload=payload,
            status="pending",
            next_attempt_at=datetime.now(UTC),
        )
    )


def _next_backoff(attempts: int) -> timedelta:
    idx = min(attempts - 1, len(_BACKOFF_SECONDS) - 1)
    return timedelta(seconds=_BACKOFF_SECONDS[idx])


def _deliver_one(delivery: WebhookDelivery, hook: Webhook) -> tuple[bool, int | None, str | None, str | None]:
    """Pure HTTP — no DB writes. Returns (succeeded, status_code, response_body, error)."""
    body = json.dumps(delivery.payload, sort_keys=True, separators=(",", ":")).encode()
    signature = hmac_sign(hook.secret, body)
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Nakatomi-Webhooks/1.0",
        "X-Nakatomi-Event": delivery.event_type,
        "X-Nakatomi-Signature": f"sha256={signature}",
        "X-Nakatomi-Delivery-Id": str(delivery.id),
        "X-Nakatomi-Delivery-Timestamp": datetime.now(UTC).isoformat(),
    }
    try:
        with httpx.Client(timeout=settings.WEBHOOK_TIMEOUT_SECONDS) as client:
            r = client.post(hook.url, content=body, headers=headers)
        ok = 200 <= r.status_code < 300
        return ok, r.status_code, r.text[:4000], None if ok else f"http {r.status_code}"
    except Exception as e:  # noqa: BLE001
        return False, None, None, str(e)[:4000]


def process_pending_deliveries(limit: int = 20) -> int:
    """Attempt at most ``limit`` pending deliveries. Returns the number processed."""
    now = datetime.now(UTC)
    processed = 0
    with db_session() as db:
        # Claim a batch. SKIP LOCKED means concurrent workers don't block each other.
        rows = db.scalars(
            select(WebhookDelivery)
            .where(
                WebhookDelivery.status == "pending",
                WebhookDelivery.next_attempt_at <= now,
            )
            .order_by(WebhookDelivery.next_attempt_at.asc())
            .limit(limit)
            .with_for_update(skip_locked=True)
        ).all()
        for delivery in rows:
            hook = db.get(Webhook, delivery.webhook_id)
            if not hook or not hook.is_active:
                delivery.status = "dead"
                delivery.error = "webhook deleted or disabled"
                delivery.next_attempt_at = None
                processed += 1
                continue

            delivery.attempts += 1
            ok, status_code, response_body, error = _deliver_one(delivery, hook)
            delivery.status_code = status_code
            delivery.response_body = response_body
            delivery.error = error

            if ok:
                delivery.status = "succeeded"
                delivery.succeeded = True
                delivery.next_attempt_at = None
                hook.last_delivery_at = datetime.now(UTC)
                hook.failure_count = 0
                hook.last_error = None
            elif delivery.attempts >= settings.WEBHOOK_MAX_RETRIES:
                delivery.status = "dead"
                delivery.next_attempt_at = None
                hook.last_delivery_at = datetime.now(UTC)
                hook.failure_count += 1
                hook.last_error = error
            else:
                delivery.next_attempt_at = datetime.now(UTC) + _next_backoff(delivery.attempts)
                hook.failure_count += 1
                hook.last_error = error
            processed += 1
    return processed


# ---------------------------------------------------------------------------
# Background worker
# ---------------------------------------------------------------------------


_stop: threading.Event | None = None
_thread: threading.Thread | None = None


def _run_forever(stop: threading.Event) -> None:
    log.info("webhook worker started")
    while not stop.is_set():
        try:
            n = process_pending_deliveries(limit=20)
            if n == 0:
                stop.wait(timeout=5.0)
        except Exception:
            log.exception("webhook worker iteration failed")
            stop.wait(timeout=10.0)
    log.info("webhook worker stopped")


def start_worker() -> None:
    global _stop, _thread
    if _thread and _thread.is_alive():
        return
    _stop = threading.Event()
    _thread = threading.Thread(
        target=_run_forever, args=(_stop,), name="nakatomi-webhook-worker", daemon=True
    )
    _thread.start()


def stop_worker(timeout: float = 5.0) -> None:
    global _stop, _thread
    if _stop:
        _stop.set()
    if _thread:
        _thread.join(timeout=timeout)
    _stop = None
    _thread = None


# ---------------------------------------------------------------------------
# Backwards-compatible shim
# ---------------------------------------------------------------------------
# Old callers invoked this via BackgroundTasks. With the durable queue we no
# longer need it, but the symbol stays for any import we haven't found. It now
# just enqueues; the worker loop handles everything else.


def deliver_webhook(webhook_id: str, event_type: str, payload: dict) -> None:
    with db_session() as db:
        hook = db.get(Webhook, webhook_id)
        if not hook:
            return
        enqueue(
            db,
            workspace_id=hook.workspace_id,
            webhook_id=webhook_id,
            event_type=event_type,
            payload=payload,
        )
