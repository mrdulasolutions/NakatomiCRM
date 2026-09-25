"""ACP — Agent Context Protocol pack builder.

A versioned machine-readable pack an agent loads once per session so it
stops inventing schema, policies, and open work.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import __version__
from app.deps import Principal
from app.models import (
    ApprovalRequest,
    ApprovalStatus,
    CustomFieldDefinition,
    Deal,
    DealStatus,
    Pipeline,
    Stage,
    Task,
    TaskStatus,
    WebhookDelivery,
)
from app.services.memory import enabled_connectors


def _json_hash(payload: dict) -> str:
    raw = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def build_context_pack(
    db: Session,
    principal: Principal,
    *,
    sections: set[str] | None = None,
) -> dict[str, Any]:
    """Build the ACP context pack.

    ``sections`` filters top-level keys (workspace + protocol always included).
    """
    want = sections or {
        "schema",
        "custom_fields",
        "pipelines",
        "views",
        "policies",
        "open_work",
        "event_types",
        "mcp",
        "a2a",
        "memory_connectors",
        "hints",
    }

    from app.routers.schema import _ENTITIES, _EVENT_TYPES

    ws = principal.workspace
    pack: dict[str, Any] = {
        "protocol": "nakatomi.acp/v1",
        "workspace": {"id": ws.id, "slug": ws.slug, "name": ws.name},
        "generated_at": datetime.now(UTC).isoformat(),
        "schema_version": __version__,
    }

    if "schema" in want:
        # Redact entity list slightly for readonly keys without write scopes
        entities = [e.model_dump() if hasattr(e, "model_dump") else e for e in _ENTITIES]
        pack["entities"] = entities

    if "custom_fields" in want:
        rows = db.scalars(
            select(CustomFieldDefinition).where(CustomFieldDefinition.workspace_id == ws.id)
        ).all()
        pack["custom_fields"] = [
            {
                "id": r.id,
                "entity_type": r.entity_type.value if hasattr(r.entity_type, "value") else r.entity_type,
                "name": r.name,
                "label": r.label,
                "field_type": r.field_type,
                "required": r.required,
                "options": r.options or [],
            }
            for r in rows
        ]

    if "pipelines" in want:
        pipes = db.scalars(select(Pipeline).where(Pipeline.workspace_id == ws.id)).all()
        pack["pipelines"] = []
        for pipe in pipes:
            stages = db.scalars(
                select(Stage).where(Stage.pipeline_id == pipe.id).order_by(Stage.position)
            ).all()
            pack["pipelines"].append(
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
                            "probability": float(s.probability or 0),
                            "is_won": s.is_won,
                            "is_lost": s.is_lost,
                        }
                        for s in stages
                    ],
                }
            )

    if "views" in want:
        # Saved views are P2 — ship empty list + seed names as hints for agents.
        pack["views"] = []
        pack["view_presets"] = [
            {"name": "open_deals", "entity": "deal", "filter": {"status": "open"}},
            {"name": "tasks_due_this_week", "entity": "task", "filter": {"status": "open", "due": "P7D"}},
            {"name": "pending_approvals", "entity": "approval", "filter": {"status": "pending"}},
        ]

    if "policies" in want:
        data = ws.data or {}
        policies = data.get("policies") or {}
        pack["policies"] = {
            "approvals": policies.get("approvals") or [],
            "scopes_on_this_key": list(principal.scopes),
            "role": principal.role.value if hasattr(principal.role, "value") else str(principal.role),
            "rate_limit": {
                "note": "Per-key override on ApiKey.rate_limit_per_minute; global API_KEY_RATE_LIMIT_PER_MINUTE",
            },
        }

    if "open_work" in want:
        now = datetime.now(UTC)
        week = now + timedelta(days=7)
        due_tasks = db.scalars(
            select(Task)
            .where(
                Task.workspace_id == ws.id,
                Task.deleted_at.is_(None),
                Task.status.in_([TaskStatus.open, TaskStatus.in_progress]),
                Task.due_at.is_not(None),
                Task.due_at <= week,
            )
            .order_by(Task.due_at.asc())
            .limit(25)
        ).all()
        stale_cutoff = now - timedelta(days=14)
        stale_deals = db.scalars(
            select(Deal)
            .where(
                Deal.workspace_id == ws.id,
                Deal.deleted_at.is_(None),
                Deal.status == DealStatus.open,
                Deal.updated_at < stale_cutoff,
            )
            .order_by(Deal.updated_at.asc())
            .limit(25)
        ).all()
        pending = db.scalars(
            select(ApprovalRequest)
            .where(
                ApprovalRequest.workspace_id == ws.id,
                ApprovalRequest.deleted_at.is_(None),
                ApprovalRequest.status == ApprovalStatus.pending,
            )
            .order_by(ApprovalRequest.created_at.desc())
            .limit(25)
        ).all()
        failed_wh = db.scalars(
            select(WebhookDelivery)
            .where(
                WebhookDelivery.workspace_id == ws.id,
                WebhookDelivery.status.in_(["failed", "dead"]),
            )
            .order_by(WebhookDelivery.created_at.desc())
            .limit(10)
        ).all()
        failed_out = [
            {
                "id": d.id,
                "status": d.status,
                "webhook_id": d.webhook_id,
                "event_type": d.event_type,
                "error": d.error,
            }
            for d in failed_wh
        ]

        pack["open_work"] = {
            "tasks_due": [
                {
                    "id": t.id,
                    "title": t.title,
                    "due_at": t.due_at.isoformat() if t.due_at else None,
                    "status": t.status.value if hasattr(t.status, "value") else t.status,
                    "entity_type": t.entity_type.value if t.entity_type else None,
                    "entity_id": t.entity_id,
                }
                for t in due_tasks
            ],
            "stale_deals": [
                {
                    "id": d.id,
                    "name": d.name,
                    "amount": float(d.amount) if d.amount is not None else None,
                    "updated_at": d.updated_at.isoformat() if d.updated_at else None,
                }
                for d in stale_deals
            ],
            "pending_approvals": [
                {
                    "id": a.id,
                    "action": a.action,
                    "reason": a.reason,
                    "created_at": a.created_at.isoformat() if a.created_at else None,
                }
                for a in pending
            ],
            "failed_webhooks": failed_out[:10],
        }

    if "event_types" in want:
        pack["event_types"] = list(_EVENT_TYPES)

    if "mcp" in want:
        pack["mcp"] = {
            "url": "/mcp",
            "tools": [
                "load_context",
                "entity_context",
                "morning_briefing",
                "agent_activity",
                "list_agents",
                "explain_change",
                "upsert_account_map",
                "advance_deal",
                "log_interaction",
                "search_contacts",
                "create_contact",
                "create_deal",
                "move_deal_stage",
                "forecast",
                "propose_action",
                "list_pending_approvals",
                "decide_approval",
                "describe_schema",
            ],
        }

    if "a2a" in want:
        pack["a2a"] = {
            "agent_card": "/.well-known/agent-card.json",
            "agent_card_legacy": "/.well-known/agent.json",
            "tasks_base": "/a2a/tasks",
            "binding": "rest",
        }

    if "memory_connectors" in want:
        pack["memory_connectors"] = list(enabled_connectors())

    if "hints" in want:
        pack["hints"] = [
            "Call load_context (or GET /acp/context) once per session before inventing fields",
            "Prefer external_id for upserts",
            "Soft-delete by default; hard delete needs resource:delete scope",
            "Send Idempotency-Key on writes (or idempotency_key on MCP mutators)",
            "email:send and admin:keys are not in member defaults — use propose_action for HITL",
            "Use morning_briefing for open work; use entity_context for account takeover",
            "Use advance_deal / upsert_account_map compound tools for multi-step writes",
        ]

    # Hash without volatile timestamps so ETag revalidation works within a session.
    stable = {k: v for k, v in pack.items() if k not in ("generated_at", "etag")}
    pack["etag"] = _json_hash(stable)
    return pack
