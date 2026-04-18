"""Self-describing endpoint: agents can GET /schema to discover what's available."""

from __future__ import annotations

from fastapi import APIRouter

from app.schemas import EntitySchemaOut, SchemaOut

router = APIRouter(tags=["schema"])


_ENTITIES = [
    EntitySchemaOut(
        entity="contact",
        fields={
            "id": "uuid",
            "external_id": "string (unique per workspace)",
            "first_name": "string?",
            "last_name": "string?",
            "email": "email?",
            "phone": "string?",
            "title": "string?",
            "company_id": "uuid?",
            "tags": "string[]",
            "data": "object (free-form)",
        },
        endpoints={
            "list": "GET /contacts",
            "create": "POST /contacts",
            "get": "GET /contacts/{id}",
            "patch": "PATCH /contacts/{id}",
            "delete": "DELETE /contacts/{id}",
            "bulk_upsert": "POST /contacts/bulk_upsert",
        },
    ),
    EntitySchemaOut(
        entity="company",
        fields={
            "id": "uuid",
            "external_id": "string?",
            "name": "string",
            "domain": "string?",
            "website": "string?",
            "industry": "string?",
            "employee_count": "int?",
            "annual_revenue": "number?",
            "description": "string?",
            "tags": "string[]",
            "data": "object",
        },
        endpoints={
            "list": "GET /companies",
            "create": "POST /companies",
            "get": "GET /companies/{id}",
            "patch": "PATCH /companies/{id}",
            "delete": "DELETE /companies/{id}",
            "bulk_upsert": "POST /companies/bulk_upsert",
        },
    ),
    EntitySchemaOut(
        entity="deal",
        fields={
            "id": "uuid",
            "name": "string",
            "pipeline_id": "uuid",
            "stage_id": "uuid",
            "status": "open|won|lost",
            "amount": "number?",
            "currency": "string",
            "expected_close_date": "datetime?",
            "primary_contact_id": "uuid?",
            "company_id": "uuid?",
            "owner_user_id": "uuid?",
            "tags": "string[]",
            "data": "object",
        },
        endpoints={
            "list": "GET /deals",
            "create": "POST /deals",
            "get": "GET /deals/{id}",
            "patch": "PATCH /deals/{id}",
            "delete": "DELETE /deals/{id}",
        },
    ),
    EntitySchemaOut(
        entity="activity",
        fields={
            "id": "uuid",
            "kind": "string (e.g. call, meeting, email_log)",
            "subject": "string?",
            "body": "string?",
            "occurred_at": "datetime",
            "entity_type": "contact|company|deal|... ?",
            "entity_id": "uuid?",
            "data": "object",
        },
        endpoints={"list": "GET /activities", "create": "POST /activities"},
    ),
    EntitySchemaOut(
        entity="note",
        fields={"entity_type": "enum", "entity_id": "uuid", "body": "markdown", "data": "object"},
        endpoints={"list": "GET /notes", "create": "POST /notes", "patch": "PATCH /notes/{id}"},
    ),
    EntitySchemaOut(
        entity="task",
        fields={
            "title": "string",
            "status": "open|in_progress|done|cancelled",
            "due_at": "datetime?",
            "assignee_user_id": "uuid?",
            "entity_type": "enum?",
            "entity_id": "uuid?",
        },
        endpoints={"list": "GET /tasks", "create": "POST /tasks", "patch": "PATCH /tasks/{id}"},
    ),
    EntitySchemaOut(
        entity="relationship",
        fields={
            "source_type": "entity enum",
            "source_id": "uuid",
            "target_type": "entity enum",
            "target_id": "uuid",
            "relation_type": "string (e.g. knows, works_at, partner_of)",
            "strength": "float",
        },
        endpoints={
            "list": "GET /relationships",
            "create": "POST /relationships",
            "neighbors": "GET /relationships/neighbors?entity_type=&entity_id=&depth=",
        },
    ),
    EntitySchemaOut(
        entity="pipeline",
        fields={"name": "string", "slug": "slug", "is_default": "bool", "stages": "stage[]"},
        endpoints={"list": "GET /pipelines", "create": "POST /pipelines"},
    ),
    EntitySchemaOut(
        entity="webhook",
        fields={"url": "string", "events": "string[]", "secret": "hex", "is_active": "bool"},
        endpoints={
            "list": "GET /webhooks",
            "create": "POST /webhooks",
            "deliveries": "GET /webhooks/{id}/deliveries",
        },
    ),
    EntitySchemaOut(
        entity="file",
        fields={
            "filename": "string",
            "content_type": "mime",
            "size_bytes": "int",
            "entity_type": "enum?",
            "entity_id": "uuid?",
        },
        endpoints={"upload": "POST /files (multipart)", "download": "GET /files/{id}", "list": "GET /files"},
    ),
]


_EVENT_TYPES = [
    "contact.created",
    "contact.updated",
    "contact.deleted",
    "company.created",
    "company.updated",
    "company.deleted",
    "deal.created",
    "deal.updated",
    "deal.deleted",
    "deal.stage_changed",
    "deal.won",
    "deal.lost",
    "activity.created",
    "activity.deleted",
    "note.created",
    "note.updated",
    "note.deleted",
    "task.created",
    "task.updated",
    "task.deleted",
    "relationship.created",
    "relationship.deleted",
    "file.uploaded",
    "file.deleted",
]


router_schema = router  # alias so main.py can import clearly


@router.get("/schema", response_model=SchemaOut)
def describe() -> SchemaOut:
    from app import __version__

    return SchemaOut(version=__version__, entities=_ENTITIES, event_types=_EVENT_TYPES)
