"""DocDeploy connector — pay-per-call encrypted memory on Base (x402).

Docs: https://www.docdeploy.io  •  API base: https://x402.docdeploy.io

This is a best-effort adapter based on public docs. Update the request/response
shapes once you have an account against the current API version.
"""

from __future__ import annotations

import logging
import os

import httpx

from app.services.memory.base import MemoryConnector, MemoryItem, MemoryWriteResult

log = logging.getLogger("nakatomi.memory.docdeploy")


class DocDeployConnector(MemoryConnector):
    name = "docdeploy"

    def __init__(self):
        self.api_key = os.getenv("DOCDEPLOY_API_KEY", "")
        self.base_url = os.getenv("DOCDEPLOY_BASE_URL", "https://x402.docdeploy.io").rstrip("/")
        if not self.api_key:
            raise RuntimeError("DOCDEPLOY_API_KEY not set")
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
        # Skip noisy events by default; operators can tune.
        if event_type.endswith(".deleted"):
            return None
        payload = {
            "text": text,
            "metadata": {
                **metadata,
                "source": "nakatomi",
                "workspace_id": workspace_id,
                "event_type": event_type,
                "crm_entity_type": crm_entity_type,
                "crm_entity_id": crm_entity_id,
            },
            "tags": [f"nakatomi:{crm_entity_type}", f"event:{event_type}"],
        }
        try:
            r = self._client.post("/v1/remember_memory", json=payload)
            r.raise_for_status()
        except Exception as e:  # noqa: BLE001
            log.warning("docdeploy store failed: %s", e)
            return None
        data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        ext_id = data.get("id") or data.get("memory_id") or ""
        return MemoryWriteResult(connector=self.name, external_id=ext_id, raw_response=data)

    def recall(
        self,
        *,
        workspace_id: str,
        query: str,
        crm_entity_type: str | None = None,
        crm_entity_id: str | None = None,
        limit: int = 10,
    ) -> list[MemoryItem]:
        payload: dict = {"query": query, "limit": limit}
        if crm_entity_type and crm_entity_id:
            payload["filters"] = {
                "metadata.crm_entity_type": crm_entity_type,
                "metadata.crm_entity_id": crm_entity_id,
            }
        try:
            r = self._client.post("/v1/recall_memory", json=payload)
            r.raise_for_status()
            items = r.json().get("items", [])
        except Exception as e:  # noqa: BLE001
            log.warning("docdeploy recall failed: %s", e)
            return []
        out: list[MemoryItem] = []
        for it in items:
            out.append(
                MemoryItem(
                    connector=self.name,
                    external_id=str(it.get("id") or it.get("memory_id") or ""),
                    text=it.get("text") or it.get("content") or "",
                    score=float(it.get("score") or 0.0),
                    metadata=it.get("metadata") or {},
                )
            )
        return out
