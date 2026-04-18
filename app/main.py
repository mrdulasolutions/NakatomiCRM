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


# Tag metadata — shows up in /docs and /redoc as the section intros.
# Keep each description tight (one sentence) and link out to the wiki for depth.
_TAGS_METADATA = [
    {"name": "auth", "description": "Signup, login, and current-user introspection."},
    {"name": "workspace", "description": "Workspace settings, memberships, and API keys."},
    {
        "name": "contacts",
        "description": "People in the CRM. Supports bulk upsert, soft delete, fuzzy duplicate detection (`/duplicates`), and duplicate merge (`/merge`).",
    },
    {"name": "companies", "description": "Organizations in the CRM. Mirrors the contacts shape."},
    {"name": "pipelines", "description": "Sales pipelines and their stages."},
    {
        "name": "deals",
        "description": "Deals moving through a pipeline. Timeline captures every stage change.",
    },
    {"name": "activities", "description": "Calls, meetings, email logs, and other timestamped touchpoints."},
    {"name": "notes", "description": "Markdown notes attached to any entity."},
    {"name": "tasks", "description": "Assignable tasks with due dates."},
    {
        "name": "relationships",
        "description": "Typed directed edges between any two entities. BFS via `/neighbors`.",
    },
    {"name": "timeline", "description": "Append-only event stream per entity and per workspace."},
    {"name": "webhooks", "description": "HMAC-signed subscriptions + durable delivery queue."},
    {
        "name": "files",
        "description": "Chunked-streaming file upload/download with pluggable storage (`local` or S3).",
    },
    {
        "name": "memory",
        "description": "Cross-link CRM entities with external memory systems (DocDeploy, Supermemory, GBrain).",
    },
    {"name": "ingest", "description": "Normalize CSV, JSON, vCard, or text into CRM rows."},
    {
        "name": "custom-fields",
        "description": "Workspace-scoped named-field registry. Values live in each row's `data` JSONB.",
    },
    {
        "name": "export-import",
        "description": "Portable JSON round-trip. The spine of the user-owns-their-data ethos.",
    },
    {
        "name": "schema",
        "description": "Machine-readable entity + field + event manifest for agent discovery.",
    },
    {
        "name": "dashboard",
        "description": "Local audit UI. Off by default; enable with `DASHBOARD_ENABLED=true`.",
    },
]


app = FastAPI(
    title="Nakatomi CRM",
    description=(
        "A headless CRM designed for AI agents (Claude, ChatGPT, Perplexity, Cursor). "
        "No human UI to click through — every primitive is a REST endpoint and also "
        "available as an MCP tool at `/mcp`.\n\n"
        "**Agent ergonomics baked in:** bulk upsert, cursor pagination, idempotency "
        "keys, soft delete, relationship graph, durable webhooks, pluggable memory "
        "connectors, workspace export/import, fuzzy duplicate detection and merge.\n\n"
        "**Discovery:** `/schema` returns the full entity + event manifest; `/llms.txt` "
        "is the LLM-discoverable pointer file; `/.well-known/agent.json` is the A2A "
        "capability card."
    ),
    version=__version__,
    lifespan=_lifespan,
    contact={
        "name": "Matt Dula",
        "url": "https://github.com/mrdulasolutions/NakatomiCRM",
        "email": "matt@mrdula.solutions",
    },
    license_info={"name": "MIT", "url": "https://github.com/mrdulasolutions/NakatomiCRM/blob/main/LICENSE"},
    openapi_tags=_TAGS_METADATA,
)

origins = [o.strip() for o in settings.CORS_ORIGINS.split(",") if o.strip()] or ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


_STATUS_TITLES = {
    400: "Bad Request",
    401: "Unauthorized",
    403: "Forbidden",
    404: "Not Found",
    409: "Conflict",
    410: "Gone",
    422: "Unprocessable Entity",
    429: "Too Many Requests",
    500: "Internal Server Error",
    503: "Service Unavailable",
}


@app.exception_handler(StarletteHTTPException)
async def _http_error(request, exc: StarletteHTTPException):
    """Return an RFC 9457 Problem Details body. We also include the legacy
    ``error`` field for backward compatibility with pre-v0.2 clients — safe
    to remove once we cut v1.0.
    """
    detail = str(exc.detail)
    body = {
        "type": f"https://github.com/mrdulasolutions/NakatomiCRM/wiki/Troubleshooting#{exc.status_code}",
        "title": _STATUS_TITLES.get(exc.status_code, "Error"),
        "status": exc.status_code,
        "detail": detail,
        "instance": str(request.url.path),
        # legacy:
        "error": detail,
    }
    return JSONResponse(
        status_code=exc.status_code,
        content=body,
        headers=getattr(exc, "headers", None),
        media_type="application/problem+json",
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
