from __future__ import annotations

import logging
import uuid
from contextlib import AsyncExitStack, asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import __version__
from app.config import settings
from app.routers import (
    a2a,
    acp,
    activities,
    approvals,
    auth,
    calendar,
    companies,
    contacts,
    custom_fields,
    custom_objects,
    dashboard,
    deals,
    discovery,
    email,
    exports,
    files,
    forecast,
    forensics,
    import_crm,
    ingest,
    jobs,
    leads,
    memory,
    notes,
    oauth,
    pipelines,
    policies,
    products,
    quotes,
    relationships,
    sso,
    tasks,
    timeline,
    views,
    webhooks,
    welcome,
    workspaces,
)
from app.routers import (
    schema as schema_router,
)
from app.services import calendar_io, email_io, webhook_delivery

logging.basicConfig(
    level=settings.LOG_LEVEL,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("nakatomi")


def _assert_production_secrets() -> None:
    """Refuse to boot production with a known-insecure SECRET_KEY."""
    if settings.ENVIRONMENT.lower() not in {"production", "prod"}:
        return
    bad = {
        "",
        "insecure-dev-key-change-me",
        "change-me-to-a-long-random-string",
        "dev-only-change-me-0123456789abcdef",
    }
    if settings.SECRET_KEY in bad or len(settings.SECRET_KEY) < 32:
        raise RuntimeError(
            "Refusing to start: ENVIRONMENT=production requires a strong SECRET_KEY "
            "(≥32 chars, not a documented default). See docs/DEPLOY.md."
        )


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    """Start the webhook-delivery worker AND the FastMCP session manager.

    FastMCP's streamable_http_app needs ``session_manager.run()`` active for
    the lifetime of the process — without it, incoming MCP requests crash
    with "Task group is not initialized". Mounting the ASGI app alone is
    not enough; the parent app has to enter its lifespan too.

    Tests disable the webhook worker via ``WEBHOOK_WORKER_ENABLED=false``
    so they can drive ``process_pending_deliveries()`` deterministically.
    """
    _assert_production_secrets()
    from app.otel import setup_otel, shutdown_otel

    setup_otel(app=_app)

    async with AsyncExitStack() as stack:
        try:
            from app.mcp_server import mcp as _mcp_server

            await stack.enter_async_context(_mcp_server.session_manager.run())
        except Exception as exc:  # noqa: BLE001
            log.warning("MCP session manager failed to start: %s", exc)

        if settings.WEBHOOK_WORKER_ENABLED:
            webhook_delivery.start_worker()
        if settings.EMAIL_POLLER_ENABLED:
            email_io.start_worker()
        if settings.CALENDAR_POLLER_ENABLED:
            calendar_io.start_worker()
        try:
            yield
        finally:
            calendar_io.stop_worker()
            email_io.stop_worker()
            webhook_delivery.stop_worker()
            shutdown_otel()


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
    {
        "name": "products",
        "description": "Workspace product catalog + per-deal line items. Line items snapshot catalog values so historical totals don't drift.",
    },
    {
        "name": "forecast",
        "description": "Period rollups of pipeline value (won, weighted, by stage, by owner). Calendar quarter, month, or custom range.",
    },
    {"name": "activities", "description": "Calls, meetings, email logs, and other timestamped touchpoints."},
    {
        "name": "email",
        "description": "Per-workspace IMAP/SMTP config + outbound send. Inbound poller (gated by `EMAIL_POLLER_ENABLED`) creates email-kind activities and matches sender by `From:` to existing contacts.",
    },
    {
        "name": "calendar",
        "description": "iCal feed subscriptions (Google, Microsoft, Fastmail, Hostinger, iCloud). Poller creates meeting activities and matches attendees to contacts by email.",
    },
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
    {
        "name": "approvals",
        "description": "Human-in-the-loop gates for agent-proposed actions (email.send, deal.won, custom).",
    },
    {
        "name": "a2a",
        "description": "Agent2Agent REST binding — peer tasks, messages, complete/fail/cancel, HITL input-required.",
    },
    {
        "name": "acp",
        "description": "Agent Context Protocol — versioned workspace context packs for agent session boot.",
    },
    {
        "name": "discovery",
        "description": "Unified agent discovery index linking REST, MCP, A2A, ACP, OAuth, OpenAPI.",
    },
    {"name": "leads", "description": "Inbound leads + convert to contact/company/deal."},
    {"name": "quotes", "description": "Versioned deal quotes with line-item snapshots."},
    {"name": "views", "description": "Saved filter views/segments agents can run by slug."},
    {"name": "jobs", "description": "Async bulk jobs (ingest, export, custom) with pollable status."},
    {
        "name": "policies",
        "description": "Declarative workspace policies (required fields, blocks, auto-tasks).",
    },
    {"name": "forensics", "description": "Audit search and entity time-travel as-of reconstruction."},
    {
        "name": "import",
        "description": "One-shot CRM importers (HubSpot, Salesforce, Pipedrive, Attio, generic).",
    },
    {"name": "custom-objects", "description": "Workspace-defined object types and records (moldable model)."},
    {
        "name": "sso",
        "description": "Optional Google/GitHub SSO for human operators (disabled unless client credentials set).",
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

from app.middleware_auth_limit import AuthRateLimitMiddleware  # noqa: E402
from app.middleware_idempotency import IdempotencyMiddleware  # noqa: E402

app.add_middleware(IdempotencyMiddleware)
app.add_middleware(AuthRateLimitMiddleware)


@app.middleware("http")
async def request_id_and_access_log(request: Request, call_next):
    """Attach X-Request-Id and emit a structured access log line."""
    import time

    rid = request.headers.get("X-Request-Id") or str(uuid.uuid4())
    request.state.request_id = rid
    started = time.perf_counter()
    response = await call_next(request)
    response.headers["X-Request-Id"] = rid
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    # Best-effort actor from bearer prefix (never log full secrets).
    actor = "-"
    auth = request.headers.get("authorization") or ""
    if auth.lower().startswith("bearer nk_"):
        parts = auth.split("_", 2)
        actor = f"nk_{parts[1]}" if len(parts) >= 2 else "nk_*"
    elif auth.lower().startswith("bearer "):
        actor = "jwt"
    log.info(
        "access method=%s path=%s status=%s ms=%s request_id=%s actor=%s",
        request.method,
        request.url.path,
        response.status_code,
        elapsed_ms,
        rid,
        actor,
    )
    return response


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
    502: "Bad Gateway",
    503: "Service Unavailable",
    202: "Accepted",
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
    """Liveness. Use ``?deep=true`` for a DB connectivity check."""
    from app.otel import status as otel_status
    from app.protocol import PROTOCOL_VERSIONS, STABILITY_TIER

    return {
        "ok": True,
        "version": __version__,
        "stability": STABILITY_TIER,
        "protocols": PROTOCOL_VERSIONS,
        "otel": otel_status(),
    }


@app.get("/health/deep")
def health_deep():
    """Readiness: ping Postgres. Returns 503 if the DB is unreachable."""
    from sqlalchemy import text

    from app.db import SessionLocal
    from app.otel import status as otel_status
    from app.protocol import PROTOCOL_VERSIONS, STABILITY_TIER

    base = {
        "version": __version__,
        "stability": STABILITY_TIER,
        "protocols": PROTOCOL_VERSIONS,
        "otel": otel_status(),
    }
    try:
        db = SessionLocal()
        try:
            db.execute(text("SELECT 1"))
        finally:
            db.close()
        return {"ok": True, "db": "up", **base}
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(
            status_code=503,
            content={"ok": False, "db": "down", "error": str(exc), **base},
        )


# Agent-facing discovery files (llms.txt, .well-known/agent.json).
_REPO_ROOT = Path(__file__).resolve().parent.parent
_PUBLIC_DIR = _REPO_ROOT / "public"
_LLMS_TXT = _REPO_ROOT / "llms.txt"


@app.get("/llms.txt", response_class=PlainTextResponse, include_in_schema=False)
def llms_txt():
    if _LLMS_TXT.exists():
        return PlainTextResponse(_LLMS_TXT.read_text())
    return PlainTextResponse("Nakatomi — see /schema and /openapi.json")


_NAKATOMI_TXT = _PUBLIC_DIR / "nakatomi.txt"


@app.get("/nakatomi.txt", response_class=PlainTextResponse, include_in_schema=False)
def nakatomi_txt():
    if _NAKATOMI_TXT.exists():
        return PlainTextResponse(_NAKATOMI_TXT.read_text())
    return PlainTextResponse("")


# OAuth routes MUST be registered before the /.well-known static mount below;
# the dynamic oauth-authorization-server + oauth-protected-resource metadata
# endpoints share that path prefix with the static agent.json.
app.include_router(oauth.router)


# Dynamic A2A agent cards (prefer these over static public/.well-known files).
@app.get("/.well-known/agent.json", include_in_schema=False)
@app.get("/.well-known/agent-card.json", include_in_schema=False)
def well_known_agent_card(request: Request):
    from app.services.agent_card import build_agent_card

    proto = request.headers.get("x-forwarded-proto") or request.url.scheme
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or request.url.netloc
    base = f"{proto}://{host}"
    auth = request.headers.get("authorization") or ""
    extended = auth.lower().startswith("bearer ")
    return build_agent_card(base_url=base, extended=extended)


if _PUBLIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(_PUBLIC_DIR)), name="static")
    # Static mount still serves other well-known assets if any; agent cards
    # are handled by the dynamic routes above (registered first).
    app.mount("/.well-known", StaticFiles(directory=str(_PUBLIC_DIR / ".well-known")), name="well-known")


# REST routers
app.include_router(auth.router)
app.include_router(sso.router)
app.include_router(workspaces.router)
app.include_router(approvals.router)
app.include_router(a2a.router)
app.include_router(acp.router)
app.include_router(discovery.router)
app.include_router(contacts.router)
app.include_router(companies.router)
app.include_router(leads.router)
app.include_router(pipelines.router)
app.include_router(deals.router)
app.include_router(quotes.router)
app.include_router(views.router)
app.include_router(jobs.router)
app.include_router(policies.router)
app.include_router(forensics.router)
app.include_router(import_crm.router)
app.include_router(custom_objects.router)
app.include_router(products.router)
app.include_router(forecast.router)
app.include_router(activities.router)
app.include_router(email.router)
app.include_router(calendar.router)
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
app.include_router(welcome.router)


# MCP server mounted at /mcp.
# Starlette Mount redirects bare ``/mcp`` → ``/mcp/`` with 307. Many MCP
# clients (including some Grok / connector stacks) POST without a trailing
# slash and do **not** re-POST after redirect, so initialize never succeeds.
# Rewrite path in-scope (no HTTP redirect) so both URLs work.
try:
    from app.mcp_server import build_asgi_app

    app.mount("/mcp", build_asgi_app())
    log.info("MCP server mounted at /mcp")
except Exception as exc:  # noqa: BLE001
    log.warning("MCP server failed to mount: %s", exc)


class _McpTrailingSlashFix:
    """ASGI wrapper: ``/mcp`` is rewritten to ``/mcp/`` (no HTTP redirect)."""

    def __init__(self, asgi_app):
        self.app = asgi_app

    async def __call__(self, scope, receive, send):
        if scope.get("type") == "http" and scope.get("path") == "/mcp":
            scope = dict(scope)
            scope["path"] = "/mcp/"
            if "raw_path" in scope:
                scope["raw_path"] = b"/mcp/"
        await self.app(scope, receive, send)


# Keep the public name ``app`` for uvicorn ``app.main:app``.
app = _McpTrailingSlashFix(app)  # type: ignore[assignment]

# Root path "/" is owned by app/routers/welcome.py — fresh installs get
# the welcome page, initialized installs get the JSON discovery doc.
