"""Shared workspace boundaries for connector results and link references."""

from uuid import UUID

from sqlalchemy.orm import Session

from app.models import Activity, Company, Contact, Deal, EntityType, File, Lead, Note, Product, Quote, Task
from app.services.memory.base import MemoryItem

_ENTITIES = {
    EntityType.contact: Contact,
    EntityType.company: Company,
    EntityType.deal: Deal,
    EntityType.activity: Activity,
    EntityType.note: Note,
    EntityType.task: Task,
    EntityType.file: File,
    EntityType.product: Product,
    EntityType.lead: Lead,
    EntityType.quote: Quote,
}


def owns_entity(db: Session, workspace_id: str, entity_type: EntityType, entity_id: str) -> bool:
    try:
        identifier = str(UUID(entity_id))
    except (ValueError, AttributeError, TypeError):
        return False
    row = db.get(_ENTITIES[entity_type], identifier)
    return bool(row and row.workspace_id == workspace_id and not getattr(row, "deleted_at", None))


def owns_result(connector: str, workspace_id: str, item: MemoryItem) -> bool:
    if connector == "gbrain":
        return item.external_id.startswith(f"nakatomi/{workspace_id}/")
    return item.metadata.get("workspace_id") == workspace_id
