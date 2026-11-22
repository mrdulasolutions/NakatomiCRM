"""Run bounded recall and attach only workspace-local CRM references."""

import logging
from collections import defaultdict

from sqlalchemy import select, tuple_
from sqlalchemy.orm import Session

from app.models import MemoryLink
from app.services.memory import enabled_connectors, get_connector
from app.services.memory.access import owns_result

log = logging.getLogger("nakatomi.memory")


def recall_workspace(
    db: Session,
    *,
    workspace_id: str,
    query: str,
    entity_type: str | None,
    entity_id: str | None,
    limit: int,
    connectors: list[str] | None,
) -> tuple[list[dict], list[str]]:
    targets = dict.fromkeys(name.lower() for name in (connectors or enabled_connectors()))
    candidates = {}
    failed = []
    for name in targets:
        connector = get_connector(name)
        if not connector:
            failed.append(name)
            continue
        try:
            results = connector.recall(
                workspace_id=workspace_id,
                query=query,
                crm_entity_type=entity_type,
                crm_entity_id=entity_id,
                limit=limit,
            )
            for item in results:
                if item.external_id and owns_result(name, workspace_id, item):
                    key = (name, item.external_id)
                    if key not in candidates or item.score > candidates[key].score:
                        candidates[key] = item
        except Exception as exc:
            log.warning("Memory recall failed for %s (%s)", name, type(exc).__name__)
            failed.append(name)

    selected = sorted(candidates, key=lambda key: candidates[key].score, reverse=True)[:limit]
    links = defaultdict(list)
    if selected:
        for link in db.scalars(
            select(MemoryLink).where(
                MemoryLink.workspace_id == workspace_id,
                tuple_(MemoryLink.connector, MemoryLink.external_id).in_(selected),
            )
        ):
            links[(link.connector, link.external_id)].append(
                f"{link.crm_entity_type.value}:{link.crm_entity_id}"
            )

    return [
        {
            "connector": key[0],
            "external_id": key[1],
            "text": candidates[key].text,
            "score": candidates[key].score,
            "metadata": candidates[key].metadata,
            "crm_links": links[key],
        }
        for key in selected
    ], failed
