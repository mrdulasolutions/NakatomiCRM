"""MCP tool catalog for /schema — versioned separately from app SemVer."""

from __future__ import annotations

MCP_TOOLS_SCHEMA_VERSION = "1.1"

# Compound / Agent OS tools added in 1.0.10 — no sunset yet.
MCP_TOOLS_MANIFEST: dict = {
    "schema_version": MCP_TOOLS_SCHEMA_VERSION,
    "transport": "streamable-http",
    "path": "/mcp",
    "tools": {
        "load_context": {"since": "1.0", "scopes": ["authenticated"]},
        "entity_context": {"since": "1.0.10", "scopes": ["timeline:read", "resource reads per section"]},
        "morning_briefing": {"since": "1.0", "scopes": ["tasks:read", "deals:read", "approvals:read"]},
        "agent_activity": {"since": "1.0.10", "scopes": ["timeline:read"]},
        "list_agents": {"since": "1.0.10", "scopes": ["workspace:read"]},
        "explain_change": {"since": "1.0.10", "scopes": ["timeline:read"]},
        "upsert_account_map": {
            "since": "1.0",
            "scopes": ["companies:write", "contacts:write", "relationships:write"],
        },
        "advance_deal": {"since": "1.0", "scopes": ["deals:write"]},
        "log_interaction": {"since": "1.0", "scopes": ["activities:write"]},
    },
    "scheduled_sunsets": [],
    "policy": "Breaking MCP tool renames require MCP_TOOLS_SCHEMA_VERSION bump + 90d notice in scheduled_sunsets.",
}

MCP_RESOURCE_TEMPLATES: list[dict] = [
    {
        "uri_template": "crm://contact/{contact_id}",
        "since": "1.0.10",
        "scopes": ["contacts:read"],
        "rest_parity": "GET /contacts/{contact_id}",
    },
    {
        "uri_template": "crm://deal/{deal_id}",
        "since": "1.0.10",
        "scopes": ["deals:read"],
        "rest_parity": "GET /deals/{deal_id}",
    },
    {
        "uri_template": "crm://company/{company_id}",
        "since": "1.0.10",
        "scopes": ["companies:read"],
        "rest_parity": "GET /companies/{company_id}",
    },
]
