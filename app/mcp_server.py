"""MCP server exposing Nakatomi CRM tools over streamable HTTP.

The server is mounted at ``/mcp`` by ``app/main.py``. Agents authenticate by sending the
same ``Authorization: Bearer nk_...`` API key header they'd use against the REST API;
each tool resolves that header into a :class:`Principal` and executes against the DB
using the same service helpers as the REST routes.

If you run into SDK version drift, the two moving pieces are:
1. :func:`FastMCP.streamable_http_app` — returns the ASGI app to mount.
2. :func:`mcp.server.fastmcp.Context` — used to reach the current HTTP request
   for per-call auth.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from mcp.server.auth.provider import AccessToken
from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import Context, FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import AnyHttpUrl
from sqlalchemy import func, or_, select

from app.config import settings
from app.db import SessionLocal
from app.deps import Principal, mcp_idempotency
from app.models import (
    Activity,
    ApiKey,
    ApprovalRequest,
    ApprovalStatus,
    CalendarFeed,
    Company,
    Contact,
    Deal,
    DealLineItem,
    DealStatus,
    EmailConfig,
    EntityType,
    IngestRun,
    MemoryLink,
    Note,
    Pipeline,
    Product,
    Relationship,
    Stage,
    Task,
    TaskStatus,
    TimelineEvent,
    User,
    Workspace,
)
from app.scopes import has_scope, missing_scopes, normalize_scopes
from app.security import hash_api_key
from app.services.ingest import adapters as _ingest_adapters  # noqa: F401  — registers adapters
from app.services.ingest.base import run_ingest
from app.services.memory import enabled_connectors, get_connector

log = logging.getLogger("nakatomi.mcp")


def _public_base_url() -> str:
    """Issuer / resource base for MCP OAuth discovery (set PUBLIC_BASE_URL in prod)."""
    base = (settings.PUBLIC_BASE_URL or "").strip().rstrip("/")
    return base or "http://localhost:8000"


class NakatomiTokenVerifier:
    """Validate Bearer tokens for MCP HTTP transport.

    Accepts workspace API keys and OAuth access tokens (both are ``nk_…``
    rows in ``api_keys``). Invalid/missing tokens make the transport return
    **401** with ``WWW-Authenticate`` so clients prompt for auth instead of
    connecting anonymously and only failing later inside tool handlers.
    """

    async def verify_token(self, token: str) -> AccessToken | None:
        if not token or not token.startswith("nk_"):
            return None
        db = SessionLocal()
        try:
            key = db.scalar(select(ApiKey).where(ApiKey.key_hash == hash_api_key(token)))
            if not key or key.revoked_at is not None:
                return None
            if key.expires_at is not None:
                exp = key.expires_at
                if exp.tzinfo is None:
                    exp = exp.replace(tzinfo=UTC)
                if exp < datetime.now(UTC):
                    return None
            scopes = list(normalize_scopes(key.scopes))
            # Advertise mcp scope for clients that request it; * already full access.
            if "mcp" not in scopes:
                scopes.append("mcp")
            expires_at = None
            if key.expires_at is not None:
                exp = key.expires_at
                if exp.tzinfo is None:
                    exp = exp.replace(tzinfo=UTC)
                expires_at = int(exp.timestamp())
            return AccessToken(
                token=token,
                client_id=key.prefix or key.id,
                scopes=scopes,
                expires_at=expires_at,
            )
        finally:
            db.close()


# Two non-default settings:
#  - streamable_http_path='/'. Default is '/mcp', which when mounted under
#    our '/mcp' prefix would make the public URL /mcp/mcp. MCP clients
#    expect exactly /mcp/.
#  - TransportSecuritySettings.enable_dns_rebinding_protection=False. The
#    default whitelists only localhost and blocks everything else; our
#    Railway domain (or any remote host) gets rejected with a 500.
#    We're behind Railway's edge with TLS termination — the DNS-rebinding
#    attack model assumes a local-only server, which isn't our deploy.
#  - auth + token_verifier: HTTP 401 until a valid Bearer nk_… is presented
#    (OAuth 2.1 discovery still via app/.well-known routes).
_base = _public_base_url()
mcp = FastMCP(
    "Nakatomi CRM",
    streamable_http_path="/",
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    token_verifier=NakatomiTokenVerifier(),
    auth=AuthSettings(
        issuer_url=AnyHttpUrl(_base),
        resource_server_url=AnyHttpUrl(_base),
        # Empty: any valid nk_ key is enough; tool scopes still enforced in-handler.
        required_scopes=[],
        service_documentation_url=AnyHttpUrl(
            "https://github.com/mrdulasolutions/NakatomiCRM/blob/main/docs/MCP.md"
        ),
    ),
)


# ---------------------------------------------------------------------------
# Auth helper — resolve Principal from the current MCP request headers
# ---------------------------------------------------------------------------


def _principal_from_ctx(ctx: Context) -> tuple[Principal, Any]:
    """Return (principal, db_session). Caller is responsible for closing the session."""
    token: str | None = None
    try:
        req = ctx.request_context.request
        auth = req.headers.get("authorization") if req else None
        if auth and auth.lower().startswith("bearer "):
            token = auth.split(None, 1)[1].strip()
    except Exception:  # noqa: BLE001
        token = None
    if not token or not token.startswith("nk_"):
        raise RuntimeError(
            "missing nakatomi api key; set Authorization: Bearer nk_... in your MCP client config"
        )
    db = SessionLocal()
    key = db.scalar(select(ApiKey).where(ApiKey.key_hash == hash_api_key(token)))
    if not key or key.revoked_at is not None:
        db.close()
        raise RuntimeError("invalid or revoked api key")
    ws = db.get(Workspace, key.workspace_id)
    user = db.get(User, key.user_id) if key.user_id else None
    scopes = normalize_scopes(key.scopes)
    return Principal(user=user, api_key=key, workspace=ws, role=key.role, scopes=scopes), db


def _require_scopes(principal: Principal, *needed: str) -> None:
    miss = missing_scopes(principal.scopes, *needed)
    if miss:
        raise RuntimeError(
            f"missing scopes: {miss}; suggestion: mint a key with those scopes "
            f"via POST /workspace/api-keys or use '*'"
        )


def _record_event(
    db, principal: Principal, *, event_type: str, entity_type: EntityType, entity_id: str, payload: dict
) -> None:
    db.add(
        TimelineEvent(
            workspace_id=principal.workspace.id,
            entity_type=entity_type,
            entity_id=entity_id,
            event_type=event_type,
            actor_user_id=principal.user_id,
            actor_api_key_id=principal.api_key_id,
            payload=payload,
        )
    )


# ---------------------------------------------------------------------------
# Contact tools
# ---------------------------------------------------------------------------


@mcp.tool()
def search_contacts(
    ctx: Context,
    query: str | None = None,
    email: str | None = None,
    company_id: str | None = None,
    tag: str | None = None,
    limit: int = 25,
) -> list[dict]:
    """Search contacts by name/email substring, exact email, company, or tag."""
    p, db = _principal_from_ctx(ctx)
    try:
        _require_scopes(p, "contacts:read")
        q = select(Contact).where(Contact.workspace_id == p.workspace.id, Contact.deleted_at.is_(None))
        if query:
            like = f"%{query.lower()}%"
            q = q.where(
                or_(
                    func.lower(Contact.first_name).like(like),
                    func.lower(Contact.last_name).like(like),
                    func.lower(Contact.email).like(like),
                )
            )
        if email:
            q = q.where(func.lower(Contact.email) == email.lower())
        if company_id:
            q = q.where(Contact.company_id == company_id)
        if tag:
            q = q.where(Contact.tags.contains([tag]))
        q = q.order_by(Contact.created_at.desc()).limit(min(limit, 200))
        return [_serialize(c) for c in db.scalars(q).all()]
    finally:
        db.close()


@mcp.tool()
def get_contact(ctx: Context, contact_id: str) -> dict:
    """Fetch one contact by id."""
    p, db = _principal_from_ctx(ctx)
    try:
        _require_scopes(p, "contacts:read")
        c = db.get(Contact, contact_id)
        if not c or c.workspace_id != p.workspace.id:
            raise RuntimeError("not found")
        return _serialize(c)
    finally:
        db.close()


@mcp.tool()
def create_contact(
    ctx: Context,
    first_name: str | None = None,
    last_name: str | None = None,
    email: str | None = None,
    phone: str | None = None,
    title: str | None = None,
    company_id: str | None = None,
    tags: list[str] | None = None,
    external_id: str | None = None,
    data: dict | None = None,
    idempotency_key: str | None = None,
) -> dict:
    """Create a new contact. Pass idempotency_key to safely retry."""
    p, db = _principal_from_ctx(ctx)
    try:
        _require_scopes(p, "contacts:write")
        args = {
            "first_name": first_name,
            "last_name": last_name,
            "email": email,
            "phone": phone,
            "title": title,
            "company_id": company_id,
            "tags": tags,
            "external_id": external_id,
            "data": data,
        }
        replay, save = mcp_idempotency(
            db, p, tool="create_contact", idempotency_key=idempotency_key, args=args
        )
        if replay is not None:
            return replay
        c = Contact(
            workspace_id=p.workspace.id,
            first_name=first_name,
            last_name=last_name,
            email=email,
            phone=phone,
            title=title,
            company_id=company_id,
            tags=tags or [],
            data=data or {},
            external_id=external_id,
        )
        db.add(c)
        db.flush()
        _record_event(
            db,
            p,
            event_type="contact.created",
            entity_type=EntityType.contact,
            entity_id=c.id,
            payload={"via": "mcp"},
        )
        db.commit()
        db.refresh(c)
        out = _serialize(c)
        save(201, out)
        return out
    finally:
        db.close()


@mcp.tool()
def update_contact(ctx: Context, contact_id: str, updates: dict) -> dict:
    """Patch an existing contact. ``updates`` may contain any field from the contact schema."""
    p, db = _principal_from_ctx(ctx)
    try:
        _require_scopes(p, "contacts:write")
        c = db.get(Contact, contact_id)
        if not c or c.workspace_id != p.workspace.id:
            raise RuntimeError("not found")
        for k, v in updates.items():
            if hasattr(c, k):
                setattr(c, k, v)
        _record_event(
            db,
            p,
            event_type="contact.updated",
            entity_type=EntityType.contact,
            entity_id=c.id,
            payload={"changes": list(updates.keys())},
        )
        db.commit()
        db.refresh(c)
        return _serialize(c)
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Company tools
# ---------------------------------------------------------------------------


@mcp.tool()
def search_companies(
    ctx: Context,
    query: str | None = None,
    domain: str | None = None,
    tag: str | None = None,
    limit: int = 25,
) -> list[dict]:
    p, db = _principal_from_ctx(ctx)
    try:
        _require_scopes(p, "companies:read")
        q = select(Company).where(Company.workspace_id == p.workspace.id, Company.deleted_at.is_(None))
        if query:
            like = f"%{query.lower()}%"
            q = q.where(or_(func.lower(Company.name).like(like), func.lower(Company.domain).like(like)))
        if domain:
            q = q.where(func.lower(Company.domain) == domain.lower())
        if tag:
            q = q.where(Company.tags.contains([tag]))
        q = q.order_by(Company.created_at.desc()).limit(min(limit, 200))
        return [_serialize(c) for c in db.scalars(q).all()]
    finally:
        db.close()


@mcp.tool()
def create_company(
    ctx: Context,
    name: str,
    domain: str | None = None,
    website: str | None = None,
    industry: str | None = None,
    employee_count: int | None = None,
    annual_revenue: float | None = None,
    description: str | None = None,
    tags: list[str] | None = None,
    external_id: str | None = None,
    data: dict | None = None,
    idempotency_key: str | None = None,
) -> dict:
    p, db = _principal_from_ctx(ctx)
    try:
        _require_scopes(p, "companies:write")
        _idem_args = {
            k: v
            for k, v in locals().items()
            if k not in ("ctx", "p", "db", "idempotency_key") and not k.startswith("_")
        }
        _replay, _save = mcp_idempotency(
            db, p, tool="create_company", idempotency_key=idempotency_key, args=_idem_args
        )
        if _replay is not None:
            return _replay
        c = Company(
            workspace_id=p.workspace.id,
            name=name,
            domain=domain,
            website=website,
            industry=industry,
            employee_count=employee_count,
            annual_revenue=annual_revenue,
            description=description,
            tags=tags or [],
            data=data or {},
            external_id=external_id,
        )
        db.add(c)
        db.flush()
        _record_event(
            db,
            p,
            event_type="company.created",
            entity_type=EntityType.company,
            entity_id=c.id,
            payload={"via": "mcp"},
        )
        db.commit()
        db.refresh(c)
        out = _serialize(c)
        _save(201, out)
        return out
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Deal tools
# ---------------------------------------------------------------------------


@mcp.tool()
def list_pipelines(ctx: Context) -> list[dict]:
    p, db = _principal_from_ctx(ctx)
    try:
        _require_scopes(p, "pipelines:read")
        rows = db.scalars(select(Pipeline).where(Pipeline.workspace_id == p.workspace.id)).all()
        out = []
        for pipe in rows:
            out.append(
                {
                    "id": pipe.id,
                    "name": pipe.name,
                    "slug": pipe.slug,
                    "is_default": pipe.is_default,
                    "stages": [
                        {
                            "id": s.id,
                            "name": s.name,
                            "slug": s.slug,
                            "position": s.position,
                            "probability": float(s.probability),
                            "is_won": s.is_won,
                            "is_lost": s.is_lost,
                        }
                        for s in pipe.stages
                    ],
                }
            )
        return out
    finally:
        db.close()


@mcp.tool()
def create_pipeline(
    ctx: Context,
    name: str,
    slug: str,
    stages: list[dict],
    is_default: bool = False,
    data: dict | None = None,
) -> dict:
    """Create a pipeline with its stages in one call.

    Each entry in ``stages`` accepts: ``name`` (required), ``slug`` (required,
    ``[a-z0-9][a-z0-9_-]*``), ``position`` (int, default 0), ``probability``
    (0–1 float, default 0), ``is_won`` (bool), ``is_lost`` (bool). Unknown
    keys are rejected.

    If ``is_default`` is true, any other pipeline flagged default in this
    workspace is flipped off — only one default at a time.
    """
    allowed = {"name", "slug", "position", "probability", "is_won", "is_lost"}
    p, db = _principal_from_ctx(ctx)
    try:
        _require_scopes(p, "pipelines:write")
        pipe = Pipeline(
            workspace_id=p.workspace.id,
            name=name,
            slug=slug,
            is_default=is_default,
            data=data or {},
        )
        db.add(pipe)
        db.flush()
        for s in stages:
            extra = set(s) - allowed
            if extra:
                raise RuntimeError(f"unknown stage field(s): {sorted(extra)}")
            if "name" not in s or "slug" not in s:
                raise RuntimeError("stage requires name and slug")
            db.add(Stage(pipeline_id=pipe.id, **s))
        if is_default:
            others = db.scalars(
                select(Pipeline).where(
                    Pipeline.workspace_id == p.workspace.id,
                    Pipeline.id != pipe.id,
                )
            ).all()
            for o in others:
                o.is_default = False
        db.commit()
        db.refresh(pipe)
        return {
            "id": pipe.id,
            "name": pipe.name,
            "slug": pipe.slug,
            "is_default": pipe.is_default,
            "stages": [
                {
                    "id": s.id,
                    "name": s.name,
                    "slug": s.slug,
                    "position": s.position,
                    "probability": float(s.probability),
                    "is_won": s.is_won,
                    "is_lost": s.is_lost,
                }
                for s in pipe.stages
            ],
        }
    finally:
        db.close()


@mcp.tool()
def create_deal(
    ctx: Context,
    name: str,
    amount: float | None = None,
    currency: str = "USD",
    pipeline_id: str | None = None,
    stage_id: str | None = None,
    primary_contact_id: str | None = None,
    company_id: str | None = None,
    expected_close_date: datetime | None = None,
    tags: list[str] | None = None,
    data: dict | None = None,
    idempotency_key: str | None = None,
) -> dict:
    p, db = _principal_from_ctx(ctx)
    try:
        _require_scopes(p, "deals:write")
        _idem_args = {
            k: v
            for k, v in locals().items()
            if k not in ("ctx", "p", "db", "idempotency_key") and not k.startswith("_")
        }
        _replay, _save = mcp_idempotency(
            db, p, tool="create_deal", idempotency_key=idempotency_key, args=_idem_args
        )
        if _replay is not None:
            return _replay
        if not pipeline_id:
            pipe = db.scalar(
                select(Pipeline)
                .where(Pipeline.workspace_id == p.workspace.id)
                .order_by(Pipeline.is_default.desc(), Pipeline.created_at.asc())
                .limit(1)
            )
            if not pipe:
                raise RuntimeError("no pipelines; create one via the REST API first")
            pipeline_id = pipe.id
        if not stage_id:
            st = db.scalar(
                select(Stage).where(Stage.pipeline_id == pipeline_id).order_by(Stage.position).limit(1)
            )
            if not st:
                raise RuntimeError("pipeline has no stages")
            stage_id = st.id

        d = Deal(
            workspace_id=p.workspace.id,
            name=name,
            amount=amount,
            currency=currency,
            pipeline_id=pipeline_id,
            stage_id=stage_id,
            primary_contact_id=primary_contact_id,
            company_id=company_id,
            expected_close_date=expected_close_date,
            tags=tags or [],
            data=data or {},
        )
        db.add(d)
        db.flush()
        _record_event(
            db,
            p,
            event_type="deal.created",
            entity_type=EntityType.deal,
            entity_id=d.id,
            payload={"via": "mcp"},
        )
        db.commit()
        db.refresh(d)
        out = _serialize(d)
        _save(201, out)
        return out
    finally:
        db.close()


@mcp.tool()
def move_deal_stage(ctx: Context, deal_id: str, stage_slug: str) -> dict:
    """Move a deal to a new stage (by slug within its pipeline)."""
    p, db = _principal_from_ctx(ctx)
    try:
        _require_scopes(p, "deals:write")
        d = db.get(Deal, deal_id)
        if not d or d.workspace_id != p.workspace.id:
            raise RuntimeError("not found")
        new_stage = db.scalar(
            select(Stage).where(Stage.pipeline_id == d.pipeline_id, Stage.slug == stage_slug)
        )
        if not new_stage:
            raise RuntimeError(f"stage slug '{stage_slug}' not in this deal's pipeline")
        old = d.stage_id
        d.stage_id = new_stage.id
        if new_stage.is_won:
            d.status = DealStatus.won
            d.closed_at = datetime.now(UTC)
        elif new_stage.is_lost:
            d.status = DealStatus.lost
            d.closed_at = datetime.now(UTC)
        _record_event(
            db,
            p,
            event_type="deal.stage_changed",
            entity_type=EntityType.deal,
            entity_id=d.id,
            payload={"from_stage_id": old, "to_stage_id": new_stage.id},
        )
        db.commit()
        db.refresh(d)
        return _serialize(d)
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Activity / Note / Task tools
# ---------------------------------------------------------------------------


@mcp.tool()
def log_activity(
    ctx: Context,
    kind: str,
    subject: str | None = None,
    body: str | None = None,
    entity_type: str | None = None,
    entity_id: str | None = None,
    occurred_at: datetime | None = None,
    data: dict | None = None,
) -> dict:
    """Log a call, meeting, email, or other touchpoint against a contact/company/deal."""
    p, db = _principal_from_ctx(ctx)
    try:
        _require_scopes(p, "activities:write")
        a = Activity(
            workspace_id=p.workspace.id,
            actor_user_id=p.user_id,
            kind=kind,
            subject=subject,
            body=body,
            entity_type=EntityType(entity_type) if entity_type else None,
            entity_id=entity_id,
            occurred_at=occurred_at or datetime.now(UTC),
            data=data or {},
        )
        db.add(a)
        db.flush()
        _record_event(
            db,
            p,
            event_type="activity.created",
            entity_type=EntityType.activity,
            entity_id=a.id,
            payload={"kind": kind},
        )
        db.commit()
        db.refresh(a)
        return _serialize(a)
    finally:
        db.close()


@mcp.tool()
def add_note(ctx: Context, entity_type: str, entity_id: str, body: str, data: dict | None = None) -> dict:
    """Attach a markdown note to a CRM entity."""
    p, db = _principal_from_ctx(ctx)
    try:
        _require_scopes(p, "notes:write")
        n = Note(
            workspace_id=p.workspace.id,
            author_user_id=p.user_id,
            entity_type=EntityType(entity_type),
            entity_id=entity_id,
            body=body,
            data=data or {},
        )
        db.add(n)
        db.flush()
        _record_event(
            db,
            p,
            event_type="note.created",
            entity_type=EntityType.note,
            entity_id=n.id,
            payload={"on": entity_type, "entity_id": entity_id},
        )
        db.commit()
        db.refresh(n)
        return _serialize(n)
    finally:
        db.close()


@mcp.tool()
def create_task(
    ctx: Context,
    title: str,
    description: str | None = None,
    due_at: datetime | None = None,
    assignee_user_id: str | None = None,
    entity_type: str | None = None,
    entity_id: str | None = None,
    data: dict | None = None,
    idempotency_key: str | None = None,
) -> dict:
    p, db = _principal_from_ctx(ctx)
    try:
        _require_scopes(p, "tasks:write")
        _idem_args = {
            k: v
            for k, v in locals().items()
            if k not in ("ctx", "p", "db", "idempotency_key") and not k.startswith("_")
        }
        _replay, _save = mcp_idempotency(
            db, p, tool="create_task", idempotency_key=idempotency_key, args=_idem_args
        )
        if _replay is not None:
            return _replay
        t = Task(
            workspace_id=p.workspace.id,
            title=title,
            description=description,
            due_at=due_at,
            assignee_user_id=assignee_user_id,
            entity_type=EntityType(entity_type) if entity_type else None,
            entity_id=entity_id,
            data=data or {},
        )
        db.add(t)
        db.flush()
        _record_event(
            db,
            p,
            event_type="task.created",
            entity_type=EntityType.task,
            entity_id=t.id,
            payload={"title": title},
        )
        db.commit()
        db.refresh(t)
        out = _serialize(t)
        _save(201, out)
        return out
    finally:
        db.close()


@mcp.tool()
def list_tasks(
    ctx: Context,
    status: str | None = None,
    assignee_user_id: str | None = None,
    limit: int = 50,
) -> list[dict]:
    p, db = _principal_from_ctx(ctx)
    try:
        _require_scopes(p, "tasks:read")
        q = select(Task).where(Task.workspace_id == p.workspace.id, Task.deleted_at.is_(None))
        if status:
            q = q.where(Task.status == TaskStatus(status))
        if assignee_user_id:
            q = q.where(Task.assignee_user_id == assignee_user_id)
        q = q.order_by(Task.due_at.asc().nulls_last(), Task.created_at.desc()).limit(min(limit, 200))
        return [_serialize(t) for t in db.scalars(q).all()]
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Relationships / timeline
# ---------------------------------------------------------------------------


@mcp.tool()
def relate(
    ctx: Context,
    source_type: str,
    source_id: str,
    target_type: str,
    target_id: str,
    relation_type: str,
    strength: float = 1.0,
    data: dict | None = None,
) -> dict:
    """Create a typed edge between two entities in the relationship graph."""
    p, db = _principal_from_ctx(ctx)
    try:
        _require_scopes(p, "relationships:write")
        r = Relationship(
            workspace_id=p.workspace.id,
            source_type=EntityType(source_type),
            source_id=source_id,
            target_type=EntityType(target_type),
            target_id=target_id,
            relation_type=relation_type,
            strength=strength,
            data=data or {},
        )
        db.add(r)
        try:
            db.flush()
        except Exception:
            db.rollback()
            raise RuntimeError("edge already exists")
        _record_event(
            db,
            p,
            event_type="relationship.created",
            entity_type=EntityType(source_type),
            entity_id=source_id,
            payload={
                "target_type": target_type,
                "target_id": target_id,
                "relation_type": relation_type,
            },
        )
        db.commit()
        db.refresh(r)
        return _serialize(r)
    finally:
        db.close()


@mcp.tool()
def timeline(
    ctx: Context,
    entity_type: str,
    entity_id: str,
    limit: int = 50,
    since: str | None = None,
) -> list[dict]:
    """Return the most recent events for one entity (includes actor_label)."""
    from datetime import datetime

    from app.services.timeline_present import enrich_timeline_events

    p, db = _principal_from_ctx(ctx)
    try:
        _require_scopes(p, "timeline:read")
        q = select(TimelineEvent).where(
            TimelineEvent.workspace_id == p.workspace.id,
            TimelineEvent.entity_type == EntityType(entity_type),
            TimelineEvent.entity_id == entity_id,
        )
        if since:
            q = q.where(TimelineEvent.occurred_at >= datetime.fromisoformat(since.replace("Z", "+00:00")))
        rows = db.scalars(
            q.order_by(TimelineEvent.occurred_at.desc(), TimelineEvent.id.desc()).limit(min(limit, 500))
        ).all()
        return enrich_timeline_events(db, p.workspace.id, rows)
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Memory tools
# ---------------------------------------------------------------------------


@mcp.tool()
def memory_list_connectors(ctx: Context) -> list[str]:
    """List enabled memory connectors (docdeploy, supermemory, gbrain, ...)."""
    _principal_from_ctx(ctx)[1].close()
    return list(enabled_connectors().keys())


@mcp.tool()
def memory_recall(
    ctx: Context,
    query: str,
    entity_type: str | None = None,
    entity_id: str | None = None,
    limit: int = 10,
    connectors: list[str] | None = None,
) -> list[dict]:
    """Fan-out semantic recall across configured memory connectors and merge the results.

    Pass ``entity_type`` + ``entity_id`` to anchor the recall on a specific CRM entity.
    Results include any known ``crm_links`` (cross-links to CRM entities) so the agent
    can pivot back into the CRM from a matched memory.
    """
    p, db = _principal_from_ctx(ctx)
    try:
        _require_scopes(p, "memory:read")
        targets = connectors or list(enabled_connectors().keys())
        out: list[dict] = []
        for name in targets:
            connector = get_connector(name)
            if not connector:
                continue
            try:
                got = connector.recall(
                    workspace_id=p.workspace.id,
                    query=query,
                    crm_entity_type=entity_type,
                    crm_entity_id=entity_id,
                    limit=limit,
                )
            except Exception as e:  # noqa: BLE001
                log.warning("recall on '%s' failed: %s", name, e)
                continue
            for m in got:
                links = db.scalars(
                    select(MemoryLink).where(
                        MemoryLink.workspace_id == p.workspace.id,
                        MemoryLink.connector == name,
                        MemoryLink.external_id == m.external_id,
                    )
                ).all()
                out.append(
                    {
                        "connector": m.connector,
                        "external_id": m.external_id,
                        "text": m.text,
                        "score": m.score,
                        "metadata": m.metadata,
                        "crm_links": [
                            f"{link.crm_entity_type.value if hasattr(link.crm_entity_type, 'value') else link.crm_entity_type}:{link.crm_entity_id}"
                            for link in links
                        ],
                    }
                )
        out.sort(key=lambda x: x["score"], reverse=True)
        return out[:limit]
    finally:
        db.close()


@mcp.tool()
def memory_link(
    ctx: Context,
    connector: str,
    external_id: str,
    crm_entity_type: str,
    crm_entity_id: str,
    note: str | None = None,
    data: dict | None = None,
) -> dict:
    """Cross-link a memory in an external system with a CRM entity. Idempotent on
    (connector, external_id, crm_entity_type, crm_entity_id)."""
    p, db = _principal_from_ctx(ctx)
    try:
        _require_scopes(p, "memory:write")
        try:
            et = EntityType(crm_entity_type)
        except ValueError:
            raise RuntimeError(f"unknown crm_entity_type '{crm_entity_type}'")
        link = MemoryLink(
            workspace_id=p.workspace.id,
            connector=connector,
            external_id=external_id,
            crm_entity_type=et,
            crm_entity_id=crm_entity_id,
            note=note,
            data=data or {},
        )
        db.add(link)
        try:
            db.flush()
        except Exception:
            db.rollback()
            raise RuntimeError("link already exists")
        _record_event(
            db,
            p,
            event_type="memory.linked",
            entity_type=et,
            entity_id=crm_entity_id,
            payload={"connector": connector, "external_id": external_id},
        )
        db.commit()
        db.refresh(link)
        return _serialize(link)
    finally:
        db.close()


@mcp.tool()
def memory_trace(ctx: Context, entity_type: str, entity_id: str) -> list[dict]:
    """Return every external memory linked to the given CRM entity."""
    p, db = _principal_from_ctx(ctx)
    try:
        _require_scopes(p, "memory:read")
        try:
            et = EntityType(entity_type)
        except ValueError:
            raise RuntimeError(f"unknown entity_type '{entity_type}'")
        rows = db.scalars(
            select(MemoryLink).where(
                MemoryLink.workspace_id == p.workspace.id,
                MemoryLink.crm_entity_type == et,
                MemoryLink.crm_entity_id == entity_id,
            )
        ).all()
        return [_serialize(r) for r in rows]
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Ingest tool
# ---------------------------------------------------------------------------


@mcp.tool()
def ingest(
    ctx: Context,
    source: str,
    format: str,
    payload: Any,
    mapping: dict | None = None,
    dry_run: bool = False,
) -> dict:
    """Normalize and land external data as CRM rows.

    ``format`` is one of: ``csv``, ``json``, ``vcard``, ``text``. For ``csv`` and
    ``vcard`` pass the raw string as ``payload``. For ``json`` pass a list of dicts
    (or a single dict). For ``text`` pass a string and set
    ``mapping={"entity_type": "contact", "entity_id": "<uuid>"}`` to attach the text
    as a markdown note on that entity.

    Matches existing rows by ``external_id`` first, then by ``email``/``domain`` where
    applicable. Returns counts, created/updated ids, and a diagnostics list.
    Set ``dry_run=true`` to see what would happen without writing.
    """
    p, db = _principal_from_ctx(ctx)
    try:
        _require_scopes(p, "ingest:write")
        result = run_ingest(
            db,
            p,
            fmt=format.lower(),
            payload=payload,
            mapping=mapping,
            dry_run=dry_run,
        )
        run = IngestRun(
            workspace_id=p.workspace.id,
            source=source,
            format=format,
            actor_user_id=p.user_id,
            actor_api_key_id=p.api_key_id,
            record_count=result.record_count,
            created_count=len(result.created_ids),
            updated_count=len(result.updated_ids),
            error_count=result.error_count,
            diagnostics={"items": result.diagnostics},
        )
        db.add(run)
        db.flush()
        _record_event(
            db,
            p,
            event_type="ingest.completed",
            entity_type=EntityType.file,
            entity_id=run.id,
            payload={
                "source": source,
                "format": format,
                "record_count": result.record_count,
                "created": len(result.created_ids),
                "updated": len(result.updated_ids),
                "errors": result.error_count,
            },
        )
        if dry_run:
            db.rollback()
        else:
            db.commit()
        return {
            "run_id": run.id,
            "record_count": result.record_count,
            "created": len(result.created_ids),
            "updated": len(result.updated_ids),
            "errors": result.error_count,
            "created_ids": result.created_ids,
            "updated_ids": result.updated_ids,
            "diagnostics": result.diagnostics,
        }
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Products + line items + forecast (v0.3)
# ---------------------------------------------------------------------------


@mcp.tool()
def create_product(
    ctx: Context,
    name: str,
    sku: str | None = None,
    unit_price: float | None = None,
    currency: str = "USD",
    description: str | None = None,
    tags: list[str] | None = None,
    data: dict | None = None,
    idempotency_key: str | None = None,
) -> dict:
    """Add a product to the workspace catalog. Returns the new product."""
    p, db = _principal_from_ctx(ctx)
    try:
        _require_scopes(p, "products:write")
        _idem_args = {
            k: v
            for k, v in locals().items()
            if k not in ("ctx", "p", "db", "idempotency_key") and not k.startswith("_")
        }
        _replay, _save = mcp_idempotency(
            db, p, tool="create_product", idempotency_key=idempotency_key, args=_idem_args
        )
        if _replay is not None:
            return _replay
        prod = Product(
            workspace_id=p.workspace.id,
            name=name,
            sku=sku,
            unit_price=unit_price,
            currency=currency,
            description=description,
            tags=tags or [],
            data=data or {},
        )
        db.add(prod)
        try:
            db.commit()
        except Exception as exc:
            db.rollback()
            raise RuntimeError(f"product conflict: {exc.__class__.__name__}") from exc
        db.refresh(prod)
        _record_event(
            db,
            p,
            event_type="product.created",
            entity_type=EntityType.product,
            entity_id=prod.id,
            payload={"via": "mcp"},
        )
        db.commit()
        out = _serialize(prod)
        _save(201, out)
        return out
    finally:
        db.close()


@mcp.tool()
def search_products(
    ctx: Context,
    q: str | None = None,
    sku: str | None = None,
    is_active: bool | None = None,
    limit: int = 25,
) -> list[dict]:
    """Find products by substring on name/sku/description, exact SKU, or active flag."""
    p, db = _principal_from_ctx(ctx)
    try:
        _require_scopes(p, "products:read")
        query = select(Product).where(Product.workspace_id == p.workspace.id, Product.deleted_at.is_(None))
        if q:
            like = f"%{q.lower()}%"
            query = query.where(
                or_(
                    func.lower(Product.name).like(like),
                    func.lower(Product.sku).like(like),
                    func.lower(Product.description).like(like),
                )
            )
        if sku:
            query = query.where(Product.sku == sku)
        if is_active is not None:
            query = query.where(Product.is_active.is_(is_active))
        query = query.order_by(Product.created_at.desc()).limit(min(limit, 100))
        return [_serialize(r) for r in db.scalars(query).all()]
    finally:
        db.close()


@mcp.tool()
def add_line_item(
    ctx: Context,
    deal_id: str,
    product_id: str | None = None,
    name: str | None = None,
    quantity: float = 1,
    unit_price: float | None = None,
    sku: str | None = None,
    currency: str | None = None,
    position: int = 0,
    data: dict | None = None,
    idempotency_key: str | None = None,
) -> dict:
    """Add a line to a deal. Either reference a ``product_id`` (snapshots
    catalog name + price) or supply ``name`` + ``unit_price`` directly for
    an ad-hoc line."""
    p, db = _principal_from_ctx(ctx)
    try:
        _require_scopes(p, "deals:write")
        _idem_args = {
            k: v
            for k, v in locals().items()
            if k not in ("ctx", "p", "db", "idempotency_key") and not k.startswith("_")
        }
        _replay, _save = mcp_idempotency(
            db, p, tool="add_line_item", idempotency_key=idempotency_key, args=_idem_args
        )
        if _replay is not None:
            return _replay
        deal = db.get(Deal, deal_id)
        if not deal or deal.workspace_id != p.workspace.id or deal.deleted_at is not None:
            raise RuntimeError("deal not found")

        snapshot_name = name
        snapshot_sku = sku
        snapshot_price = unit_price
        snapshot_currency = currency
        if product_id:
            prod = db.get(Product, product_id)
            if not prod or prod.workspace_id != p.workspace.id or prod.deleted_at is not None:
                raise RuntimeError("product not found")
            snapshot_name = snapshot_name or prod.name
            snapshot_sku = snapshot_sku or prod.sku
            if snapshot_price is None:
                snapshot_price = float(prod.unit_price or 0)
            if snapshot_currency is None:
                snapshot_currency = prod.currency
        if not snapshot_name:
            raise RuntimeError("name is required when product_id is omitted")

        line = DealLineItem(
            deal_id=deal_id,
            product_id=product_id,
            name=snapshot_name,
            sku=snapshot_sku,
            quantity=quantity,
            unit_price=snapshot_price if snapshot_price is not None else 0,
            currency=snapshot_currency or "USD",
            position=position,
            data=data or {},
        )
        db.add(line)
        db.commit()
        db.refresh(line)
        _record_event(
            db,
            p,
            event_type="deal.line_item_added",
            entity_type=EntityType.deal,
            entity_id=deal_id,
            payload={
                "line_item_id": line.id,
                "name": line.name,
                "amount": float(line.unit_price) * float(line.quantity),
                "via": "mcp",
            },
        )
        db.commit()
        out = _serialize(line)
        _save(201, out)
        return out
    finally:
        db.close()


@mcp.tool()
def list_line_items(ctx: Context, deal_id: str) -> list[dict]:
    """Return the line items on a deal in display order."""
    p, db = _principal_from_ctx(ctx)
    try:
        _require_scopes(p, "deals:read")
        deal = db.get(Deal, deal_id)
        if not deal or deal.workspace_id != p.workspace.id:
            raise RuntimeError("deal not found")
        rows = db.scalars(
            select(DealLineItem)
            .where(DealLineItem.deal_id == deal_id)
            .order_by(DealLineItem.position.asc(), DealLineItem.created_at.asc())
        ).all()
        return [_serialize(r) for r in rows]
    finally:
        db.close()


@mcp.tool()
def forecast(
    ctx: Context,
    period: str,
    pipeline_id: str | None = None,
    owner_user_id: str | None = None,
) -> dict:
    """Period rollup of pipeline value.

    ``period`` accepts ``2026Q2`` (calendar quarter), ``2026-04`` (calendar
    month), or ``custom:2026-04-01:2026-06-30`` (inclusive ISO range).
    Returns totals (open, weighted, won, lost), breakdown by stage, and
    breakdown by owner. Stage probability is stored 0..100 and divided
    once at rollup.
    """
    from app.routers.forecast import _parse_period  # local import to avoid cycle

    p, db = _principal_from_ctx(ctx)
    try:
        _require_scopes(p, "forecast:read")
        start, end, label = _parse_period(period)
        from datetime import datetime as _dt
        from datetime import timedelta as _td

        start_dt = _dt.combine(start, _dt.min.time(), tzinfo=UTC)
        end_dt = _dt.combine(end, _dt.min.time(), tzinfo=UTC)

        query = (
            select(Deal, Stage)
            .join(Stage, Stage.id == Deal.stage_id)
            .where(
                Deal.workspace_id == p.workspace.id,
                Deal.deleted_at.is_(None),
                Deal.expected_close_date >= start_dt,
                Deal.expected_close_date < end_dt,
            )
        )
        if pipeline_id:
            query = query.where(Deal.pipeline_id == pipeline_id)
        if owner_user_id:
            query = query.where(Deal.owner_user_id == owner_user_id)

        totals = {
            "open_count": 0,
            "open_amount": 0.0,
            "weighted_amount": 0.0,
            "won_count": 0,
            "won_amount": 0.0,
            "lost_count": 0,
            "lost_amount": 0.0,
        }
        by_stage: dict[str, dict] = {}
        by_owner: dict[str, dict] = {}

        for deal, stage in db.execute(query).all():
            amount = float(deal.amount or 0)
            prob_frac = float(stage.probability or 0) / 100.0
            if deal.status == DealStatus.won:
                totals["won_count"] += 1
                totals["won_amount"] += amount
                weight = 1.0
            elif deal.status == DealStatus.lost:
                totals["lost_count"] += 1
                totals["lost_amount"] += amount
                weight = 0.0
            else:
                totals["open_count"] += 1
                totals["open_amount"] += amount
                weight = prob_frac
            weighted = amount * weight
            totals["weighted_amount"] += weighted

            st = by_stage.setdefault(
                stage.id,
                {
                    "stage_id": stage.id,
                    "stage_slug": stage.slug,
                    "probability": float(stage.probability or 0),
                    "count": 0,
                    "amount": 0.0,
                    "weighted_amount": 0.0,
                },
            )
            st["count"] += 1
            st["amount"] += amount
            st["weighted_amount"] += weighted

            ok = deal.owner_user_id or "unassigned"
            ow = by_owner.setdefault(
                ok,
                {
                    "owner_user_id": deal.owner_user_id,
                    "count": 0,
                    "amount": 0.0,
                    "weighted_amount": 0.0,
                },
            )
            ow["count"] += 1
            ow["amount"] += amount
            ow["weighted_amount"] += weighted

        return {
            "period": label,
            "from": start.isoformat(),
            "to": (end - _td(days=1)).isoformat(),
            "totals": {k: round(v, 2) if isinstance(v, float) else v for k, v in totals.items()},
            "by_stage": sorted(by_stage.values(), key=lambda r: r["stage_slug"]),
            "by_owner": list(by_owner.values()),
        }
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Email + calendar (v0.3)
# ---------------------------------------------------------------------------


@mcp.tool()
def send_email(
    ctx: Context,
    to: list[str],
    subject: str,
    body: str,
    cc: list[str] | None = None,
    bcc: list[str] | None = None,
    body_html: str | None = None,
    contact_id: str | None = None,
    deal_id: str | None = None,
) -> dict:
    """Send an email via the workspace's configured SMTP. Requires ``email:send`` scope.
    Persists an ``email_outbound`` activity. Prefer ``propose_action`` when HITL is required."""
    from app.services.email_io import send_email as _send

    p, db = _principal_from_ctx(ctx)
    try:
        _require_scopes(p, "email:send")
        cfg = db.scalar(select(EmailConfig).where(EmailConfig.workspace_id == p.workspace.id))
        if cfg is None or not cfg.smtp_host:
            raise RuntimeError("SMTP not configured for this workspace")
        if not to:
            raise RuntimeError("`to` must contain at least one recipient")

        try:
            _send(
                cfg,
                to=to,
                cc=cc or [],
                bcc=bcc or [],
                subject=subject,
                body=body,
                body_html=body_html,
            )
        except Exception as exc:
            raise RuntimeError(f"smtp send failed: {exc}") from exc

        sent_at = datetime.now(UTC)
        entity_type = None
        entity_id = None
        if contact_id:
            entity_type, entity_id = EntityType.contact, contact_id
        elif deal_id:
            entity_type, entity_id = EntityType.deal, deal_id

        activity = Activity(
            workspace_id=p.workspace.id,
            kind="email_outbound",
            subject=subject[:500],
            body=body[:50_000],
            occurred_at=sent_at,
            entity_type=entity_type,
            entity_id=entity_id,
            data={
                "to": to,
                "cc": cc or [],
                "bcc": bcc or [],
                "from": cfg.from_address or cfg.smtp_user,
                "via": "mcp",
            },
        )
        db.add(activity)
        db.flush()
        if entity_id:
            _record_event(
                db,
                p,
                event_type="email.sent",
                entity_type=entity_type,
                entity_id=entity_id,
                payload={"activity_id": activity.id, "subject": subject, "via": "mcp"},
            )
        db.commit()
        return {
            "activity_id": activity.id,
            "sent_at": sent_at.isoformat(),
            "to": to,
            "subject": subject,
        }
    finally:
        db.close()


@mcp.tool()
def add_calendar_feed(ctx: Context, name: str, ics_url: str) -> dict:
    """Subscribe the workspace to an iCal feed. Any ``.ics`` URL works
    (Google, Microsoft, Fastmail, Hostinger, iCloud). Run
    ``sync_calendar_feed`` after to ingest events immediately."""
    p, db = _principal_from_ctx(ctx)
    try:
        _require_scopes(p, "calendar:write")
        feed = CalendarFeed(workspace_id=p.workspace.id, name=name, ics_url=ics_url)
        db.add(feed)
        db.commit()
        db.refresh(feed)
        return _serialize(feed)
    finally:
        db.close()


@mcp.tool()
def sync_calendar_feed(ctx: Context, feed_id: str) -> dict:
    """Run an on-demand sync of one calendar feed. Returns the count of
    events created or updated. Useful right after wiring a feed or when
    the caller knows there's been a change."""
    from app.services.calendar_io import sync_feed as _sync

    p, db = _principal_from_ctx(ctx)
    try:
        _require_scopes(p, "calendar:write")
        feed = db.get(CalendarFeed, feed_id)
        if not feed or feed.workspace_id != p.workspace.id:
            raise RuntimeError("feed not found")
        try:
            n = _sync(feed)
        except Exception as exc:
            raise RuntimeError(f"sync failed: {exc}") from exc
        return {"feed_id": feed_id, "events_touched": n}
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Approvals (HITL)
# ---------------------------------------------------------------------------


@mcp.tool()
def propose_action(
    ctx: Context,
    action: str,
    payload: dict | None = None,
    entity_type: str | None = None,
    entity_id: str | None = None,
    reason: str | None = None,
) -> dict:
    """Propose an action for human approval (HITL). Returns a pending approval_id.

    Use for sensitive work the agent cannot or should not execute alone
    (email.send without scope, large deal.won, custom workflows).
    """
    from app.services.approvals import create_approval

    p, db = _principal_from_ctx(ctx)
    try:
        _require_scopes(p, "approvals:write")
        row = create_approval(
            db,
            p,
            action=action,
            payload=payload or {},
            entity_type=entity_type,
            entity_id=entity_id,
            reason=reason,
        )
        return _serialize(row)
    finally:
        db.close()


@mcp.tool()
def list_pending_approvals(ctx: Context, limit: int = 50) -> list[dict]:
    """List pending (and recent) approval requests for this workspace."""
    p, db = _principal_from_ctx(ctx)
    try:
        _require_scopes(p, "approvals:read")
        q = (
            select(ApprovalRequest)
            .where(
                ApprovalRequest.workspace_id == p.workspace.id,
                ApprovalRequest.deleted_at.is_(None),
            )
            .order_by(ApprovalRequest.created_at.desc())
            .limit(min(limit, 200))
        )
        return [_serialize(r) for r in db.scalars(q).all()]
    finally:
        db.close()


@mcp.tool()
def decide_approval(
    ctx: Context,
    approval_id: str,
    approve: bool,
    note: str | None = None,
    execute: bool = True,
) -> dict:
    """Approve or reject a pending request. Requires owner/admin role or admin:keys scope."""
    from app.models import MemberRole
    from app.services.approvals import decide_approval as _decide

    p, db = _principal_from_ctx(ctx)
    try:
        _require_scopes(p, "approvals:write")
        if p.role not in (MemberRole.owner, MemberRole.admin) and not has_scope(p.scopes, "admin:keys"):
            raise RuntimeError(
                "deciding approvals requires owner/admin or admin:keys; "
                "suggestion: escalate to a human principal"
            )
        row = db.get(ApprovalRequest, approval_id)
        if not row or row.workspace_id != p.workspace.id:
            raise RuntimeError("not found")
        if row.status != ApprovalStatus.pending:
            raise RuntimeError(f"approval is already {row.status.value}")
        row = _decide(db, p, row, approve=approve, note=note, execute=execute)
        return _serialize(row)
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Compound tools (P1.1) + ACP boot
# ---------------------------------------------------------------------------


@mcp.tool()
def load_context(ctx: Context, sections: str | None = None) -> dict:
    """Boot into a workspace — ACP context pack (schema, pipelines, open work, policies, scopes).

    Requires any authenticated key. Pass sections as comma-separated names to thin the pack.
    Scope: any (authenticated). Prefer this before inventing field names.
    """
    from app.services.context_pack import build_context_pack

    p, db = _principal_from_ctx(ctx)
    try:
        sec = {s.strip() for s in sections.split(",")} if sections else None
        return build_context_pack(db, p, sections=sec)
    finally:
        db.close()


@mcp.tool()
def morning_briefing(ctx: Context, stale_days: int = 14) -> dict:
    """Open work snapshot: due tasks, stale deals, pending approvals, recent timeline.

    Scopes: tasks:read, deals:read, approvals:read, timeline:read (or *).
    """
    from datetime import timedelta

    from app.models import ApprovalRequest, ApprovalStatus, Deal, DealStatus, Task, TaskStatus, TimelineEvent

    p, db = _principal_from_ctx(ctx)
    try:
        _require_scopes(p, "tasks:read")
        _require_scopes(p, "deals:read")
        now = datetime.now(UTC)
        week = now + timedelta(days=7)
        due = db.scalars(
            select(Task)
            .where(
                Task.workspace_id == p.workspace.id,
                Task.deleted_at.is_(None),
                Task.status.in_([TaskStatus.open, TaskStatus.in_progress]),
                Task.due_at.is_not(None),
                Task.due_at <= week,
            )
            .order_by(Task.due_at.asc())
            .limit(20)
        ).all()
        stale = db.scalars(
            select(Deal)
            .where(
                Deal.workspace_id == p.workspace.id,
                Deal.deleted_at.is_(None),
                Deal.status == DealStatus.open,
                Deal.updated_at < now - timedelta(days=stale_days),
            )
            .order_by(Deal.updated_at.asc())
            .limit(20)
        ).all()
        pending = []
        if has_scope(p.scopes, "approvals:read"):
            pending = list(
                db.scalars(
                    select(ApprovalRequest)
                    .where(
                        ApprovalRequest.workspace_id == p.workspace.id,
                        ApprovalRequest.status == ApprovalStatus.pending,
                        ApprovalRequest.deleted_at.is_(None),
                    )
                    .order_by(ApprovalRequest.created_at.desc())
                    .limit(20)
                ).all()
            )
        recent = db.scalars(
            select(TimelineEvent)
            .where(TimelineEvent.workspace_id == p.workspace.id)
            .order_by(TimelineEvent.created_at.desc())
            .limit(15)
        ).all()
        return {
            "as_of": now.isoformat(),
            "tasks_due": [_serialize(t) for t in due],
            "stale_deals": [_serialize(d) for d in stale],
            "pending_approvals": [_serialize(a) for a in pending],
            "recent_timeline": [
                {
                    "event_type": e.event_type,
                    "entity_type": e.entity_type.value if e.entity_type else None,
                    "entity_id": e.entity_id,
                    "created_at": e.created_at.isoformat() if e.created_at else None,
                }
                for e in recent
            ],
        }
    finally:
        db.close()


@mcp.tool()
def entity_context(
    ctx: Context,
    entity_type: str,
    entity_ref: str,
    timeline_limit: int = 40,
) -> dict:
    """Coherent business-state bundle for one entity (company, contact, deal, lead).

    Pass UUID or human ref (company name/domain, contact email, deal name).
    Scopes: timeline:read plus each resource section (companies:read, contacts:read, …).
    """
    from app.services.entity_context import build_entity_context

    p, db = _principal_from_ctx(ctx)
    try:
        _require_scopes(p, "timeline:read")
        return build_entity_context(
            db, p.workspace.id, entity_type, entity_ref, scopes=p.scopes, timeline_limit=timeline_limit
        )
    except ValueError as e:
        raise RuntimeError(str(e)) from e
    finally:
        db.close()


@mcp.tool()
def agent_activity(
    ctx: Context,
    since: str,
    until: str | None = None,
    agent_api_key_id: str | None = None,
    entity_type: str | None = None,
    event_type_prefix: str | None = None,
) -> dict:
    """Workforce facts aggregated from timeline since ``since`` (ISO). Not orchestration analytics."""
    from app.services.agent_activity import build_agent_activity

    p, db = _principal_from_ctx(ctx)
    try:
        _require_scopes(p, "timeline:read")
        since_dt = datetime.fromisoformat(since.replace("Z", "+00:00"))
        until_dt = (
            datetime.fromisoformat(until.replace("Z", "+00:00")) if until else None
        )
        return build_agent_activity(
            db,
            p.workspace.id,
            since=since_dt,
            until=until_dt,
            agent_api_key_id=agent_api_key_id,
            entity_type=entity_type,
            event_type_prefix=event_type_prefix,
        )
    finally:
        db.close()


@mcp.tool()
def list_agents(ctx: Context) -> dict:
    """List workspace agent identities (API keys with agent roster conventions). Scope: workspace:read."""
    from app.services.agent_activity import list_workspace_agents

    p, db = _principal_from_ctx(ctx)
    try:
        _require_scopes(p, "workspace:read")
        return {"agents": list_workspace_agents(db, p.workspace.id)}
    finally:
        db.close()


@mcp.tool()
def explain_change(
    ctx: Context,
    entity_type: str,
    entity_id: str,
    event_id: int | None = None,
    since: str | None = None,
    limit: int = 20,
) -> dict:
    """Evidence chain: timeline with actor_label plus audit log entries for an entity."""
    from app.services.explain_change import explain_change as _explain

    p, db = _principal_from_ctx(ctx)
    try:
        _require_scopes(p, "timeline:read")
        since_dt = datetime.fromisoformat(since.replace("Z", "+00:00")) if since else None
        return _explain(
            db,
            p.workspace.id,
            entity_type,
            entity_id,
            event_id=event_id,
            since=since_dt,
            limit=limit,
        )
    finally:
        db.close()


@mcp.tool()
def upsert_account_map(
    ctx: Context,
    company_name: str,
    company_domain: str | None = None,
    contacts: list[dict] | None = None,
    relationships: list[dict] | None = None,
    company_external_id: str | None = None,
    idempotency_key: str | None = None,
) -> dict:
    """Create/update a company, contacts, and typed relationships in one call.

    contacts: [{first_name, last_name, email, title, external_id?, …}]
    relationships: [{source_type, source_email|source_id, target_type, target_id|target_email,
                     relation_type}] — source/target can reference emails from this batch.

    Scopes: companies:write, contacts:write, relationships:write.
    """
    p, db = _principal_from_ctx(ctx)
    try:
        _require_scopes(p, "companies:write")
        _require_scopes(p, "contacts:write")
        args = {
            "company_name": company_name,
            "company_domain": company_domain,
            "contacts": contacts,
            "relationships": relationships,
            "company_external_id": company_external_id,
        }
        replay, save = mcp_idempotency(
            db, p, tool="upsert_account_map", idempotency_key=idempotency_key, args=args
        )
        if replay is not None:
            return replay

        company = None
        if company_external_id:
            company = db.scalar(
                select(Company).where(
                    Company.workspace_id == p.workspace.id,
                    Company.external_id == company_external_id,
                )
            )
        if company is None and company_domain:
            company = db.scalar(
                select(Company).where(
                    Company.workspace_id == p.workspace.id,
                    func.lower(Company.domain) == company_domain.lower(),
                )
            )
        if company is None:
            company = Company(
                workspace_id=p.workspace.id,
                name=company_name,
                domain=company_domain,
                external_id=company_external_id,
            )
            db.add(company)
            db.flush()
            _record_event(
                db,
                p,
                event_type="company.created",
                entity_type=EntityType.company,
                entity_id=company.id,
                payload={"via": "upsert_account_map"},
            )
        else:
            company.name = company_name or company.name
            if company_domain:
                company.domain = company_domain

        email_to_id: dict[str, str] = {}
        contact_ids: list[str] = []
        for cdata in contacts or []:
            email = cdata.get("email")
            existing = None
            if cdata.get("external_id"):
                existing = db.scalar(
                    select(Contact).where(
                        Contact.workspace_id == p.workspace.id,
                        Contact.external_id == cdata["external_id"],
                    )
                )
            if existing is None and email:
                existing = db.scalar(
                    select(Contact).where(
                        Contact.workspace_id == p.workspace.id,
                        func.lower(Contact.email) == email.lower(),
                    )
                )
            if existing:
                for k in ("first_name", "last_name", "phone", "title"):
                    if cdata.get(k) is not None:
                        setattr(existing, k, cdata[k])
                existing.company_id = company.id
                contact_ids.append(existing.id)
                if email:
                    email_to_id[email.lower()] = existing.id
            else:
                c = Contact(
                    workspace_id=p.workspace.id,
                    first_name=cdata.get("first_name"),
                    last_name=cdata.get("last_name"),
                    email=email,
                    phone=cdata.get("phone"),
                    title=cdata.get("title"),
                    company_id=company.id,
                    external_id=cdata.get("external_id"),
                    tags=cdata.get("tags") or [],
                    data=cdata.get("data") or {},
                )
                db.add(c)
                db.flush()
                contact_ids.append(c.id)
                if email:
                    email_to_id[email.lower()] = c.id
                _record_event(
                    db,
                    p,
                    event_type="contact.created",
                    entity_type=EntityType.contact,
                    entity_id=c.id,
                    payload={"via": "upsert_account_map"},
                )

        rel_ids: list[str] = []
        for r in relationships or []:
            st = r.get("source_type", "contact")
            tt = r.get("target_type", "company")
            sid = r.get("source_id")
            tid = r.get("target_id")
            if not sid and r.get("source_email"):
                sid = email_to_id.get(r["source_email"].lower())
            if not tid and r.get("target_email"):
                tid = email_to_id.get(r["target_email"].lower())
            if not tid and tt == "company":
                tid = company.id
            if not sid or not tid:
                continue
            rel = Relationship(
                workspace_id=p.workspace.id,
                source_type=EntityType(st),
                source_id=sid,
                target_type=EntityType(tt),
                target_id=tid,
                relation_type=r.get("relation_type") or "works_at",
            )
            db.add(rel)
            db.flush()
            rel_ids.append(rel.id)

        db.commit()
        out = {
            "company_id": company.id,
            "contact_ids": contact_ids,
            "relationship_ids": rel_ids,
        }
        save(201, out)
        return out
    finally:
        db.close()


@mcp.tool()
def advance_deal(
    ctx: Context,
    deal_id: str,
    stage_slug: str,
    activity_kind: str | None = "note",
    activity_subject: str | None = None,
    activity_body: str | None = None,
    task_title: str | None = None,
    task_due_at: datetime | None = None,
    idempotency_key: str | None = None,
) -> dict:
    """Move a deal to a stage by slug; optionally log an activity and create a follow-up task.

    Scopes: deals:write (+ activities:write / tasks:write if those are set).
    """
    p, db = _principal_from_ctx(ctx)
    try:
        _require_scopes(p, "deals:write")
        args = {
            "deal_id": deal_id,
            "stage_slug": stage_slug,
            "activity_kind": activity_kind,
            "activity_subject": activity_subject,
            "activity_body": activity_body,
            "task_title": task_title,
        }
        replay, save = mcp_idempotency(db, p, tool="advance_deal", idempotency_key=idempotency_key, args=args)
        if replay is not None:
            return replay

        deal = db.get(Deal, deal_id)
        if not deal or deal.workspace_id != p.workspace.id:
            raise RuntimeError("deal not found")
        stage = db.scalar(
            select(Stage).where(Stage.pipeline_id == deal.pipeline_id, Stage.slug == stage_slug)
        )
        if not stage:
            raise RuntimeError(f"stage slug not found in deal pipeline: {stage_slug}")
        old = deal.stage_id
        deal.stage_id = stage.id
        if stage.is_won:
            deal.status = DealStatus.won
            deal.closed_at = datetime.now(UTC)
        elif stage.is_lost:
            deal.status = DealStatus.lost
            deal.closed_at = datetime.now(UTC)
        _record_event(
            db,
            p,
            event_type="deal.stage_changed",
            entity_type=EntityType.deal,
            entity_id=deal.id,
            payload={"from_stage_id": old, "to_stage_id": stage.id, "via": "advance_deal"},
        )
        activity_id = None
        if activity_subject or activity_body:
            _require_scopes(p, "activities:write")
            act = Activity(
                workspace_id=p.workspace.id,
                kind=activity_kind or "note",
                subject=activity_subject,
                body=activity_body,
                entity_type=EntityType.deal,
                entity_id=deal.id,
            )
            db.add(act)
            db.flush()
            activity_id = act.id
        task_id = None
        if task_title:
            _require_scopes(p, "tasks:write")
            t = Task(
                workspace_id=p.workspace.id,
                title=task_title,
                due_at=task_due_at,
                entity_type=EntityType.deal,
                entity_id=deal.id,
                status=TaskStatus.open,
            )
            db.add(t)
            db.flush()
            task_id = t.id
        db.commit()
        db.refresh(deal)
        out = {
            "deal": _serialize(deal),
            "stage_slug": stage_slug,
            "activity_id": activity_id,
            "task_id": task_id,
        }
        save(200, out)
        return out
    finally:
        db.close()


@mcp.tool()
def log_interaction(
    ctx: Context,
    kind: str,
    subject: str | None = None,
    body: str | None = None,
    entity_type: str | None = None,
    entity_id: str | None = None,
    note_body: str | None = None,
    occurred_at: datetime | None = None,
    idempotency_key: str | None = None,
) -> dict:
    """Log a call/email/meeting activity; optionally attach a note on the same entity.

    kind: call | meeting | email_outbound | email_inbound | note | other
    Scopes: activities:write (+ notes:write if note_body set).
    """
    p, db = _principal_from_ctx(ctx)
    try:
        _require_scopes(p, "activities:write")
        args = {
            "kind": kind,
            "subject": subject,
            "body": body,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "note_body": note_body,
        }
        replay, save = mcp_idempotency(
            db, p, tool="log_interaction", idempotency_key=idempotency_key, args=args
        )
        if replay is not None:
            return replay
        et = EntityType(entity_type) if entity_type else None
        act = Activity(
            workspace_id=p.workspace.id,
            kind=kind,
            subject=subject,
            body=body,
            entity_type=et,
            entity_id=entity_id,
            occurred_at=occurred_at or datetime.now(UTC),
        )
        db.add(act)
        db.flush()
        _record_event(
            db,
            p,
            event_type="activity.created",
            entity_type=et or EntityType.activity,
            entity_id=act.id if et is None else (entity_id or act.id),
            payload={"activity_id": act.id, "via": "log_interaction"},
        )
        note_id = None
        if note_body and entity_type and entity_id:
            _require_scopes(p, "notes:write")
            n = Note(
                workspace_id=p.workspace.id,
                body=note_body,
                entity_type=et,
                entity_id=entity_id,
            )
            db.add(n)
            db.flush()
            note_id = n.id
        db.commit()
        out = {"activity_id": act.id, "note_id": note_id}
        save(201, out)
        return out
    finally:
        db.close()


# ---------------------------------------------------------------------------
# P2: Leads, views, quotes
# ---------------------------------------------------------------------------


@mcp.tool()
def create_lead(
    ctx: Context,
    email: str | None = None,
    first_name: str | None = None,
    last_name: str | None = None,
    company_name: str | None = None,
    company_domain: str | None = None,
    source: str | None = None,
    phone: str | None = None,
    title: str | None = None,
    score: float | None = None,
    tags: list[str] | None = None,
    external_id: str | None = None,
    idempotency_key: str | None = None,
) -> dict:
    """Create an inbound lead. Scopes: leads:write."""
    from app.models import Lead, LeadStatus

    p, db = _principal_from_ctx(ctx)
    try:
        _require_scopes(p, "leads:write")
        args = {
            "email": email,
            "first_name": first_name,
            "last_name": last_name,
            "company_name": company_name,
            "company_domain": company_domain,
            "source": source,
        }
        replay, save = mcp_idempotency(db, p, tool="create_lead", idempotency_key=idempotency_key, args=args)
        if replay is not None:
            return replay
        row = Lead(
            workspace_id=p.workspace.id,
            email=email,
            first_name=first_name,
            last_name=last_name,
            company_name=company_name,
            company_domain=company_domain,
            source=source,
            phone=phone,
            title=title,
            score=score,
            tags=tags or [],
            external_id=external_id,
            status=LeadStatus.new,
        )
        db.add(row)
        db.flush()
        _record_event(
            db,
            p,
            event_type="lead.created",
            entity_type=EntityType.lead,
            entity_id=row.id,
            payload={"via": "mcp"},
        )
        db.commit()
        db.refresh(row)
        out = _serialize(row)
        save(201, out)
        return out
    finally:
        db.close()


@mcp.tool()
def search_leads(
    ctx: Context,
    query: str | None = None,
    status: str | None = None,
    email: str | None = None,
    limit: int = 25,
) -> list[dict]:
    """Search leads. Scopes: leads:read."""
    from app.models import Lead

    p, db = _principal_from_ctx(ctx)
    try:
        _require_scopes(p, "leads:read")
        q = select(Lead).where(Lead.workspace_id == p.workspace.id, Lead.deleted_at.is_(None))
        if status:
            q = q.where(Lead.status == status)
        if email:
            q = q.where(func.lower(Lead.email) == email.lower())
        if query:
            like = f"%{query.lower()}%"
            q = q.where(
                or_(
                    func.lower(Lead.first_name).like(like),
                    func.lower(Lead.last_name).like(like),
                    func.lower(Lead.email).like(like),
                    func.lower(Lead.company_name).like(like),
                )
            )
        q = q.order_by(Lead.created_at.desc()).limit(min(limit, 200))
        return [_serialize(r) for r in db.scalars(q).all()]
    finally:
        db.close()


@mcp.tool()
def convert_lead(
    ctx: Context,
    lead_id: str,
    create_company: bool = True,
    create_deal: bool = False,
    deal_name: str | None = None,
    pipeline_id: str | None = None,
    amount: float | None = None,
) -> dict:
    """Convert lead → contact (+ company/deal). Scopes: leads:write, contacts:write."""
    from app.models import Lead
    from app.services.leads import convert_lead as _convert

    p, db = _principal_from_ctx(ctx)
    try:
        _require_scopes(p, "leads:write")
        _require_scopes(p, "contacts:write")
        row = db.get(Lead, lead_id)
        if not row or row.workspace_id != p.workspace.id:
            raise RuntimeError("lead not found")
        return _convert(
            db,
            p,
            row,
            create_company=create_company,
            create_deal=create_deal,
            deal_name=deal_name,
            pipeline_id=pipeline_id,
            amount=amount,
        )
    finally:
        db.close()


@mcp.tool()
def list_views(ctx: Context) -> list[dict]:
    """List saved views (seeds defaults). Scopes: views:read."""
    from app.models import SavedView
    from app.routers.views import ensure_default_views

    p, db = _principal_from_ctx(ctx)
    try:
        _require_scopes(p, "views:read")
        ensure_default_views(db, p.workspace.id)
        rows = db.scalars(
            select(SavedView).where(
                SavedView.workspace_id == p.workspace.id,
                SavedView.deleted_at.is_(None),
            )
        ).all()
        return [_serialize(r) for r in rows]
    finally:
        db.close()


@mcp.tool()
def run_view(ctx: Context, view_slug: str, limit: int = 50) -> dict:
    """Run a saved view by slug (e.g. open_deals, stale_deals, new_leads). Scopes: views:read."""
    from app.models import SavedView
    from app.routers.views import ensure_default_views
    from app.services.views import run_view as _run

    p, db = _principal_from_ctx(ctx)
    try:
        _require_scopes(p, "views:read")
        ensure_default_views(db, p.workspace.id)
        row = db.scalar(
            select(SavedView).where(
                SavedView.workspace_id == p.workspace.id,
                SavedView.slug == view_slug,
                SavedView.deleted_at.is_(None),
            )
        )
        if not row:
            raise RuntimeError(f"view not found: {view_slug}")
        items = _run(
            db,
            p.workspace.id,
            entity_type=row.entity_type,
            filters=row.filters or [],
            sort=row.sort or [],
            limit=limit,
        )
        return {
            "view": row.slug,
            "entity_type": row.entity_type,
            "count": len(items),
            "items": [_serialize(i) for i in items],
        }
    finally:
        db.close()


@mcp.tool()
def create_quote(
    ctx: Context,
    deal_id: str,
    name: str,
    lines: list[dict] | None = None,
    currency: str = "USD",
    notes: str | None = None,
    idempotency_key: str | None = None,
) -> dict:
    """Create a draft quote on a deal with optional line items.
    lines: [{name, unit_price, quantity?, product_id?}]. Scopes: quotes:write.
    """
    from app.models import Deal, Quote, QuoteLineItem
    from app.routers.quotes import _materialize_line, _recalc
    from app.schemas import QuoteLineIn

    p, db = _principal_from_ctx(ctx)
    try:
        _require_scopes(p, "quotes:write")
        args = {"deal_id": deal_id, "name": name, "lines": lines}
        replay, save = mcp_idempotency(db, p, tool="create_quote", idempotency_key=idempotency_key, args=args)
        if replay is not None:
            return replay
        deal = db.get(Deal, deal_id)
        if not deal or deal.workspace_id != p.workspace.id:
            raise RuntimeError("deal not found")
        max_v = db.scalar(
            select(func.coalesce(func.max(Quote.version), 0)).where(
                Quote.deal_id == deal.id, Quote.deleted_at.is_(None)
            )
        )
        row = Quote(
            workspace_id=p.workspace.id,
            deal_id=deal.id,
            name=name,
            version=int(max_v or 0) + 1,
            currency=currency,
            notes=notes,
        )
        db.add(row)
        db.flush()
        for raw in lines or []:
            line = QuoteLineIn(**raw)
            fields = _materialize_line(db, p.workspace.id, line)
            db.add(QuoteLineItem(quote_id=row.id, **fields))
        db.flush()
        _recalc(db, row)
        db.commit()
        db.refresh(row)
        out = _serialize(row)
        save(201, out)
        return out
    finally:
        db.close()


@mcp.tool()
def set_quote_status(
    ctx: Context,
    quote_id: str,
    status: str,
    sync_deal_amount: bool = False,
) -> dict:
    """Set quote status (draft|sent|accepted|rejected|expired). Scopes: quotes:write."""
    from app.models import Deal, Quote, QuoteStatus

    p, db = _principal_from_ctx(ctx)
    try:
        _require_scopes(p, "quotes:write")
        row = db.get(Quote, quote_id)
        if not row or row.workspace_id != p.workspace.id:
            raise RuntimeError("quote not found")
        st = QuoteStatus(status)
        row.status = st
        now = datetime.now(UTC)
        if st == QuoteStatus.sent:
            row.sent_at = now
        if st == QuoteStatus.accepted:
            row.accepted_at = now
            if sync_deal_amount:
                deal = db.get(Deal, row.deal_id)
                if deal:
                    deal.amount = row.total
                    deal.currency = row.currency
        db.commit()
        db.refresh(row)
        return _serialize(row)
    finally:
        db.close()


@mcp.tool()
def list_policies(ctx: Context) -> dict:
    """Read workspace policies (approvals, required_fields, auto_tasks, block)."""
    from app.services.policies import get_policies

    p, db = _principal_from_ctx(ctx)
    try:
        return {"workspace_id": p.workspace.id, "policies": get_policies(p.workspace)}
    finally:
        db.close()


@mcp.tool()
def start_job(ctx: Context, job_type: str, input: dict | None = None, run_async: bool = True) -> dict:
    """Start an async job (ingest|export|merge|custom). Scopes: jobs:write."""
    from app.services.jobs import _run_job, create_job, enqueue

    p, db = _principal_from_ctx(ctx)
    try:
        _require_scopes(p, "jobs:write")
        job = create_job(
            db,
            workspace_id=p.workspace.id,
            job_type=job_type,
            input_data=input or {},
            actor_user_id=p.user_id,
            actor_api_key_id=p.api_key_id,
        )
        if run_async:
            enqueue(job.id)
        else:
            _run_job(job.id)
            db.refresh(job)
        return {
            "id": job.id,
            "status": job.status.value,
            "job_type": job.job_type,
            "progress": float(job.progress or 0),
        }
    finally:
        db.close()


@mcp.tool()
def get_job(ctx: Context, job_id: str) -> dict:
    """Poll a job by id. Scopes: jobs:read."""
    from app.models import Job

    p, db = _principal_from_ctx(ctx)
    try:
        _require_scopes(p, "jobs:read")
        job = db.get(Job, job_id)
        if not job or job.workspace_id != p.workspace.id:
            raise RuntimeError("job not found")
        return {
            "id": job.id,
            "status": job.status.value,
            "job_type": job.job_type,
            "progress": float(job.progress or 0),
            "result": job.result or {},
            "error": job.error,
        }
    finally:
        db.close()


@mcp.tool()
def entity_as_of(ctx: Context, entity_type: str, entity_id: str, ts: str) -> dict:
    """Reconstruct entity state as of an ISO timestamp via timeline. Scopes: timeline:read."""
    from app.services.forensics import entity_as_of as _as_of

    p, db = _principal_from_ctx(ctx)
    try:
        _require_scopes(p, "timeline:read")
        at = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return _as_of(db, p.workspace.id, entity_type, entity_id, at)
    finally:
        db.close()


@mcp.tool()
def search_audit(
    ctx: Context,
    action: str | None = None,
    entity_type: str | None = None,
    entity_id: str | None = None,
    limit: int = 50,
) -> dict:
    """Search the audit log. Scopes: timeline:read."""
    from app.services.forensics import search_audit as _search

    p, db = _principal_from_ctx(ctx)
    try:
        _require_scopes(p, "timeline:read")
        return {
            "items": _search(
                db,
                p.workspace.id,
                action=action,
                entity_type=entity_type,
                entity_id=entity_id,
                limit=limit,
            )
        }
    finally:
        db.close()


@mcp.tool()
def import_crm(
    ctx: Context,
    source: str,
    payload: dict | list,
    mapping: dict | None = None,
    dry_run: bool = False,
) -> dict:
    """One-shot CRM import. source: hubspot|salesforce|pipedrive|attio|generic.
    Scopes: export:write. Prefer dry_run=true first.
    """
    from app.services.importers import run_crm_import

    p, db = _principal_from_ctx(ctx)
    try:
        _require_scopes(p, "export:write")
        result = run_crm_import(db, p, source=source, payload=payload, mapping=mapping, dry_run=dry_run)
        return {
            "source": result.source,
            "dry_run": result.dry_run,
            "created": result.created,
            "updated": result.updated,
            "skipped": result.skipped,
            "errors": result.errors,
        }
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Custom fields (workspace-tunable schema on core entities)
# ---------------------------------------------------------------------------

_ALLOWED_FIELD_TYPES = {"string", "text", "number", "bool", "date", "url", "email", "select"}


def _require_adminish(principal: Principal) -> None:
    """Custom-field mutations match REST: owner/admin only."""
    from app.models import MemberRole

    role = principal.role
    role_v = role.value if hasattr(role, "value") else str(role)
    if role_v not in {MemberRole.owner.value, MemberRole.admin.value, "owner", "admin"}:
        raise RuntimeError(
            "custom field mutations require owner/admin API key role; "
            "suggestion: mint a key with role=owner|admin"
        )


@mcp.tool()
def list_custom_fields(
    ctx: Context,
    entity_type: str | None = None,
) -> list[dict]:
    """List workspace custom field definitions. Optional entity_type filter
    (contact|company|deal|…). Scopes: custom_fields:read.
    """
    from app.models import CustomFieldDefinition, EntityType

    p, db = _principal_from_ctx(ctx)
    try:
        _require_scopes(p, "custom_fields:read")
        q = select(CustomFieldDefinition).where(CustomFieldDefinition.workspace_id == p.workspace.id)
        if entity_type:
            try:
                et = EntityType(entity_type)
            except ValueError as exc:
                raise RuntimeError(
                    f"unknown entity_type {entity_type!r}; " f"use one of {[e.value for e in EntityType]}"
                ) from exc
            q = q.where(CustomFieldDefinition.entity_type == et)
        q = q.order_by(CustomFieldDefinition.entity_type, CustomFieldDefinition.name)
        return [_serialize(r) for r in db.scalars(q).all()]
    finally:
        db.close()


@mcp.tool()
def create_custom_field(
    ctx: Context,
    entity_type: str,
    name: str,
    label: str,
    field_type: str = "string",
    required: bool = False,
    options: list[str] | None = None,
    description: str | None = None,
    default_value: dict | None = None,
) -> dict:
    """Define a custom field on a core entity (contact, company, deal, …).
    Values are stored on each row's `data` JSONB under this name.
    field_type: string|text|number|bool|date|url|email|select.
    Requires owner/admin role + custom_fields:write.
    """
    from app.models import CustomFieldDefinition, EntityType

    p, db = _principal_from_ctx(ctx)
    try:
        _require_scopes(p, "custom_fields:write")
        _require_adminish(p)
        if field_type not in _ALLOWED_FIELD_TYPES:
            raise RuntimeError(f"field_type must be one of: {sorted(_ALLOWED_FIELD_TYPES)}")
        if not name or not name[0].islower() or not all(c.isalnum() or c == "_" for c in name):
            raise RuntimeError("name must be snake_case starting with a letter (e.g. linkedin_url)")
        try:
            et = EntityType(entity_type)
        except ValueError as exc:
            raise RuntimeError(f"unknown entity_type {entity_type!r}") from exc
        row = CustomFieldDefinition(
            workspace_id=p.workspace.id,
            entity_type=et,
            name=name,
            label=label,
            field_type=field_type,
            required=required,
            default_value=default_value or {},
            options=options or [],
            description=description,
        )
        db.add(row)
        try:
            db.flush()
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            raise RuntimeError(f"a field named '{name}' already exists on {entity_type}") from exc
        db.commit()
        db.refresh(row)
        return _serialize(row)
    finally:
        db.close()


@mcp.tool()
def update_custom_field(
    ctx: Context,
    field_id: str,
    label: str | None = None,
    field_type: str | None = None,
    required: bool | None = None,
    options: list[str] | None = None,
    description: str | None = None,
    default_value: dict | None = None,
) -> dict:
    """Patch a custom field definition. Cannot rename `name` or change entity_type
    (delete + recreate). Requires owner/admin + custom_fields:write.
    """
    from app.models import CustomFieldDefinition

    p, db = _principal_from_ctx(ctx)
    try:
        _require_scopes(p, "custom_fields:write")
        _require_adminish(p)
        row = db.get(CustomFieldDefinition, field_id)
        if not row or row.workspace_id != p.workspace.id:
            raise RuntimeError(f"custom field not found: {field_id}")
        if field_type is not None:
            if field_type not in _ALLOWED_FIELD_TYPES:
                raise RuntimeError(f"field_type must be one of: {sorted(_ALLOWED_FIELD_TYPES)}")
            row.field_type = field_type
        if label is not None:
            row.label = label
        if required is not None:
            row.required = required
        if options is not None:
            row.options = options
        if description is not None:
            row.description = description
        if default_value is not None:
            row.default_value = default_value
        db.commit()
        db.refresh(row)
        return _serialize(row)
    finally:
        db.close()


@mcp.tool()
def delete_custom_field(ctx: Context, field_id: str) -> dict:
    """Delete a custom field definition (does not scrub values already written
    into row `data`). Requires owner/admin + custom_fields:write.
    """
    from app.models import CustomFieldDefinition

    p, db = _principal_from_ctx(ctx)
    try:
        _require_scopes(p, "custom_fields:write")
        _require_adminish(p)
        row = db.get(CustomFieldDefinition, field_id)
        if not row or row.workspace_id != p.workspace.id:
            raise RuntimeError(f"custom field not found: {field_id}")
        db.delete(row)
        db.commit()
        return {"ok": True, "deleted": field_id}
    finally:
        db.close()


@mcp.tool()
def list_object_types(ctx: Context) -> list[dict]:
    """List workspace custom object types (moldable model). Scopes: custom_fields:read."""
    from app.models import CustomObjectType

    p, db = _principal_from_ctx(ctx)
    try:
        _require_scopes(p, "custom_fields:read")
        q = (
            select(CustomObjectType)
            .where(
                CustomObjectType.workspace_id == p.workspace.id,
                CustomObjectType.deleted_at.is_(None),
            )
            .order_by(CustomObjectType.slug)
        )
        return [_serialize(r) for r in db.scalars(q).all()]
    finally:
        db.close()


@mcp.tool()
def create_object_type(
    ctx: Context,
    name: str,
    slug: str,
    fields: list[dict] | None = None,
    description: str | None = None,
) -> dict:
    """Define a custom object type. fields: [{name, label, type, required?}]. Scopes: custom_fields:write."""
    from app.models import CustomObjectType

    p, db = _principal_from_ctx(ctx)
    try:
        _require_scopes(p, "custom_fields:write")
        row = CustomObjectType(
            workspace_id=p.workspace.id,
            name=name,
            slug=slug,
            description=description,
            fields=fields or [],
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return _serialize(row)
    finally:
        db.close()


@mcp.tool()
def upsert_record(
    ctx: Context,
    object_slug: str,
    name: str | None = None,
    values: dict | None = None,
    external_id: str | None = None,
    related_entity_type: str | None = None,
    related_entity_id: str | None = None,
) -> dict:
    """Create/update a custom record by external_id. Scopes: custom_fields:write."""
    from app.models import CustomObjectType, CustomRecord

    p, db = _principal_from_ctx(ctx)
    try:
        _require_scopes(p, "custom_fields:write")
        t = db.scalar(
            select(CustomObjectType).where(
                CustomObjectType.workspace_id == p.workspace.id,
                CustomObjectType.slug == object_slug,
                CustomObjectType.deleted_at.is_(None),
            )
        )
        if not t:
            raise RuntimeError(f"object type not found: {object_slug}")
        existing = None
        if external_id:
            existing = db.scalar(
                select(CustomRecord).where(
                    CustomRecord.workspace_id == p.workspace.id,
                    CustomRecord.object_slug == object_slug,
                    CustomRecord.external_id == external_id,
                )
            )
        if existing:
            if name is not None:
                existing.name = name
            if values:
                existing.values = {**(existing.values or {}), **values}
            if related_entity_type:
                existing.related_entity_type = related_entity_type
            if related_entity_id:
                existing.related_entity_id = related_entity_id
            db.commit()
            db.refresh(existing)
            return _serialize(existing)
        row = CustomRecord(
            workspace_id=p.workspace.id,
            object_type_id=t.id,
            object_slug=object_slug,
            name=name,
            external_id=external_id,
            values=values or {},
            related_entity_type=related_entity_type,
            related_entity_id=related_entity_id,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return _serialize(row)
    finally:
        db.close()


@mcp.tool()
def search_records(
    ctx: Context,
    object_slug: str,
    query: str | None = None,
    limit: int = 25,
) -> list[dict]:
    """Search custom records. Scopes: custom_fields:read."""
    from app.models import CustomRecord

    p, db = _principal_from_ctx(ctx)
    try:
        _require_scopes(p, "custom_fields:read")
        q = select(CustomRecord).where(
            CustomRecord.workspace_id == p.workspace.id,
            CustomRecord.object_slug == object_slug,
            CustomRecord.deleted_at.is_(None),
        )
        if query:
            like = f"%{query.lower()}%"
            q = q.where(
                or_(
                    func.lower(CustomRecord.name).like(like),
                    func.lower(CustomRecord.external_id).like(like),
                )
            )
        q = q.order_by(CustomRecord.created_at.desc()).limit(min(limit, 200))
        return [_serialize(r) for r in db.scalars(q).all()]
    finally:
        db.close()


@mcp.tool()
def describe_schema(ctx: Context) -> dict:
    """Return core entity manifest plus this workspace's custom fields and
    custom object types so the agent can introspect tunable schema.
    """
    from app import __version__
    from app.models import CustomFieldDefinition, CustomObjectType
    from app.protocol import protocol_manifest
    from app.routers.schema import _ENTITIES, _EVENT_TYPES  # local import to avoid cycles

    p, db = _principal_from_ctx(ctx)
    try:
        custom_fields = [
            _serialize(r)
            for r in db.scalars(
                select(CustomFieldDefinition)
                .where(CustomFieldDefinition.workspace_id == p.workspace.id)
                .order_by(CustomFieldDefinition.entity_type, CustomFieldDefinition.name)
            ).all()
        ]
        object_types = [
            _serialize(r)
            for r in db.scalars(
                select(CustomObjectType)
                .where(
                    CustomObjectType.workspace_id == p.workspace.id,
                    CustomObjectType.deleted_at.is_(None),
                )
                .order_by(CustomObjectType.slug)
            ).all()
        ]
        return {
            "version": __version__,
            "protocols": protocol_manifest(),
            "entities": [e.model_dump() for e in _ENTITIES],
            "event_types": list(_EVENT_TYPES),
            "custom_fields": custom_fields,
            "custom_object_types": object_types,
            "hints": [
                "Prefer custom_fields for properties on contact/company/deal.",
                "Prefer custom_object_types for new nouns (Partner, Part, Milestone).",
                "Store values on row `data` for custom fields; use upsert_record for object records.",
                "Do not invent field names — use custom_fields + entities from this payload.",
            ],
        }
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


def _serialize(obj: Any) -> dict:
    """Flatten SQLAlchemy row into a JSON-safe dict."""
    if obj is None:
        return {}
    from decimal import Decimal

    out: dict[str, Any] = {}
    for col in obj.__table__.columns:
        v = getattr(obj, col.name)
        if isinstance(v, datetime):
            out[col.name] = v.isoformat()
        elif isinstance(v, Decimal):
            out[col.name] = float(v)
        elif hasattr(v, "value"):  # enum
            out[col.name] = v.value
        else:
            out[col.name] = v
    return out


def build_asgi_app():
    """Return the MCP streamable-HTTP ASGI app for mounting under FastAPI."""
    try:
        return mcp.streamable_http_app()
    except AttributeError:
        # older SDKs
        return mcp.sse_app()
