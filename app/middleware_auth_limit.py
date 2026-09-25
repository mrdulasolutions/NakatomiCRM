"""In-process rate limits for unauthenticated auth and bootstrap endpoints."""

from __future__ import annotations

import time
from threading import Lock

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp

from app.config import settings

_LIMIT_PATHS = frozenset(
    {
        "/auth/login",
        "/auth/signup",
        "/bootstrap",
        "/welcome/signup",
    }
)

_buckets: dict[str, tuple[float, int]] = {}
_lock = Lock()


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "").strip()
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "unknown"


def _check_auth_rate_limit(ip: str, limit: int) -> tuple[bool, int]:
    """Return (allowed, retry_after_seconds)."""
    now = time.monotonic()
    with _lock:
        window_start, count = _buckets.get(ip, (now, 0))
        if now - window_start >= 60.0:
            window_start, count = now, 0
        count += 1
        _buckets[ip] = (window_start, count)
        if count > limit:
            remaining = max(1, int(60.0 - (now - window_start)))
            return False, remaining
    return True, 0


class AuthRateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next):
        limit = settings.AUTH_RATE_LIMIT_PER_MINUTE
        if limit <= 0 or request.method.upper() != "POST":
            return await call_next(request)

        path = request.url.path.rstrip("/") or "/"
        if path not in _LIMIT_PATHS:
            return await call_next(request)

        allowed, retry_after = _check_auth_rate_limit(_client_ip(request), limit)
        if not allowed:
            return JSONResponse(
                status_code=429,
                content={"detail": f"rate limit exceeded ({limit}/min); try again shortly"},
                headers={"Retry-After": str(retry_after)},
            )
        return await call_next(request)
