"""Auth/bootstrap in-process rate limit middleware."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.middleware_auth_limit import _buckets


def test_auth_rate_limit_returns_429(client: TestClient, monkeypatch):
    monkeypatch.setattr("app.config.settings.AUTH_RATE_LIMIT_PER_MINUTE", 2)
    _buckets.clear()
    for _ in range(2):
        r = client.post("/auth/login", json={"email": "nobody@example.com", "password": "wrong-password"})
        assert r.status_code == 401
    r = client.post("/auth/login", json={"email": "nobody@example.com", "password": "wrong-password"})
    assert r.status_code == 429
    assert "Retry-After" in r.headers


def test_auth_rate_limit_disabled_by_default(client: TestClient, monkeypatch):
    monkeypatch.setattr("app.config.settings.AUTH_RATE_LIMIT_PER_MINUTE", 0)
    _buckets.clear()
    for _ in range(5):
        r = client.post("/auth/login", json={"email": "nobody@example.com", "password": "wrong-password"})
        assert r.status_code == 401
