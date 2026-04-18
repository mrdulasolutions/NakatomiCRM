"""Workspace import — merge-mode upsert from an export document.

Design
------
We accept a doc produced by ``services/export.build_export``. Each row is
upserted into the target workspace using a stable natural key per entity.
Missing rows are created; existing rows are patched in place.

- contact / company / deal / activity / task → ``external_id`` if present,
  else a type-specific fallback (email for contacts, domain for companies).
- note → ``(entity_type, entity_id, body, author_user_id)`` tuple — notes
  don't have external ids; duplicates are rare in practice.
- relationship → unique edge tuple ``(source_type, source_id, target_type,
  target_id, relation_type)``.
- custom_field_definition → ``(entity_type, name)``.
- pipeline → ``slug``; stages by ``(pipeline, slug)``.
- webhook → ``url``; secret must be re-minted by the operator (we don't
  carry secrets across installs).
- memory_link → unique tuple.
- file → ``sha256`` if present, else ``storage_key``. File *bytes* are not
  part of the document — operators migrate bytes separately.

We purposely do NOT import ``id`` fields from the source. Generating fresh
UUIDs on the target side means two imports of the same data don't collide
by primary key, and cross-workspace portability is trivial. Relationships,
notes, tasks, activities, deals, and files may reference CRM entities by id
in the source doc — on import we translate those via an ``id_map`` from
source-id → new-id built as we go.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

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
    Stage,
    Task,
    Webhook,
)


@dataclass
class ImportResult:
    created: dict[str, int] = field(default_factory=dict)
    updated: dict[str, int] = field(default_factory=dict)
    skipped: dict[str, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


SUPPORTED_SCHEMA_VERSIONS = {1}


def _parse_dt(v: Any) -> datetime | None:
    if v is None or isinstance(v, datetime):
        return v
    try:
        return datetime.fromisoformat(str(v))
    except (TypeError, ValueError):
        return None


def _bump(bucket: dict[str, int], key: str) -> None:
    bucket[key] = bucket.get(key, 0) + 1


def apply_import(db: Session, workspace_id: str, doc: dict, *, dry_run: bool = False) -> ImportResult:
    result = ImportResult()

    version = doc.get("schema_version")
    if version not in SUPPORTED_SCHEMA_VERSIONS:
        raise ValueError(
            f"unsupported schema_version: {version}; this server supports {sorted(SUPPORTED_SCHEMA_VERSIONS)}"
        )

    # Work inside a SAVEPOINT so ``dry_run`` can cleanly roll back even when
    # the caller has already committed earlier changes.
    nested = db.begin_nested()

    try:
        id_map: dict[str, str] = {}  # source_id → new_id per CRM row

        _import_custom_fields(db, workspace_id, doc.get("custom_field_definitions", []), result)
        _import_pipelines(db, workspace_id, doc.get("pipelines", []), id_map, result)
        _import_companies(db, workspace_id, doc.get("companies", []), id_map, result)
        _import_contacts(db, workspace_id, doc.get("contacts", []), id_map, result)
        _import_deals(db, workspace_id, doc.get("deals", []), id_map, result)
        _import_activities(db, workspace_id, doc.get("activities", []), id_map, result)
        _import_notes(db, workspace_id, doc.get("notes", []), id_map, result)
        _import_tasks(db, workspace_id, doc.get("tasks", []), id_map, result)
        _import_relationships(db, workspace_id, doc.get("relationships", []), id_map, result)
        _import_webhooks(db, workspace_id, doc.get("webhooks", []), result)
        _import_memory_links(db, workspace_id, doc.get("memory_links", []), id_map, result)
        _import_files(db, workspace_id, doc.get("files", []), id_map, result)
    except Exception:
        nested.rollback()
        raise

    if dry_run:
        nested.rollback()
    else:
        nested.commit()
    return result


# ---------------------------------------------------------------------------
# Per-entity import functions
# ---------------------------------------------------------------------------


def _import_custom_fields(db, workspace_id, rows, result):
    for r in rows:
        existing = db.scalar(
            select(CustomFieldDefinition).where(
                CustomFieldDefinition.workspace_id == workspace_id,
                CustomFieldDefinition.entity_type == r["entity_type"],
                CustomFieldDefinition.name == r["name"],
            )
        )
        if existing:
            for k in ("label", "field_type", "required", "default_value", "options", "description"):
                if k in r:
                    setattr(existing, k, r[k])
            _bump(result.updated, "custom_field_definitions")
        else:
            db.add(
                CustomFieldDefinition(
                    workspace_id=workspace_id,
                    entity_type=r["entity_type"],
                    name=r["name"],
                    label=r.get("label", r["name"]),
                    field_type=r.get("field_type", "string"),
                    required=r.get("required", False),
                    default_value=r.get("default_value") or {},
                    options=r.get("options") or [],
                    description=r.get("description"),
                )
            )
            _bump(result.created, "custom_field_definitions")
    db.flush()


def _import_pipelines(db, workspace_id, rows, id_map, result):
    for r in rows:
        existing = db.scalar(
            select(Pipeline).where(Pipeline.workspace_id == workspace_id, Pipeline.slug == r["slug"])
        )
        if existing:
            for k in ("name", "is_default", "data"):
                if k in r:
                    setattr(existing, k, r[k])
            pipe = existing
            _bump(result.updated, "pipelines")
        else:
            pipe = Pipeline(
                workspace_id=workspace_id,
                name=r["name"],
                slug=r["slug"],
                is_default=r.get("is_default", False),
                data=r.get("data") or {},
            )
            db.add(pipe)
            db.flush()
            _bump(result.created, "pipelines")
        if r.get("id"):
            id_map[r["id"]] = pipe.id

        for sr in r.get("stages", []):
            stage = db.scalar(select(Stage).where(Stage.pipeline_id == pipe.id, Stage.slug == sr["slug"]))
            if stage:
                for k in ("name", "position", "probability", "is_won", "is_lost"):
                    if k in sr:
                        setattr(stage, k, sr[k])
                _bump(result.updated, "stages")
            else:
                stage = Stage(
                    pipeline_id=pipe.id,
                    name=sr["name"],
                    slug=sr["slug"],
                    position=sr.get("position", 0),
                    probability=sr.get("probability", 0),
                    is_won=sr.get("is_won", False),
                    is_lost=sr.get("is_lost", False),
                )
                db.add(stage)
                db.flush()
                _bump(result.created, "stages")
            if sr.get("id"):
                id_map[sr["id"]] = stage.id
    db.flush()


def _match_by_external_id_or(fallback_field: str | None):
    """Build a matcher closure shared by CRM entity imports."""

    def _match(db, workspace_id, model, row):
        if row.get("external_id"):
            hit = db.scalar(
                select(model).where(
                    model.workspace_id == workspace_id,
                    model.external_id == row["external_id"],
                )
            )
            if hit:
                return hit
        if fallback_field:
            val = row.get(fallback_field)
            if val:
                col = getattr(model, fallback_field)
                return db.scalar(
                    select(model).where(
                        model.workspace_id == workspace_id, func.lower(col) == str(val).lower()
                    )
                )
        return None

    return _match


def _copy_fields(row: dict, *, keys: list[str], translate_ids: dict[str, str] | None = None) -> dict:
    out: dict[str, Any] = {}
    for k in keys:
        if k not in row:
            continue
        v = row[k]
        if translate_ids and k.endswith("_id") and isinstance(v, str) and v in translate_ids:
            v = translate_ids[v]
        if k in {
            "created_at",
            "updated_at",
            "deleted_at",
            "closed_at",
            "expected_close_date",
            "due_at",
            "completed_at",
            "occurred_at",
            "last_used_at",
            "expires_at",
            "revoked_at",
            "last_delivery_at",
        }:
            v = _parse_dt(v)
        out[k] = v
    return out


def _import_companies(db, workspace_id, rows, id_map, result):
    match = _match_by_external_id_or("domain")
    keys = [
        "external_id",
        "name",
        "domain",
        "website",
        "industry",
        "employee_count",
        "annual_revenue",
        "description",
        "tags",
        "data",
    ]
    for r in rows:
        existing = match(db, workspace_id, Company, r)
        fields = _copy_fields(r, keys=keys)
        if existing:
            for k, v in fields.items():
                setattr(existing, k, v)
            company = existing
            _bump(result.updated, "companies")
        else:
            company = Company(workspace_id=workspace_id, **fields)
            db.add(company)
            db.flush()
            _bump(result.created, "companies")
        if r.get("id"):
            id_map[r["id"]] = company.id
    db.flush()


def _import_contacts(db, workspace_id, rows, id_map, result):
    match = _match_by_external_id_or("email")
    keys = [
        "external_id",
        "first_name",
        "last_name",
        "email",
        "phone",
        "title",
        "company_id",
        "tags",
        "data",
    ]
    for r in rows:
        existing = match(db, workspace_id, Contact, r)
        fields = _copy_fields(r, keys=keys, translate_ids=id_map)
        if existing:
            for k, v in fields.items():
                setattr(existing, k, v)
            contact = existing
            _bump(result.updated, "contacts")
        else:
            contact = Contact(workspace_id=workspace_id, **fields)
            db.add(contact)
            db.flush()
            _bump(result.created, "contacts")
        if r.get("id"):
            id_map[r["id"]] = contact.id
    db.flush()


def _import_deals(db, workspace_id, rows, id_map, result):
    match = _match_by_external_id_or(None)
    keys = [
        "external_id",
        "name",
        "pipeline_id",
        "stage_id",
        "status",
        "amount",
        "currency",
        "expected_close_date",
        "closed_at",
        "primary_contact_id",
        "company_id",
        "owner_user_id",
        "tags",
        "data",
    ]
    for r in rows:
        existing = match(db, workspace_id, Deal, r)
        fields = _copy_fields(r, keys=keys, translate_ids=id_map)
        if existing:
            for k, v in fields.items():
                setattr(existing, k, v)
            deal = existing
            _bump(result.updated, "deals")
        else:
            if not fields.get("pipeline_id") or not fields.get("stage_id"):
                result.warnings.append(f"deal '{r.get('name')}' skipped: missing pipeline_id/stage_id")
                _bump(result.skipped, "deals")
                continue
            deal = Deal(workspace_id=workspace_id, **fields)
            db.add(deal)
            db.flush()
            _bump(result.created, "deals")
        if r.get("id"):
            id_map[r["id"]] = deal.id
    db.flush()


def _resolve_entity_ref(row: dict, id_map: dict[str, str]) -> dict:
    """Translate (entity_type, entity_id) references via id_map when possible."""
    if row.get("entity_id") and row["entity_id"] in id_map:
        row["entity_id"] = id_map[row["entity_id"]]
    return row


def _import_activities(db, workspace_id, rows, id_map, result):
    keys = [
        "external_id",
        "kind",
        "subject",
        "body",
        "occurred_at",
        "entity_type",
        "entity_id",
        "data",
    ]
    for r in rows:
        r = _resolve_entity_ref(dict(r), id_map)
        existing = None
        if r.get("external_id"):
            existing = db.scalar(
                select(Activity).where(
                    Activity.workspace_id == workspace_id,
                    Activity.external_id == r["external_id"],
                )
            )
        fields = _copy_fields(r, keys=keys)
        if existing:
            for k, v in fields.items():
                setattr(existing, k, v)
            _bump(result.updated, "activities")
        else:
            db.add(Activity(workspace_id=workspace_id, **fields))
            _bump(result.created, "activities")
    db.flush()


def _import_notes(db, workspace_id, rows, id_map, result):
    for r in rows:
        r = _resolve_entity_ref(dict(r), id_map)
        # Notes have no external id — skip if an identical row already exists.
        existing = db.scalar(
            select(Note).where(
                Note.workspace_id == workspace_id,
                Note.entity_type == r["entity_type"],
                Note.entity_id == r["entity_id"],
                Note.body == r.get("body", ""),
            )
        )
        if existing:
            _bump(result.skipped, "notes")
            continue
        db.add(
            Note(
                workspace_id=workspace_id,
                entity_type=r["entity_type"],
                entity_id=r["entity_id"],
                body=r.get("body", ""),
                data=r.get("data") or {},
            )
        )
        _bump(result.created, "notes")
    db.flush()


def _import_tasks(db, workspace_id, rows, id_map, result):
    keys = [
        "external_id",
        "title",
        "description",
        "status",
        "due_at",
        "completed_at",
        "entity_type",
        "entity_id",
        "assignee_user_id",
        "data",
    ]
    for r in rows:
        r = _resolve_entity_ref(dict(r), id_map)
        existing = None
        if r.get("external_id"):
            existing = db.scalar(
                select(Task).where(Task.workspace_id == workspace_id, Task.external_id == r["external_id"])
            )
        fields = _copy_fields(r, keys=keys)
        if existing:
            for k, v in fields.items():
                setattr(existing, k, v)
            _bump(result.updated, "tasks")
        else:
            db.add(Task(workspace_id=workspace_id, **fields))
            _bump(result.created, "tasks")
    db.flush()


def _import_relationships(db, workspace_id, rows, id_map, result):
    for r in rows:
        src_id = id_map.get(r["source_id"], r["source_id"])
        tgt_id = id_map.get(r["target_id"], r["target_id"])
        existing = db.scalar(
            select(Relationship).where(
                Relationship.workspace_id == workspace_id,
                Relationship.source_type == r["source_type"],
                Relationship.source_id == src_id,
                Relationship.target_type == r["target_type"],
                Relationship.target_id == tgt_id,
                Relationship.relation_type == r["relation_type"],
            )
        )
        if existing:
            if "strength" in r:
                existing.strength = r["strength"]
            if "data" in r:
                existing.data = r.get("data") or {}
            _bump(result.updated, "relationships")
        else:
            db.add(
                Relationship(
                    workspace_id=workspace_id,
                    source_type=r["source_type"],
                    source_id=src_id,
                    target_type=r["target_type"],
                    target_id=tgt_id,
                    relation_type=r["relation_type"],
                    strength=r.get("strength", 1.0),
                    data=r.get("data") or {},
                )
            )
            _bump(result.created, "relationships")
    db.flush()


def _import_webhooks(db, workspace_id, rows, result):
    for r in rows:
        if r.get("secret") in (None, "", "[redacted on export]"):
            result.warnings.append(
                f"webhook '{r.get('name')}' imported without a secret — mint a new one via PATCH"
            )
            secret = uuid.uuid4().hex + uuid.uuid4().hex
        else:
            secret = r["secret"]
        existing = db.scalar(
            select(Webhook).where(Webhook.workspace_id == workspace_id, Webhook.url == r["url"])
        )
        if existing:
            for k in ("name", "events", "is_active"):
                if k in r:
                    setattr(existing, k, r[k])
            _bump(result.updated, "webhooks")
        else:
            db.add(
                Webhook(
                    workspace_id=workspace_id,
                    name=r.get("name", "imported"),
                    url=r["url"],
                    secret=secret,
                    events=r.get("events") or [],
                    is_active=r.get("is_active", True),
                )
            )
            _bump(result.created, "webhooks")
    db.flush()


def _import_memory_links(db, workspace_id, rows, id_map, result):
    for r in rows:
        crm_id = id_map.get(r["crm_entity_id"], r["crm_entity_id"])
        existing = db.scalar(
            select(MemoryLink).where(
                MemoryLink.workspace_id == workspace_id,
                MemoryLink.connector == r["connector"],
                MemoryLink.external_id == r["external_id"],
                MemoryLink.crm_entity_type == r["crm_entity_type"],
                MemoryLink.crm_entity_id == crm_id,
            )
        )
        if existing:
            _bump(result.skipped, "memory_links")
            continue
        db.add(
            MemoryLink(
                workspace_id=workspace_id,
                connector=r["connector"],
                external_id=r["external_id"],
                crm_entity_type=r["crm_entity_type"],
                crm_entity_id=crm_id,
                note=r.get("note"),
                data=r.get("data") or {},
            )
        )
        _bump(result.created, "memory_links")
    db.flush()


def _import_files(db, workspace_id, rows, id_map, result):
    for r in rows:
        entity_id = id_map.get(r.get("entity_id"), r.get("entity_id"))
        existing = None
        if r.get("sha256"):
            existing = db.scalar(
                select(File).where(File.workspace_id == workspace_id, File.sha256 == r["sha256"])
            )
        if existing:
            for k in ("filename", "content_type", "size_bytes", "entity_type", "data"):
                if k in r:
                    setattr(existing, k, r[k])
            existing.entity_id = entity_id
            _bump(result.updated, "files")
        else:
            db.add(
                File(
                    workspace_id=workspace_id,
                    filename=r.get("filename", "imported"),
                    content_type=r.get("content_type", "application/octet-stream"),
                    size_bytes=r.get("size_bytes", 0),
                    sha256=r.get("sha256"),
                    storage_key=r.get("storage_key", ""),
                    entity_type=r.get("entity_type"),
                    entity_id=entity_id,
                    data=r.get("data") or {},
                )
            )
            _bump(result.created, "files")
            result.warnings.append(
                f"file '{r.get('filename')}' metadata imported; bytes must be copied separately"
            )
    db.flush()


# Unused helper signature kept to appease mypy if we later want to register
# per-entity strategies through a dict. Harmless.
_registry: dict[str, Callable[..., None]] = {}
