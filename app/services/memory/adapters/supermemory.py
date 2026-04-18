"""Supermemory connector — REST API at https://api.supermemory.ai.

This is a best-effort adapter based on public docs. Verify request shapes
against your Supermemory dashboard before relying on it in production.
"""

from __future__ import annotations

import logging
import os

import httpx

from app.services.memory.base import MemoryConnector, MemoryItem, MemoryWriteResult

log = logging.getLogger("nakatomi.memory.supermemory")


class SupermemoryConnector(MemoryConnector):
    name = "supermemory"

    def __init__(self):
        self.api_key = os.getenv("SUPERMEMORY_API_KEY", "")
        self.base_url = os.getenv("SUPERMEMORY_BASE_URL", "https://api.supermemory.ai").rstrip("/")
        if not self.api_key:
            raise RuntimeError("SUPERMEMORY_API_KEY not set")
        self._client = httpx.Client(
            base_url=self.base_url,
            timeout=10.0,
            headers={"Authorization": f"Bearer {self.api_key}"},
        )

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
        payload = {
            "content": text,
            "metadata": {
                **metadata,
                "source": "nakatomi",
                "workspace_id": workspace_id,
                "event_type": event_type,
                "crm_entity_type": crm_entity_type,
                "crm_entity_id": crm_entity_id,
            },
            "containerTags": [f"nakatomi:{crm_entity_type}", f"ws:{workspace_id}"],
        }
        try:
            r = self._client.post("/v3/memories", json=payload)
            r.raise_for_status()
        except Exception as e:  # noqa: BLE001
            log.warning("supermemory store failed: %s", e)
            return None
        data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        ext_id = data.get("id") or ""
        return MemoryWriteResult(connector=self.name, external_id=str(ext_id), raw_response=data)

    def recall(
        self,
        *,
        workspace_id: str,
        query: str,
        crm_entity_type: str | None = None,
        crm_entity_id: str | None = None,
        limit: int = 10,
    ) -> list[MemoryItem]:
        payload: dict = {"q": query, "limit": limit, "containerTags": [f"ws:{workspace_id}"]}
        if crm_entity_type and crm_entity_id:
            payload["filters"] = {
                "metadata.crm_entity_type": crm_entity_type,
                "metadata.crm_entity_id": crm_entity_id,
            }
        try:
            r = self._client.post("/v3/search", json=payload)
            r.raise_for_status()
            items = r.json().get("results", []) or r.json().get("items", [])
        except Exception as e:  # noqa: BLE001
            log.warning("supermemory recall failed: %s", e)
            return []
        out: list[MemoryItem] = []
        for it in items:
            out.append(
                MemoryItem(
                    connector=self.name,
                    external_id=str(it.get("id") or ""),
                    text=it.get("content") or it.get("text") or "",
                    score=float(it.get("score") or 0.0),
                    metadata=it.get("metadata") or {},
                )
            )
        return out
