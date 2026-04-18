"""Memory connector contracts."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class MemoryItem:
    connector: str
    external_id: str
    text: str
    score: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class MemoryWriteResult:
    connector: str
    external_id: str
    raw_response: dict[str, Any] = field(default_factory=dict)


class MemoryConnector(ABC):
    """One instance per configured adapter. Safe to hold long-lived HTTP clients."""

    name: str

    @abstractmethod
    def store_event(
        self,
        *,
        workspace_id: str,
        event_type: str,
        crm_entity_type: str,
        crm_entity_id: str,
        text: str,
        metadata: dict,
    ) -> Optional[MemoryWriteResult]:
        """Mirror a CRM event to the external memory. Return a write result, or None
        if the adapter chose to skip this event type."""

    @abstractmethod
    def recall(
        self,
        *,
        workspace_id: str,
        query: str,
        crm_entity_type: Optional[str] = None,
        crm_entity_id: Optional[str] = None,
        limit: int = 10,
    ) -> list[MemoryItem]:
        """Return the top-N memories relevant to the query (+ optional CRM anchor)."""

    def verify_webhook(self, headers: dict, body: bytes) -> bool:
        """Default: accept. Override with HMAC/signature verification per provider."""
        return True

    def parse_webhook(self, headers: dict, body: dict) -> list[dict]:
        """Return a list of ``{external_id, text, metadata, crm_refs: [{type, id}]}``
        items extracted from the inbound payload. Default: treat the whole body as
        a single item with no CRM refs."""
        return [
            {
                "external_id": body.get("id") or body.get("external_id") or "",
                "text": body.get("text") or body.get("content") or "",
                "metadata": body.get("metadata") or {},
                "crm_refs": body.get("crm_refs") or [],
            }
        ]
