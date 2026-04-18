"""GBrain connector — Garry Tan's self-wiring agent brain.

Upstream: https://github.com/garrytan/gbrain

GBrain is MCP-first (stdio or HTTP). There is no first-class REST endpoint at
time of writing; the integration path is to deploy GBrain's MCP server (see
`docs/mcp/DEPLOY.md` in the upstream repo) and point Nakatomi at that URL.

This adapter is a **stub**. It demonstrates the wiring but makes no outbound
calls by default — filling in the right MCP tool calls requires knowing which
version of GBrain you've deployed (its tool names and shapes can evolve). Set
``GBRAIN_MCP_URL`` and ``GBRAIN_TOKEN`` to enable the adapter, then replace the
``_call_tool`` body with real MCP client calls for your deployment.
"""

from __future__ import annotations

import logging
import os

from app.services.memory.base import MemoryConnector, MemoryItem, MemoryWriteResult

log = logging.getLogger("nakatomi.memory.gbrain")


class GBrainConnector(MemoryConnector):
    name = "gbrain"

    def __init__(self):
        self.mcp_url = os.getenv("GBRAIN_MCP_URL", "").rstrip("/")
        self.token = os.getenv("GBRAIN_TOKEN", "")
        if not self.mcp_url or not self.token:
            raise RuntimeError("GBRAIN_MCP_URL and GBRAIN_TOKEN must both be set")

    def _call_tool(self, tool: str, arguments: dict) -> dict:
        """Placeholder for MCP tool invocation.

        Implementing this requires an MCP client session against ``self.mcp_url``.
        The simplest path is to reuse ``mcp.client.streamable_http`` (same SDK
        we use for our own MCP server) to open a session, call ``tool``, and
        return the tool result. Left as a TODO because the tool names depend
        on which GBrain build is deployed.
        """
        log.info(
            "gbrain stub: would call tool=%s args=%s against %s",
            tool,
            list(arguments.keys()),
            self.mcp_url,
        )
        return {}

    def store_event(
        self,
        *,
        workspace_id: str,
        event_type: str,
        crm_entity_type: str,
        crm_entity_id: str,
        text: str,
        metadata: dict,
    ) -> MemoryWriteResult | None:
        if event_type.endswith(".deleted"):
            return None
        # GBrain's natural verb for this is a brain-page write that includes
        # typed links; `ingest` or `idea-ingest` are likely MCP tools.
        resp = self._call_tool(
            "ingest",
            {
                "content": text,
                "metadata": {
                    **metadata,
                    "source": "nakatomi",
                    "workspace_id": workspace_id,
                    "event_type": event_type,
                    "crm_entity_type": crm_entity_type,
                    "crm_entity_id": crm_entity_id,
                },
                "tags": [f"nakatomi:{crm_entity_type}", f"ws:{workspace_id}"],
            },
        )
        ext_id = (resp.get("page_id") or resp.get("id") or "") if isinstance(resp, dict) else ""
        if not ext_id:
            return None
        return MemoryWriteResult(connector=self.name, external_id=str(ext_id), raw_response=resp)

    def recall(
        self,
        *,
        workspace_id: str,
        query: str,
        crm_entity_type: str | None = None,
        crm_entity_id: str | None = None,
        limit: int = 10,
    ) -> list[MemoryItem]:
        resp = self._call_tool(
            "query",
            {
                "q": query,
                "limit": limit,
                "filters": (
                    {
                        "metadata.crm_entity_type": crm_entity_type,
                        "metadata.crm_entity_id": crm_entity_id,
                    }
                    if crm_entity_type and crm_entity_id
                    else {}
                ),
            },
        )
        items = resp.get("results") if isinstance(resp, dict) else None
        if not items:
            return []
        out: list[MemoryItem] = []
        for it in items:
            out.append(
                MemoryItem(
                    connector=self.name,
                    external_id=str(it.get("id") or it.get("page_id") or ""),
                    text=it.get("content") or it.get("text") or "",
                    score=float(it.get("score") or 0.0),
                    metadata=it.get("metadata") or {},
                )
            )
        return out
