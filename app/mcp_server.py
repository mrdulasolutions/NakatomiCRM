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

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from sqlalchemy import func, or_, select

from app.db import SessionLocal
from app.deps import Principal
from app.models import (
    Activity,
    ApiKey,
    Company,
    Contact,
    Deal,
    DealStatus,
    EntityType,
    IngestRun,
    MemoryLink,
    Note,
    Pipeline,
    Relationship,
    Stage,
    Task,
    TaskStatus,
    TimelineEvent,
    User,
    Workspace,
)
from app.security import hash_api_key
from app.services.ingest import adapters as _ingest_adapters  # noqa: F401  — registers adapters
from app.services.ingest.base import run_ingest
from app.services.memory import enabled_connectors, get_connector

log = logging.getLogger("nakatomi.mcp")

# Two non-default settings:
#  - streamable_http_path='/'. Default is '/mcp', which when mounted under
#    our '/mcp' prefix would make the public URL /mcp/mcp. MCP clients
#    expect exactly /mcp/.
#  - TransportSecuritySettings.enable_dns_rebinding_protection=False. The
#    default whitelists only localhost and blocks everything else; our
#    Railway domain (or any remote host) gets rejected with a 500.
#    We're behind Railway's edge with TLS termination — the DNS-rebinding
#    attack model assumes a local-only server, which isn't our deploy.
mcp = FastMCP(
    "Nakatomi CRM",
    streamable_http_path="/",
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
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
    return Principal(user=user, api_key=key, workspace=ws, role=key.role), db


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
) -> dict:
    """Create a new contact."""
    p, db = _principal_from_ctx(ctx)
    try:
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
        return _serialize(c)
    finally:
        db.close()


@mcp.tool()
def update_contact(ctx: Context, contact_id: str, updates: dict) -> dict:
    """Patch an existing contact. ``updates`` may contain any field from the contact schema."""
    p, db = _principal_from_ctx(ctx)
    try:
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
) -> dict:
    p, db = _principal_from_ctx(ctx)
    try:
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
        return _serialize(c)
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Deal tools
# ---------------------------------------------------------------------------


@mcp.tool()
def list_pipelines(ctx: Context) -> list[dict]:
    p, db = _principal_from_ctx(ctx)
    try:
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
) -> dict:
    p, db = _principal_from_ctx(ctx)
    try:
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
        return _serialize(d)
    finally:
        db.close()


@mcp.tool()
def move_deal_stage(ctx: Context, deal_id: str, stage_slug: str) -> dict:
    """Move a deal to a new stage (by slug within its pipeline)."""
    p, db = _principal_from_ctx(ctx)
    try:
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
) -> dict:
    p, db = _principal_from_ctx(ctx)
    try:
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
        return _serialize(t)
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
def timeline(ctx: Context, entity_type: str, entity_id: str, limit: int = 50) -> list[dict]:
    """Return the most recent events for one entity."""
    p, db = _principal_from_ctx(ctx)
    try:
        rows = db.scalars(
            select(TimelineEvent)
            .where(
                TimelineEvent.workspace_id == p.workspace.id,
                TimelineEvent.entity_type == EntityType(entity_type),
                TimelineEvent.entity_id == entity_id,
            )
            .order_by(TimelineEvent.occurred_at.desc(), TimelineEvent.id.desc())
            .limit(min(limit, 500))
        ).all()
        return [
            {
                "id": r.id,
                "event_type": r.event_type,
                "occurred_at": r.occurred_at.isoformat(),
                "actor_user_id": r.actor_user_id,
                "actor_api_key_id": r.actor_api_key_id,
                "payload": r.payload,
            }
            for r in rows
        ]
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


@mcp.tool()
def describe_schema(ctx: Context) -> dict:
    """Return a summary of entities, fields, and event types so the agent can introspect."""
    from app import __version__
    from app.routers.schema import _ENTITIES, _EVENT_TYPES  # local import to avoid cycles

    return {
        "version": __version__,
        "entities": [e.model_dump() for e in _ENTITIES],
        "event_types": list(_EVENT_TYPES),
    }


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
