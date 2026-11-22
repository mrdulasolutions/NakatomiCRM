"""Persist workspace-approved connector deliveries and retry transient failures."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.db import db_session
from app.models import EntityType, MemoryDelivery, MemoryLink, Workspace
from app.services.memory import enabled_connectors, get_connector

_RETRIES = (10, 60, 300, 1200)


def enqueue(
    db: Session, workspace: Workspace, event_type: str, entity_type: EntityType, entity_id: str
) -> None:
    if (workspace.data or {}).get("memory_mirroring") is not True or event_type.startswith("memory."):
        return
    for name in enabled_connectors():
        db.add(
            MemoryDelivery(
                workspace_id=workspace.id,
                connector=name,
                event_type=event_type,
                entity_type=entity_type,
                entity_id=entity_id,
                next_attempt_at=datetime.now(UTC),
            )
        )


def process_pending(limit: int = 5) -> int:
    processed = 0
    for _ in range(limit):
        with db_session() as db:
            row = db.scalar(
                select(MemoryDelivery)
                .where(
                    MemoryDelivery.status == "pending",
                    MemoryDelivery.next_attempt_at <= datetime.now(UTC),
                )
                .order_by(MemoryDelivery.next_attempt_at, MemoryDelivery.id)
                .limit(1)
                .with_for_update(skip_locked=True)
            )
            if row is None:
                break
            processed += 1
            workspace = db.get(Workspace, row.workspace_id)
            connector = get_connector(row.connector)
            if not workspace or (workspace.data or {}).get("memory_mirroring") is not True or not connector:
                row.status = "skipped"
                continue
            row.attempts += 1
            try:
                result = connector.store_event(
                    workspace_id=row.workspace_id,
                    event_type=row.event_type,
                    crm_entity_type=row.entity_type.value,
                    crm_entity_id=row.entity_id,
                    text=row.event_type,
                    metadata={"delivery_id": row.id},
                )
                if result is not None and not result.external_id:
                    raise ValueError("Missing provider record ID")
            except Exception as exc:
                row.error = type(exc).__name__
                if row.attempts > len(_RETRIES):
                    row.status = "dead"
                else:
                    row.next_attempt_at = datetime.now(UTC) + timedelta(seconds=_RETRIES[row.attempts - 1])
                continue
            if result is None:
                row.status = "skipped"
                continue
            db.execute(
                insert(MemoryLink)
                .values(
                    workspace_id=row.workspace_id,
                    connector=row.connector,
                    external_id=result.external_id,
                    crm_entity_type=row.entity_type,
                    crm_entity_id=row.entity_id,
                    note=f"auto-link via {row.event_type}",
                    data={"event_type": row.event_type},
                )
                .on_conflict_do_nothing(constraint="uq_memory_link")
            )
            row.status = "succeeded"
            row.error = None
    return processed
