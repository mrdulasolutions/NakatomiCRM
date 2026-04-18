"""Per-API-key rate limiting."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.db import SessionLocal
from app.models import ApiKey


def _set_key_limit(key_id: str, limit: int | None) -> None:
    db = SessionLocal()
    try:
        k = db.get(ApiKey, key_id)
        k.rate_limit_per_minute = limit
        k.usage_window_start = None
        k.usage_count = 0
        db.commit()
    finally:
        db.close()


def _api_key_id_for(workspace) -> str:
    db = SessionLocal()
    try:
        return db.scalars(select(ApiKey).where(ApiKey.workspace_id == workspace["workspace_id"])).one().id
    finally:
        db.close()


def test_disabled_by_default(client, workspace):
    """No rate_limit set on the key + global default is 0 → unlimited."""
    h = workspace["headers"]
    for _ in range(20):
        r = client.get("/contacts", headers=h)
        assert r.status_code == 200


def test_per_key_limit_blocks_when_exceeded(client, workspace):
    kid = _api_key_id_for(workspace)
    _set_key_limit(kid, 3)

    h = workspace["headers"]
    statuses = [client.get("/contacts", headers=h).status_code for _ in range(5)]
    # First 3 succeed, the rest return 429.
    assert statuses[:3] == [200, 200, 200]
    assert any(s == 429 for s in statuses[3:])

    # 429 response should carry a Retry-After header.
    r = client.get("/contacts", headers=h)
    assert r.status_code == 429
    assert "retry-after" in {k.lower() for k in r.headers}


def test_window_resets_after_60s(client, workspace):
    kid = _api_key_id_for(workspace)
    _set_key_limit(kid, 2)
    h = workspace["headers"]

    assert client.get("/contacts", headers=h).status_code == 200
    assert client.get("/contacts", headers=h).status_code == 200
    assert client.get("/contacts", headers=h).status_code == 429

    # Rewind the window to > 60s ago; next request should open a new window.
    db = SessionLocal()
    try:
        k = db.get(ApiKey, kid)
        k.usage_window_start = datetime.now(UTC) - timedelta(seconds=120)
        db.commit()
    finally:
        db.close()

    assert client.get("/contacts", headers=h).status_code == 200


def test_usage_count_tracked_even_when_disabled(client, workspace):
    """With no limit, last_used_at still bumps so operators can see activity."""
    h = workspace["headers"]
    client.get("/contacts", headers=h)
    db = SessionLocal()
    try:
        k = db.scalars(select(ApiKey).where(ApiKey.workspace_id == workspace["workspace_id"])).one()
        assert k.last_used_at is not None
    finally:
        db.close()


def test_create_api_key_honors_rate_limit_arg(client, workspace):
    # Create a new key with a per-key limit via the REST API.
    r = client.post(
        "/workspace/api-keys",
        headers=workspace["headers"],
        json={"name": "limited", "role": "member", "rate_limit_per_minute": 5},
    )
    assert r.status_code == 201, r.text
    assert r.json()["rate_limit_per_minute"] == 5
