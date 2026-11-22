"""Shared partial-update (PATCH) logic for REST routes and MCP tools.

Each ``apply_*_patch`` helper mutates an already-loaded, workspace-checked row
in place, emits the matching ``<entity>.updated`` event (timeline + audit +
webhooks via :func:`app.services.events.emit`) and leaves the commit to the
caller. Keeping this in one place means the REST ``PATCH`` routes and the MCP
``update_*`` tools can't drift apart on validation, policy checks, or events.

Errors are raised as :class:`fastapi.HTTPException` (same as the policy
service); MCP callers translate them into tool errors.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import BackgroundTasks, HTTPException
from sqlalchemy.orm import Session

from app.deps import Principal
from app.models import (
    Deal,
    DealLineItem,
    DealStatus,
    EntityType,
    Lead,
    LeadStatus,
    Note,
    Product,
    Stage,
    Task,
    TaskStatus,
)
from app.services.custom_field_validate import validate_entity_data
from app.services.deal_references import validate_deal_references
from app.services.diffs import compute_changes
from app.services.events import emit


def merge_json_data(existing: dict | None, incoming: dict, *, merge: bool = True) -> dict:
    """Return the new value for a JSONB ``data`` column.

    ``merge=True`` (default) shallow-merges ``incoming`` into ``existing``;
    a ``None`` value removes that key. ``merge=False`` replaces the whole
    object with ``incoming`` (``None`` values are dropped).
    """
    base: dict[str, Any] = dict(existing or {}) if merge else {}
    for key, value in incoming.items():
        if value is None:
            base.pop(key, None)
        else:
            base[key] = value
    return base


def apply_deal_patch(
    db: Session,
    p: Principal,
    d: Deal,
    updates: dict[str, Any],
    *,
    background: BackgroundTasks | None = None,
    validate_data_against_existing: bool = True,
) -> dict[str, dict[str, Any]]:
    """Apply a deal PATCH. Returns the computed ``changes`` diff.

    ``validate_data_against_existing=False`` validates ``updates["data"]`` as
    the complete new object (used when the caller already merged it).
    """
    try:
        validate_deal_references(
            db,
            p.workspace.id,
            updates.get("pipeline_id", d.pipeline_id),
            updates.get("stage_id", d.stage_id),
            updates,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    old_stage = d.stage_id
    old_status = d.status
    if "data" in updates and updates["data"] is not None:
        try:
            validate_entity_data(
                db,
                p.workspace.id,
                EntityType.deal,
                updates["data"],
                merge_existing=(d.data or {}) if validate_data_against_existing else None,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    # Workspace policy (required fields / block rules)
    from app.services.policies import evaluate_write

    stage_slug = None
    if "stage_id" in updates and updates["stage_id"]:
        st = db.get(Stage, updates["stage_id"])
        stage_slug = st.slug if st else None
    check = {
        "amount": updates.get("amount", d.amount),
        "primary_contact_id": updates.get("primary_contact_id", d.primary_contact_id),
        "status": updates.get("status", d.status),
        "stage_id": updates.get("stage_id", d.stage_id),
    }
    if hasattr(check["status"], "value"):
        check["status"] = check["status"].value
    action = "deal.won" if check["status"] == "won" else "deal.updated"
    evaluate_write(p, entity_type="deal", action=action, payload=check, stage_slug=stage_slug)
    for k, v in updates.items():
        setattr(d, k, v)
    if "status" in updates and updates["status"] in (DealStatus.won, DealStatus.lost):
        d.closed_at = datetime.now(UTC)
    # Capture per-field before/after *before* commit — SA's history only has
    # the old values while the session is still dirty.
    changes = compute_changes(d, list(updates.keys()))
    emit(
        db,
        p,
        event_type="deal.updated",
        entity_type=EntityType.deal,
        entity_id=d.id,
        payload={"changes": changes},
        background=background,
    )
    if "stage_id" in updates and updates["stage_id"] != old_stage:
        emit(
            db,
            p,
            event_type="deal.stage_changed",
            entity_type=EntityType.deal,
            entity_id=d.id,
            payload={"from_stage_id": old_stage, "to_stage_id": d.stage_id},
            background=background,
        )
    if "status" in updates and updates["status"] != old_status:
        new_status = updates["status"]
        status_name = new_status.value if hasattr(new_status, "value") else str(new_status)
        emit(
            db,
            p,
            event_type=f"deal.{status_name}",
            entity_type=EntityType.deal,
            entity_id=d.id,
            payload={"amount": float(d.amount) if d.amount else None},
            background=background,
        )
    return changes


def apply_task_patch(
    db: Session,
    p: Principal,
    t: Task,
    updates: dict[str, Any],
    *,
    background: BackgroundTasks | None = None,
) -> dict[str, dict[str, Any]]:
    for k, v in updates.items():
        setattr(t, k, v)
    if updates.get("status") == TaskStatus.done and not t.completed_at:
        t.completed_at = datetime.now(UTC)
    changes = compute_changes(t, list(updates.keys()))
    emit(
        db,
        p,
        event_type="task.updated",
        entity_type=EntityType.task,
        entity_id=t.id,
        payload={"changes": changes},
        background=background,
    )
    return changes


def apply_note_patch(
    db: Session,
    p: Principal,
    n: Note,
    updates: dict[str, Any],
    *,
    background: BackgroundTasks | None = None,
) -> None:
    if "body" in updates:
        n.body = updates["body"]
    if "data" in updates:
        n.data = updates["data"]
    emit(
        db,
        p,
        event_type="note.updated",
        entity_type=EntityType.note,
        entity_id=n.id,
        payload={},
        background=background,
    )


def apply_product_patch(
    db: Session,
    p: Principal,
    prod: Product,
    updates: dict[str, Any],
    *,
    background: BackgroundTasks | None = None,
) -> dict[str, dict[str, Any]]:
    for k, v in updates.items():
        setattr(prod, k, v)
    changes = compute_changes(prod, list(updates.keys()))
    emit(
        db,
        p,
        event_type="product.updated",
        entity_type=EntityType.product,
        entity_id=prod.id,
        payload={"changes": changes},
        background=background,
    )
    return changes


def apply_lead_patch(
    db: Session,
    p: Principal,
    row: Lead,
    updates: dict[str, Any],
    *,
    background: BackgroundTasks | None = None,
) -> None:
    if "status" in updates and updates["status"] is not None:
        try:
            updates["status"] = LeadStatus(updates["status"])
        except ValueError as e:
            raise HTTPException(status_code=422, detail=f"invalid status: {updates['status']}") from e
    for k, v in updates.items():
        setattr(row, k, v)
    emit(
        db,
        p,
        event_type="lead.updated",
        entity_type=EntityType.lead,
        entity_id=row.id,
        payload={"changes": list(updates.keys())},
        background=background,
    )


def apply_line_item_patch(
    db: Session,
    p: Principal,
    deal: Deal,
    line: DealLineItem,
    updates: dict[str, Any],
    *,
    background: BackgroundTasks | None = None,
) -> dict[str, dict[str, Any]]:
    for k, v in updates.items():
        setattr(line, k, v)
    changes = compute_changes(line, list(updates.keys()))
    emit(
        db,
        p,
        event_type="deal.line_item_updated",
        entity_type=EntityType.deal,
        entity_id=deal.id,
        payload={"line_item_id": line.id, "changes": changes},
        background=background,
    )
    return changes
