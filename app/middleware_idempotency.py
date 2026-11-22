"""Global Idempotency-Key middleware for mutating REST requests.

When a client sends ``Idempotency-Key`` with a workspace API key (``nk_…``),
we fingerprint method + path + body and either:

- replay a stored JSON response (``Idempotent-Replay: true``), or
- run the handler and persist the 2xx JSON body for future replays.

JWT-authenticated requests still work without keys; idempotency is best-effort
for agents which always use API keys.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable

from sqlalchemy import func, select
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.db import SessionLocal
from app.deps import check_idempotency, principal_idempotency_key, save_idempotency
from app.oauth_grants import bearer_key

log = logging.getLogger("nakatomi.idempotency")

_MUTATING = frozenset({"POST", "PUT", "PATCH", "DELETE"})
# Paths that must never be idempotency-cached (auth, oauth, static).
_SKIP_PREFIXES = (
    "/auth",
    "/oauth",
    "/mcp",
    "/health",
    "/docs",
    "/openapi",
    "/redoc",
    "/dashboard",
    "/welcome",
    "/bootstrap",
    "/llms.txt",
    "/nakatomi.txt",
    "/.well-known",
    "/workspace/api-keys",
    "/webhooks",
    "/export/archive",
    "/files",
)


def _skip(path: str) -> bool:
    if path in ("/",):
        return True
    return any(path == p or path.startswith(p + "/") or path.startswith(p) for p in _SKIP_PREFIXES)


class IdempotencyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if request.method not in _MUTATING or _skip(request.url.path):
            return await call_next(request)

        idem_key = request.headers.get("Idempotency-Key") or request.headers.get("idempotency-key")
        if not idem_key:
            return await call_next(request)

        auth = request.headers.get("authorization") or request.headers.get("Authorization") or ""
        if not auth.lower().startswith("bearer "):
            return await call_next(request)
        _, _, token = auth.partition(" ")
        token = token.strip()
        if not token.startswith("nk_"):
            return await call_next(request)

        body = await request.body()

        db = SessionLocal()
        try:
            resolved = bearer_key(db, token)
            if not resolved:
                return await call_next(request)
            key_row, role, scopes = resolved
            idem_key = principal_idempotency_key(key_row.id, role, scopes, idem_key)
            lock = db.scalar(select(func.pg_try_advisory_xact_lock(func.hashtextextended(idem_key, 0))))
            if not lock:
                return JSONResponse(
                    status_code=409, content={"detail": "Request with this key is in progress"}
                )
            path = str(request.url.path) + (f"?{request.url.query}" if request.url.query else "")

            try:
                existing = check_idempotency(
                    db,
                    key_row.workspace_id,
                    idem_key,
                    request.method,
                    path,
                    body,
                )
            except Exception as exc:  # noqa: BLE001 — HTTPException or dict detail
                from fastapi import HTTPException as FastAPIHTTPException

                if isinstance(exc, FastAPIHTTPException):
                    detail = exc.detail
                    if isinstance(detail, dict):
                        body_out = {**detail, "error": detail.get("error", str(detail))}
                    else:
                        body_out = {"error": str(detail), "detail": str(detail)}
                    return JSONResponse(status_code=exc.status_code, content=body_out)
                raise
            if existing is not None:
                return JSONResponse(
                    status_code=existing.status_code,
                    content=existing.response_body,
                    headers={"Idempotent-Replay": "true"},
                )

            response = await call_next(request)

            if not (200 <= response.status_code < 300):
                return response

            # Buffer body for JSON persistence.
            chunks: list[bytes] = []
            async for chunk in response.body_iterator:
                if isinstance(chunk, str):
                    chunks.append(chunk.encode())
                else:
                    chunks.append(chunk)
            raw = b"".join(chunks)
            content_type = response.headers.get("content-type", "")
            if "json" in content_type and raw:
                try:
                    parsed = json.loads(raw)
                    if isinstance(parsed, dict):
                        save_idempotency(
                            db,
                            key_row.workspace_id,
                            idem_key,
                            request.method,
                            path,
                            body,
                            response.status_code,
                            parsed,
                        )
                except Exception:  # noqa: BLE001
                    log.debug("idempotency: could not persist response", exc_info=True)

            headers = dict(response.headers)
            headers.pop("content-length", None)
            return Response(
                content=raw,
                status_code=response.status_code,
                headers=headers,
                media_type=response.media_type,
                background=response.background,
            )
        finally:
            db.close()
