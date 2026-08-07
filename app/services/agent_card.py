"""Dynamic A2A Agent Card builder.

Serves both legacy ``/.well-known/agent.json`` and spec-preferred
``/.well-known/agent-card.json`` with the same payload. Base URL is taken
from the incoming request so Railway / local deploys need no rewrite.
"""

from __future__ import annotations

from typing import Any

from app import __version__

# Skills advertise compound capabilities (P1.1 tools + core surfaces).
_SKILLS: list[dict[str, Any]] = [
    {
        "id": "pipeline-ops",
        "name": "Pipeline operations",
        "description": "Create deals, advance stages, forecast, log pipeline activity.",
        "tags": ["deals", "forecast", "mcp"],
        "examples": ["Move ACME deal to negotiation", "Forecast 2026Q3"],
    },
    {
        "id": "contact-hygiene",
        "name": "Contact & company hygiene",
        "description": "Upsert contacts/companies, relationships, bulk ingest, merge duplicates.",
        "tags": ["contacts", "companies", "ingest"],
        "examples": ["Upsert account map for Acme Corp"],
    },
    {
        "id": "forecast",
        "name": "Forecast",
        "description": "Period rollups of open/won/lost weighted pipeline value.",
        "tags": ["forecast", "deals"],
        "examples": ["Forecast 2026Q2"],
    },
    {
        "id": "approvals-hitl",
        "name": "Human-in-the-loop approvals",
        "description": "Propose and decide sensitive actions (email.send, deal.won, custom).",
        "tags": ["approvals", "safety"],
        "examples": ["Propose email send for approval"],
    },
    {
        "id": "context-boot",
        "name": "Workspace context boot",
        "description": "Load ACP context pack: schema, pipelines, open work, policies, scopes.",
        "tags": ["acp", "context"],
        "examples": ["load_context for this workspace"],
    },
    {
        "id": "morning-briefing",
        "name": "Morning briefing",
        "description": "Due tasks, stale deals, pending approvals, recent timeline.",
        "tags": ["mcp", "ops"],
        "examples": ["Give me the morning briefing"],
    },
]


def build_agent_card(*, base_url: str, extended: bool = False) -> dict[str, Any]:
    """Return an A2A-shaped Agent Card.

    ``extended`` (authenticated) adds nakatomi-specific surface inventory
    without breaking card consumers that only read the core fields.
    """
    base = base_url.rstrip("/")
    card: dict[str, Any] = {
        "name": "Nakatomi CRM",
        "description": (
            "Headless, agent-native CRM. REST + MCP + A2A tasks + ACP context packs. "
            "Contacts, companies, deals, activities, notes, tasks, files, relationships, "
            "timeline, webhooks, memory connectors, HITL approvals."
        ),
        "version": __version__,
        "protocolVersion": "0.2.1",
        "url": f"{base}/a2a",
        "documentationUrl": f"{base}/llms.txt",
        "provider": {
            "organization": "MrDula Solutions",
            "url": "https://github.com/mrdulasolutions/NakatomiCRM",
        },
        "defaultInputModes": ["text", "text/plain", "application/json"],
        "defaultOutputModes": ["text", "text/plain", "application/json"],
        "capabilities": {
            "streaming": False,
            "pushNotifications": True,
            "stateTransitionHistory": True,
        },
        "skills": _SKILLS,
        "securitySchemes": {
            "bearer": {
                "type": "http",
                "scheme": "bearer",
                "bearerFormat": "API key nk_<prefix>_<secret> or JWT",
                "description": (
                    "Workspace API key (Authorization: Bearer nk_…) or user JWT "
                    "with X-Workspace header."
                ),
            }
        },
        "security": [{"bearer": []}],
        # Nakatomi extensions (non-breaking for strict A2A clients)
        "nakatomi": {
            "schema_version": "1.1",
            "transports": [
                {"type": "http", "base_url": f"{base}/", "openapi_url": f"{base}/openapi.json"},
                {
                    "type": "mcp",
                    "base_url": f"{base}/mcp",
                    "protocol_version": "2024-11-05",
                    "streamable_http": True,
                },
                {"type": "a2a", "base_url": f"{base}/a2a", "binding": "rest"},
                {"type": "acp", "context_url": f"{base}/acp/context"},
            ],
            "discovery": f"{base}/discovery",
            "agent_card": f"{base}/.well-known/agent-card.json",
            "agent_card_legacy": f"{base}/.well-known/agent.json",
            "safety": {
                "data_residency": "operator-controlled",
                "soft_delete": True,
                "audit_log": True,
                "scoped_api_keys": True,
                "hitl_approvals": True,
            },
        },
    }
    if extended:
        card["nakatomi"]["extended"] = True
        card["nakatomi"]["mcp_tools_hint"] = [
            "load_context",
            "morning_briefing",
            "upsert_account_map",
            "advance_deal",
            "log_interaction",
            "search_contacts",
            "create_deal",
            "forecast",
            "propose_action",
        ]
    return card
