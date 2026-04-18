from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import __version__
from app.config import settings
from app.routers import (
    activities,
    auth,
    companies,
    contacts,
    custom_fields,
    dashboard,
    deals,
    exports,
    files,
    ingest,
    memory,
    notes,
    pipelines,
    relationships,
    tasks,
    timeline,
    webhooks,
    workspaces,
)
from app.routers import (
    schema as schema_router,
)
from app.services import webhook_delivery

logging.basicConfig(
    level=settings.LOG_LEVEL,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("nakatomi")


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    """Start the durable webhook-delivery worker for the lifetime of the process.

    Tests disable the worker via ``WEBHOOK_WORKER_ENABLED=false`` so they can
    drive ``process_pending_deliveries()`` deterministically.
    """
    if settings.WEBHOOK_WORKER_ENABLED:
        webhook_delivery.start_worker()
    try:
        yield
    finally:
        webhook_delivery.stop_worker()


app = FastAPI(
    title="Nakatomi CRM",
    description="A headless CRM designed for AI agents (Claude, ChatGPT, Perplexity, ...).",
    version=__version__,
    lifespan=_lifespan,
)

origins = [o.strip() for o in settings.CORS_ORIGINS.split(",") if o.strip()] or ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(StarletteHTTPException)
async def _http_error(_, exc: StarletteHTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": str(exc.detail)},
        headers=getattr(exc, "headers", None),
    )


@app.get("/health")
def health() -> dict:
    return {"ok": True, "version": __version__}


# Agent-facing discovery files (llms.txt, .well-known/agent.json).
_REPO_ROOT = Path(__file__).resolve().parent.parent
_PUBLIC_DIR = _REPO_ROOT / "public"
_LLMS_TXT = _REPO_ROOT / "llms.txt"


@app.get("/llms.txt", response_class=PlainTextResponse, include_in_schema=False)
def llms_txt():
    if _LLMS_TXT.exists():
        return PlainTextResponse(_LLMS_TXT.read_text())
    return PlainTextResponse("Nakatomi — see /schema and /openapi.json")


if _PUBLIC_DIR.exists():
    app.mount("/.well-known", StaticFiles(directory=str(_PUBLIC_DIR / ".well-known")), name="well-known")


# REST routers
app.include_router(auth.router)
app.include_router(workspaces.router)
app.include_router(contacts.router)
app.include_router(companies.router)
app.include_router(pipelines.router)
app.include_router(deals.router)
app.include_router(activities.router)
app.include_router(notes.router)
app.include_router(tasks.router)
app.include_router(relationships.router)
app.include_router(timeline.router)
app.include_router(webhooks.router)
app.include_router(files.router)
app.include_router(memory.router)
app.include_router(ingest.router)
app.include_router(custom_fields.router)
app.include_router(exports.router)
app.include_router(schema_router.router)
app.include_router(dashboard.router)


# MCP server mounted at /mcp.
try:
    from app.mcp_server import build_asgi_app

    app.mount("/mcp", build_asgi_app())
    log.info("MCP server mounted at /mcp")
except Exception as exc:  # noqa: BLE001
    log.warning("MCP server failed to mount: %s", exc)


@app.get("/")
def root() -> dict:
    return {
        "name": "Nakatomi CRM",
        "version": __version__,
        "docs": "/docs",
        "schema": "/schema",
        "mcp": "/mcp",
        "health": "/health",
        "llms": "/llms.txt",
        "agent_card": "/.well-known/agent.json",
        "dashboard": "/dashboard" if settings.DASHBOARD_ENABLED else None,
    }
