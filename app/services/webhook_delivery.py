"""Background webhook delivery with HMAC signing and bounded retries."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone

import httpx

from app.config import settings
from app.db import db_session
from app.models import Webhook, WebhookDelivery
from app.security import hmac_sign

log = logging.getLogger(__name__)


def deliver_webhook(webhook_id: str, event_type: str, payload: dict) -> None:
    """Synchronous entrypoint used from BackgroundTasks; does its own retries inline."""
    asyncio.run(_deliver_async(webhook_id, event_type, payload))


async def _deliver_async(webhook_id: str, event_type: str, payload: dict) -> None:
    body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()

    with db_session() as db:
        hook = db.get(Webhook, webhook_id)
        if not hook or not hook.is_active:
            return
        url = hook.url
        secret = hook.secret
        workspace_id = hook.workspace_id

    signature = hmac_sign(secret, body)
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Nakatomi-Webhooks/1.0",
        "X-Nakatomi-Event": event_type,
        "X-Nakatomi-Signature": f"sha256={signature}",
        "X-Nakatomi-Delivery-Timestamp": datetime.now(timezone.utc).isoformat(),
    }

    attempts = 0
    status_code: int | None = None
    response_body: str | None = None
    error: str | None = None
    succeeded = False

    for attempt in range(1, settings.WEBHOOK_MAX_RETRIES + 1):
        attempts = attempt
        try:
            async with httpx.AsyncClient(timeout=settings.WEBHOOK_TIMEOUT_SECONDS) as client:
                r = await client.post(url, content=body, headers=headers)
            status_code = r.status_code
            response_body = r.text[:4000]
            if 200 <= r.status_code < 300:
                succeeded = True
                error = None
                break
            error = f"http {r.status_code}"
        except Exception as e:  # noqa: BLE001
            error = str(e)[:4000]
        await asyncio.sleep(min(2 ** attempt, 30))

    with db_session() as db:
        db.add(
            WebhookDelivery(
                workspace_id=workspace_id,
                webhook_id=webhook_id,
                event_type=event_type,
                payload=payload,
                status_code=status_code,
                response_body=response_body,
                error=error,
                attempts=attempts,
                succeeded=succeeded,
            )
        )
        hook = db.get(Webhook, webhook_id)
        if hook:
            hook.last_delivery_at = datetime.now(timezone.utc)
            if succeeded:
                hook.failure_count = 0
                hook.last_error = None
            else:
                hook.failure_count += 1
                hook.last_error = error
