"""P2.6 — validate entity ``data`` JSONB against workspace field definitions."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CustomFieldDefinition, EntityType


def validate_entity_data(
    db: Session,
    workspace_id: str,
    entity_type: EntityType,
    data: dict[str, Any] | None,
    *,
    merge_existing: dict | None = None,
) -> None:
    """Raise ValueError with agent-readable message if ``data`` violates definitions."""
    if not data:
        return
    defs = db.scalars(
        select(CustomFieldDefinition).where(
            CustomFieldDefinition.workspace_id == workspace_id,
            CustomFieldDefinition.entity_type == entity_type,
        )
    ).all()
    if not defs:
        return
    merged = {**(merge_existing or {}), **data}
    errors: list[str] = []
    for d in defs:
        val = merged.get(d.name)
        if d.required and (val is None or val == ""):
            errors.append(f"{d.name} is required ({d.label})")
            continue
        if val is None:
            continue
        err = _check_type(d.name, d.field_type, val, d.options)
        if err:
            errors.append(err)
    if errors:
        raise ValueError(
            "custom field validation failed: "
            + "; ".join(errors)
            + "; suggestion: GET /custom-fields or list_custom_fields MCP"
        )


def _check_type(name: str, field_type: str, val: Any, options: list) -> str | None:
    if field_type == "string" or field_type == "text" or field_type == "url":
        if not isinstance(val, str):
            return f"{name} must be a string"
    elif field_type == "email":
        if not isinstance(val, str) or "@" not in val:
            return f"{name} must be an email string"
    elif field_type == "number":
        if not isinstance(val, (int, float)):
            return f"{name} must be a number"
    elif field_type == "bool":
        if not isinstance(val, bool):
            return f"{name} must be a boolean"
    elif field_type == "date":
        if isinstance(val, str):
            try:
                date.fromisoformat(val[:10])
            except ValueError:
                return f"{name} must be ISO date YYYY-MM-DD"
        elif not isinstance(val, (date, datetime)):
            return f"{name} must be a date"
    elif field_type == "select":
        if options and val not in options:
            return f"{name} must be one of {options}"
    return None
