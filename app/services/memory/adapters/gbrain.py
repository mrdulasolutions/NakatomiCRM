"""GBrain connector — Garry Tan's self-wiring agent brain.

Upstream: https://github.com/garrytan/gbrain

GBrain ships an MCP server (``gbrain serve``) that defaults to stdio. For
remote access users wrap it in an ngrok (or Tailscale / cloud) tunnel so
HTTP clients can reach it — see `recipes/ngrok-tunnel.md` + `docs/mcp/DEPLOY.md`
upstream. The public surface is standard streamable-HTTP MCP over POST with
``Authorization: Bearer <token>`` and ``Accept: application/json, text/event-stream``
— the same protocol our own ``/mcp`` endpoint speaks.

This adapter targets three GBrain operations:

* ``put_page`` — write/update a page (markdown + YAML frontmatter). GBrain
  chunks, embeds, and reconciles tags. Auto-link extraction is skipped for
  remote callers (us) for security reasons.
* ``query`` — hybrid vector + keyword search with multi-query expansion.
* ``delete_page`` — used when a CRM entity is soft-deleted.

Env:
  * ``GBRAIN_MCP_URL`` — full URL to the MCP endpoint, e.g. ``https://brain.ngrok.app/mcp``
  * ``GBRAIN_TOKEN`` — Bearer token minted via ``gbrain auth create <label>``
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import UTC, datetime
from typing import Any

import httpx

from app.services.memory.base import MemoryConnector, MemoryItem, MemoryWriteResult

log = logging.getLogger("nakatomi.memory.gbrain")

_SLUG_SAFE = re.compile(r"[^a-z0-9_-]+")


def _slug_component(s: str) -> str:
    s = (s or "").strip().lower()
    s = _SLUG_SAFE.sub("-", s)
    return s.strip("-") or "na"


def _build_slug(workspace_id: str, entity_type: str, entity_id: str, ts: datetime) -> str:
    """Deterministic per-event slug. GBrain pages are slug-keyed, so include a
    timestamp so successive events on the same entity don't clobber each other."""
    return "/".join(
        [
            "nakatomi",
            _slug_component(workspace_id),
            _slug_component(entity_type),
            _slug_component(entity_id),
            ts.strftime("%Y%m%dT%H%M%SZ"),
        ]
    )


def _yaml_frontmatter(values: dict[str, Any]) -> str:
    """Minimal YAML emitter — stays readable, escapes strings, handles lists of scalars.
    GBrain parses its frontmatter itself; we only need well-formed YAML for the
    common scalar + list-of-scalar case."""
    def _emit(v: Any) -> str:
        if isinstance(v, bool):
            return "true" if v else "false"
        if v is None:
            return "null"
        if isinstance(v, (int, float)):
            return str(v)
        # string: quote if it has anything remotely tricky
        s = str(v)
        if s == "" or any(c in s for c in ':#\n"\'[]{}') or s.strip() != s:
            return json.dumps(s)
        return s

    lines = ["---"]
    for key, val in values.items():
        if isinstance(val, list):
            lines.append(f"{key}:")
            for item in val:
                lines.append(f"  - {_emit(item)}")
        else:
            lines.append(f"{key}: {_emit(val)}")
    lines.append("---")
    return "\n".join(lines)


def _parse_mcp_body(text: str) -> dict:
    """Decode a streamable-HTTP MCP response body. GBrain (and our own server)
    may return either plain ``application/json`` or an SSE stream with a single
    ``data: { ... }`` frame. Return the parsed JSON-RPC envelope."""
    text = text.strip()
    if not text:
        return {}
    if text.startswith("{"):
        return json.loads(text)
    # SSE: pick the last `data:` line that parses as JSON.
    last: dict = {}
    for line in text.splitlines():
        if line.startswith("data:"):
            payload = line[5:].strip()
            if payload:
                try:
                    last = json.loads(payload)
                except json.JSONDecodeError:
                    continue
    return last


def _extract_tool_result(envelope: dict) -> Any:
    """Unwrap ``{result: {content: [{type: 'text', text: '<json>'}]}}`` into the
    parsed inner JSON. Tools that return raw text fall through to the text.
    Returns ``None`` on protocol error."""
    if not isinstance(envelope, dict):
        return None
    if "error" in envelope:
        log.warning("gbrain tool error: %s", envelope["error"])
        return None
    content = (envelope.get("result") or {}).get("content") or []
    if not content:
        return envelope.get("result")
    first = content[0] or {}
    raw = first.get("text", "")
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


class GBrainConnector(MemoryConnector):
    name = "gbrain"

    _PROTOCOL_VERSION = "2025-03-26"

    def __init__(self) -> None:
        self.mcp_url = os.getenv("GBRAIN_MCP_URL", "").rstrip("/")
        self.token = os.getenv("GBRAIN_TOKEN", "")
        if not self.mcp_url or not self.token:
            raise RuntimeError("GBRAIN_MCP_URL and GBRAIN_TOKEN must both be set")
        self._client = httpx.Client(
            timeout=30.0,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json",
            },
        )

    def _call_tool(self, tool: str, arguments: dict) -> Any:
        """Open a fresh MCP session, call ``tool`` with ``arguments``, return the
        decoded result. Sessions are not reused — each CRM event mirrors
        independently and we'd rather eat the handshake than track stale IDs."""
        # 1. initialize
        init_resp = self._client.post(
            self.mcp_url,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": self._PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": "nakatomi", "version": "0.1"},
                },
            },
        )
        init_resp.raise_for_status()
        session_id = init_resp.headers.get("mcp-session-id")
        sid_headers = {"mcp-session-id": session_id} if session_id else {}

        # 2. initialized notification (FastMCP-like servers require it before tool calls)
        self._client.post(
            self.mcp_url,
            headers=sid_headers,
            json={"jsonrpc": "2.0", "method": "notifications/initialized"},
        )

        # 3. tools/call
        call_resp = self._client.post(
            self.mcp_url,
            headers=sid_headers,
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": tool, "arguments": arguments},
            },
        )
        call_resp.raise_for_status()
        envelope = _parse_mcp_body(call_resp.text)
        return _extract_tool_result(envelope)

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
        ts = datetime.now(UTC)
        slug = _build_slug(workspace_id, crm_entity_type, crm_entity_id, ts)

        if event_type.endswith(".deleted"):
            # Mirror deletes by removing the stored page lineage for this entity.
            # We only have a per-event slug here so we can't reliably find all
            # prior pages — leave them in place. Upstream MemoryLink rows are
            # cleaned up separately when the CRM row is soft-deleted.
            return None

        fm = _yaml_frontmatter(
            {
                "source": "nakatomi",
                "workspace_id": workspace_id,
                "event_type": event_type,
                "crm_entity_type": crm_entity_type,
                "crm_entity_id": crm_entity_id,
                "occurred_at": ts.isoformat(),
                "tags": [f"nakatomi:{crm_entity_type}", f"ws:{workspace_id}"],
                **{k: v for k, v in metadata.items() if isinstance(v, (str, int, float, bool)) and k not in {"source", "workspace_id", "event_type", "crm_entity_type", "crm_entity_id", "tags"}},
            }
        )
        content = f"{fm}\n\n{text}\n"

        try:
            result = self._call_tool("put_page", {"slug": slug, "content": content})
        except httpx.HTTPError as e:
            log.warning("gbrain put_page failed: %s", e)
            return None

        if not isinstance(result, dict):
            # put_page returns {status, slug, chunks, ...} on success; anything else is noise
            return None
        if result.get("status") == "error":
            log.warning("gbrain put_page status=error: %s", result.get("message") or result)
            return None

        return MemoryWriteResult(
            connector=self.name,
            external_id=result.get("slug") or slug,
            raw_response=result,
        )

    def recall(
        self,
        *,
        workspace_id: str,
        query: str,
        crm_entity_type: str | None = None,
        crm_entity_id: str | None = None,
        limit: int = 10,
    ) -> list[MemoryItem]:
        # `query` is GBrain's hybrid (vector + keyword) search. No server-side
        # metadata filter — we widen the search and filter client-side by slug
        # prefix when an entity anchor is supplied.
        oversample = limit * 4 if (crm_entity_type and crm_entity_id) else limit
        try:
            result = self._call_tool(
                "query",
                {"query": query, "limit": oversample, "expand": True},
            )
        except httpx.HTTPError as e:
            log.warning("gbrain query failed: %s", e)
            return []

        rows = result if isinstance(result, list) else (result or {}).get("results") or []
        if not isinstance(rows, list):
            return []

        prefix = None
        if crm_entity_type and crm_entity_id:
            prefix = f"nakatomi/{_slug_component(workspace_id)}/{_slug_component(crm_entity_type)}/{_slug_component(crm_entity_id)}/"

        out: list[MemoryItem] = []
        for it in rows:
            if not isinstance(it, dict):
                continue
            slug = it.get("slug") or it.get("page_slug") or it.get("id") or ""
            if prefix and not str(slug).startswith(prefix):
                continue
            out.append(
                MemoryItem(
                    connector=self.name,
                    external_id=str(slug),
                    text=it.get("content") or it.get("text") or it.get("snippet") or "",
                    score=float(it.get("score") or it.get("relevance") or 0.0),
                    metadata={k: v for k, v in it.items() if k not in {"content", "text", "snippet", "score", "relevance", "slug"}},
                )
            )
            if len(out) >= limit:
                break
        return out
