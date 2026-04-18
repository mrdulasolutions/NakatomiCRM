"""Merge two duplicate contacts into one.

Rules
-----
- Caller picks a **winner** (the contact to keep) and a **loser** (the
  contact to retire). The loser is soft-deleted with
  ``data.merged_into = winner.id`` so operators can reconstruct history.
- Scalar fields: winner wins unless it's ``None`` and loser has a value;
  override per-field via ``field_preferences = {"title": "loser", ...}``.
- ``tags``: union of both lists, dedup preserving winner's order.
- ``data`` JSONB: shallow merge — keys the winner has stay, keys only the
  loser has are added.
- Every reference to the loser is rewritten to the winner:
    - ``deal.primary_contact_id``
    - ``relationship.source_id`` / ``target_id`` (where source/target is contact)
    - ``note.entity_id`` / ``task.entity_id`` / ``activity.entity_id`` /
      ``file.entity_id`` / ``memory_link.crm_entity_id`` (where entity_type = contact)

Emits a ``contact.merged`` timeline event on the winner carrying the full
before-merge-winner / after diff, plus counts of rewritten rows.
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field as _field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Activity,
    Contact,
    Deal,
    EntityType,
    File,
    MemoryLink,
    Note,
    Relationship,
    Task,
)

# Fields we never merge — keys, timestamps, tenancy.
_SKIP_FIELDS = {
    "id",
    "workspace_id",
    "created_at",
    "updated_at",
    "deleted_at",
    "external_id",  # external_id is a business key; moving it silently would break upstream syncs
}

# Fields with custom merge semantics.
_CUSTOM_FIELDS = {"tags", "data"}


@dataclass
class MergeResult:
    changes: dict[str, dict[str, Any]] = _field(default_factory=dict)
    references_rewritten: dict[str, int] = _field(default_factory=dict)
    warnings: list[str] = _field(default_factory=list)


def _jsonable(v: Any) -> Any:
    from decimal import Decimal

    if v is None or isinstance(v, str | int | float | bool | list | dict):
        return v
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, datetime):
        return v.isoformat()
    if hasattr(v, "value"):
        return v.value
    return str(v)


def _merge_scalar(winner_val: Any, loser_val: Any, preference: str | None) -> tuple[Any, bool]:
    """Return (new_value, changed). Changed iff the winner's value is
    replaced."""
    if preference == "loser":
        return loser_val, winner_val != loser_val
    if preference == "winner":
        return winner_val, False
    # Default: winner wins unless None.
    if winner_val is None and loser_val is not None:
        return loser_val, True
    return winner_val, False


def _merge_tags(winner: list[str], loser: list[str]) -> list[str]:
    seen: list[str] = []
    for t in list(winner or []) + list(loser or []):
        if t and t not in seen:
            seen.append(t)
    return seen


def _rewrite(db: Session, workspace_id: str, winner_id: str, loser_id: str) -> dict[str, int]:
    """Rewrite every CRM reference pointing at ``loser_id`` to ``winner_id``.
    Returns counts per entity family."""
    counts: dict[str, int] = {}

    # deals.primary_contact_id
    deals = db.scalars(
        select(Deal).where(Deal.workspace_id == workspace_id, Deal.primary_contact_id == loser_id)
    ).all()
    for d in deals:
        d.primary_contact_id = winner_id
    counts["deals.primary_contact_id"] = len(deals)

    # relationships source / target where matching a contact.
    # If rewriting would collide with an existing edge on the winner, delete
    # the loser's row instead — the unique constraint would otherwise block
    # the whole merge.
    rewritten_rels = 0

    rels_src = db.scalars(
        select(Relationship).where(
            Relationship.workspace_id == workspace_id,
            Relationship.source_type == EntityType.contact,
            Relationship.source_id == loser_id,
        )
    ).all()
    for r in rels_src:
        dup = db.scalar(
            select(Relationship).where(
                Relationship.workspace_id == workspace_id,
                Relationship.source_type == EntityType.contact,
                Relationship.source_id == winner_id,
                Relationship.target_type == r.target_type,
                Relationship.target_id == r.target_id,
                Relationship.relation_type == r.relation_type,
            )
        )
        if dup and dup.id != r.id:
            db.delete(r)
        else:
            r.source_id = winner_id
        rewritten_rels += 1

    rels_tgt = db.scalars(
        select(Relationship).where(
            Relationship.workspace_id == workspace_id,
            Relationship.target_type == EntityType.contact,
            Relationship.target_id == loser_id,
        )
    ).all()
    for r in rels_tgt:
        dup = db.scalar(
            select(Relationship).where(
                Relationship.workspace_id == workspace_id,
                Relationship.source_type == r.source_type,
                Relationship.source_id == r.source_id,
                Relationship.target_type == EntityType.contact,
                Relationship.target_id == winner_id,
                Relationship.relation_type == r.relation_type,
            )
        )
        if dup and dup.id != r.id:
            db.delete(r)
        else:
            r.target_id = winner_id
        rewritten_rels += 1

    counts["relationships"] = rewritten_rels

    # polymorphic (entity_type, entity_id) children
    for model, label in (
        (Note, "notes"),
        (Task, "tasks"),
        (Activity, "activities"),
        (File, "files"),
    ):
        rows = db.scalars(
            select(model).where(
                model.workspace_id == workspace_id,
                model.entity_type == EntityType.contact,
                model.entity_id == loser_id,
            )
        ).all()
        for row in rows:
            row.entity_id = winner_id
        counts[label] = len(rows)

    # memory_links: same duplicate concern as relationships
    links = db.scalars(
        select(MemoryLink).where(
            MemoryLink.workspace_id == workspace_id,
            MemoryLink.crm_entity_type == EntityType.contact,
            MemoryLink.crm_entity_id == loser_id,
        )
    ).all()
    rewritten_links = 0
    for link in links:
        dup = db.scalar(
            select(MemoryLink).where(
                MemoryLink.workspace_id == workspace_id,
                MemoryLink.connector == link.connector,
                MemoryLink.external_id == link.external_id,
                MemoryLink.crm_entity_type == EntityType.contact,
                MemoryLink.crm_entity_id == winner_id,
            )
        )
        if dup and dup.id != link.id:
            db.delete(link)
        else:
            link.crm_entity_id = winner_id
        rewritten_links += 1
    counts["memory_links"] = rewritten_links

    return counts


def merge_contacts(
    db: Session,
    workspace_id: str,
    *,
    winner_id: str,
    loser_id: str,
    field_preferences: dict[str, str] | None = None,
    dry_run: bool = False,
) -> MergeResult:
    if winner_id == loser_id:
        raise ValueError("winner_id and loser_id must differ")

    winner = db.get(Contact, winner_id)
    loser = db.get(Contact, loser_id)
    if not winner or winner.workspace_id != workspace_id:
        raise ValueError("winner not found in this workspace")
    if not loser or loser.workspace_id != workspace_id:
        raise ValueError("loser not found in this workspace")
    if winner.deleted_at is not None or loser.deleted_at is not None:
        raise ValueError("both contacts must be live (not soft-deleted)")

    prefs = field_preferences or {}
    result = MergeResult()

    # Run inside a SAVEPOINT so dry_run can rewind.
    nested = db.begin_nested()
    try:
        # Scalar fields on the winner.
        for col in Contact.__table__.columns:
            name = col.name
            if name in _SKIP_FIELDS or name in _CUSTOM_FIELDS:
                continue
            winner_val = getattr(winner, name)
            loser_val = getattr(loser, name)
            new_val, changed = _merge_scalar(winner_val, loser_val, prefs.get(name))
            if changed:
                setattr(winner, name, new_val)
                result.changes[name] = {
                    "from": _jsonable(winner_val),
                    "to": _jsonable(new_val),
                }

        # Custom fields: tags union + data shallow merge.
        new_tags = _merge_tags(winner.tags, loser.tags)
        if set(new_tags) != set(winner.tags or []):
            result.changes["tags"] = {"from": list(winner.tags or []), "to": new_tags}
            winner.tags = new_tags

        new_data: dict = {**(loser.data or {}), **(winner.data or {})}
        if new_data != (winner.data or {}):
            result.changes["data"] = {"from": dict(winner.data or {}), "to": new_data}
            winner.data = new_data

        # Rewrite cross-entity references.
        result.references_rewritten = _rewrite(db, workspace_id, winner_id, loser_id)

        # Retire the loser.
        if not dry_run:
            loser.deleted_at = datetime.now(UTC)
            loser.data = {**(loser.data or {}), "merged_into": winner_id}

        if any(c > 0 for c in result.references_rewritten.values()):
            result.warnings.append(
                f"{sum(result.references_rewritten.values())} references rewritten from loser to winner"
            )
    except Exception:
        nested.rollback()
        raise

    if dry_run:
        nested.rollback()
    else:
        nested.commit()
    return result
