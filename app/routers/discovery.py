"""Unified discovery index for agents."""

from __future__ import annotations

from fastapi import APIRouter, Request

from app import __version__
from app.services.agent_card import build_agent_card

router = APIRouter(tags=["discovery"])


def _base_url(request: Request) -> str:
    proto = request.headers.get("x-forwarded-proto") or request.url.scheme
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or request.url.netloc
    return f"{proto}://{host}"


@router.get("/discovery")
def discovery(request: Request) -> dict:
    """Single index of all agent-facing surfaces."""
    from app.protocol import protocol_manifest

    base = _base_url(request)
    return {
        "name": "Nakatomi CRM",
        "version": __version__,
        "protocol_stack": ["rest", "mcp", "a2a", "acp"],
        "protocols": protocol_manifest(),
        "links": {
            "health": f"{base}/health",
            "health_deep": f"{base}/health/deep",
            "openapi": f"{base}/openapi.json",
            "docs": f"{base}/docs",
            "schema": f"{base}/schema",
            "llms_txt": f"{base}/llms.txt",
            "agent_card": f"{base}/.well-known/agent-card.json",
            "agent_card_legacy": f"{base}/.well-known/agent.json",
            "mcp": f"{base}/mcp",
            "acp_context": f"{base}/acp/context",
            "a2a_tasks": f"{base}/a2a/tasks",
            "sso_providers": f"{base}/auth/sso/providers",
            "oauth_authorization_server": f"{base}/.well-known/oauth-authorization-server",
            "oauth_protected_resource": f"{base}/.well-known/oauth-protected-resource",
        },
        "agent_card_preview": build_agent_card(base_url=base, extended=False),
        "hints": [
            "1. GET /discovery or /acp/context to boot",
            "2. Use MCP tools at /mcp with Bearer nk_…",
            "3. Delegate peer work via POST /a2a/tasks",
            "4. Sensitive actions: POST /approvals or require_approval on A2A tasks",
            "5. Protocol SLA: see `protocols` block (90-day sunset for breaks)",
        ],
    }
