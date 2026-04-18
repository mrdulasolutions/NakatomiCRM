"""Adapter registry. Enabled via the MEMORY_CONNECTORS env var."""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Optional

from app.config import settings
from app.services.memory.base import MemoryConnector

log = logging.getLogger("nakatomi.memory")


@lru_cache(maxsize=1)
def _builtins() -> dict[str, type[MemoryConnector]]:
    """Lazy-import to avoid loading every adapter module on startup."""
    from app.services.memory.adapters.docdeploy import DocDeployConnector
    from app.services.memory.adapters.supermemory import SupermemoryConnector

    return {
        "docdeploy": DocDeployConnector,
        "supermemory": SupermemoryConnector,
    }


@lru_cache(maxsize=1)
def enabled_connectors() -> dict[str, MemoryConnector]:
    raw = (settings.MEMORY_CONNECTORS or "").strip()
    if not raw:
        return {}
    out: dict[str, MemoryConnector] = {}
    builtins = _builtins()
    for name in [n.strip().lower() for n in raw.split(",") if n.strip()]:
        cls = builtins.get(name)
        if not cls:
            log.warning("memory connector '%s' is not registered; skipping", name)
            continue
        try:
            out[name] = cls()
            log.info("memory connector '%s' enabled", name)
        except Exception as e:  # noqa: BLE001
            log.warning("memory connector '%s' failed to initialize: %s", name, e)
    return out


def get_connector(name: str) -> Optional[MemoryConnector]:
    return enabled_connectors().get(name.lower())
