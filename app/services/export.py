"""Workspace export.

Produces a single JSON document with every exportable row in the workspace.
File *bytes* are not included — callers can fetch them via ``GET /files/{id}``
using the manifest entries. Operational state (audit log, webhook deliveries,
ingest runs, idempotency keys) is excluded on purpose — it's tied to this
deployment, not portable between installs.

The output shape is versioned via ``schema_version``. Bumping the version is
how we signal import-side migrations when the schema evolves.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import __version__
from app.models import (
    Activity,
    Company,
    Contact,
    CustomFieldDefinition,
    Deal,
    File,
    MemoryLink,
    Note,
    Pipeline,
    Relationship,
    Task,
    TimelineEvent,
    Webhook,
    Workspace,
)

EXPORT_SCHEMA_VERSION = 1


def _serialize(obj: Any) -> dict:
    out: dict[str, Any] = {}
    for col in obj.__table__.columns:
        v = getattr(obj, col.name)
        if isinstance(v, datetime):
            out[col.name] = v.isoformat()
        elif isinstance(v, Decimal):
            # JSON has no Decimal — float is lossy but lossless enough for our
            # ranges (deal amounts, probabilities, relationship strengths).
            out[col.name] = float(v)
        elif hasattr(v, "value"):  # Enum
            out[col.name] = v.value
        else:
            out[col.name] = v
    return out


def _rows(db: Session, model, workspace_id: str) -> list[dict]:
    rows = db.scalars(select(model).where(model.workspace_id == workspace_id)).all()
    return [_serialize(r) for r in rows]


def build_export(db: Session, workspace: Workspace, *, include_timeline: bool = False) -> dict:
    """Return a JSON-safe dict representing the entire workspace."""
    data: dict[str, Any] = {
        "schema_version": EXPORT_SCHEMA_VERSION,
        "nakatomi_version": __version__,
        "exported_at": datetime.now(UTC).isoformat(),
        "workspace": _serialize(workspace),
        "custom_field_definitions": _rows(db, CustomFieldDefinition, workspace.id),
        "pipelines": [],
        "contacts": _rows(db, Contact, workspace.id),
        "companies": _rows(db, Company, workspace.id),
        "deals": _rows(db, Deal, workspace.id),
        "activities": _rows(db, Activity, workspace.id),
        "notes": _rows(db, Note, workspace.id),
        "tasks": _rows(db, Task, workspace.id),
        "relationships": _rows(db, Relationship, workspace.id),
        "memory_links": _rows(db, MemoryLink, workspace.id),
        "files": _rows(db, File, workspace.id),
    }

    # Pipelines include their stages inline — mirrors the API's POST /pipelines shape.
    for pipe in db.scalars(select(Pipeline).where(Pipeline.workspace_id == workspace.id)).all():
        pipe_dict = _serialize(pipe)
        pipe_dict["stages"] = [_serialize(s) for s in pipe.stages]
        data["pipelines"].append(pipe_dict)

    # Webhooks: redact the HMAC secret. Operators must re-mint on import.
    webhooks_out = []
    for hook in db.scalars(select(Webhook).where(Webhook.workspace_id == workspace.id)).all():
        d = _serialize(hook)
        d["secret"] = "[redacted on export]"
        webhooks_out.append(d)
    data["webhooks"] = webhooks_out

    if include_timeline:
        data["timeline_events"] = [
            _serialize(e)
            for e in db.scalars(select(TimelineEvent).where(TimelineEvent.workspace_id == workspace.id)).all()
        ]

    data["counts"] = {k: len(v) for k, v in data.items() if isinstance(v, list)}
    return data
