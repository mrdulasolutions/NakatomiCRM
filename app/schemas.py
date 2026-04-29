"""Pydantic request/response schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models import DealStatus, EntityType, MemberRole, TaskStatus

T = TypeVar("T")


class ORMBase(BaseModel):
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)


class Page(BaseModel, Generic[T]):
    items: list[T]
    next_cursor: str | None = None
    count: int


# ---------- Auth ----------
class SignupRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    display_name: str | None = None
    workspace_name: str
    workspace_slug: str = Field(min_length=2, max_length=64, pattern=r"^[a-z0-9][a-z0-9-]*$")


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: str
    workspace_id: str
    workspace_slug: str
    expires_in_seconds: int


class UserOut(ORMBase):
    id: str
    email: str
    display_name: str | None
    is_active: bool


# ---------- Workspace / members ----------
class WorkspaceOut(ORMBase):
    id: str
    name: str
    slug: str
    data: dict
    created_at: datetime


class WorkspaceUpdate(BaseModel):
    name: str | None = None
    data: dict | None = None


class InviteRequest(BaseModel):
    email: EmailStr
    role: MemberRole = MemberRole.member


class MembershipOut(ORMBase):
    id: str
    user_id: str
    role: MemberRole


# ---------- API keys ----------
class ApiKeyCreate(BaseModel):
    name: str
    role: MemberRole = MemberRole.member
    expires_at: datetime | None = None
    user_id: str | None = None
    rate_limit_per_minute: int | None = Field(
        default=None,
        ge=1,
        description="override the global API_KEY_RATE_LIMIT_PER_MINUTE for this key",
    )


class ApiKeyOut(ORMBase):
    id: str
    name: str
    prefix: str
    role: MemberRole
    last_used_at: datetime | None
    expires_at: datetime | None
    revoked_at: datetime | None
    rate_limit_per_minute: int | None
    created_at: datetime


class ApiKeyCreatedOut(ApiKeyOut):
    key: str  # shown exactly once


# ---------- Contact ----------
class ContactIn(BaseModel):
    external_id: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    email: EmailStr | None = None
    phone: str | None = None
    title: str | None = None
    company_id: str | None = None
    tags: list[str] = []
    data: dict = {}


class ContactPatch(BaseModel):
    external_id: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    email: EmailStr | None = None
    phone: str | None = None
    title: str | None = None
    company_id: str | None = None
    tags: list[str] | None = None
    data: dict | None = None


class ContactOut(ORMBase):
    id: str
    external_id: str | None
    first_name: str | None
    last_name: str | None
    email: str | None
    phone: str | None
    title: str | None
    company_id: str | None
    tags: list[str]
    data: dict
    created_at: datetime
    updated_at: datetime


# ---------- Company ----------
class CompanyIn(BaseModel):
    external_id: str | None = None
    name: str
    domain: str | None = None
    website: str | None = None
    industry: str | None = None
    employee_count: int | None = None
    annual_revenue: float | None = None
    description: str | None = None
    tags: list[str] = []
    data: dict = {}


class CompanyPatch(BaseModel):
    external_id: str | None = None
    name: str | None = None
    domain: str | None = None
    website: str | None = None
    industry: str | None = None
    employee_count: int | None = None
    annual_revenue: float | None = None
    description: str | None = None
    tags: list[str] | None = None
    data: dict | None = None


class CompanyOut(ORMBase):
    id: str
    external_id: str | None
    name: str
    domain: str | None
    website: str | None
    industry: str | None
    employee_count: int | None
    annual_revenue: float | None
    description: str | None
    tags: list[str]
    data: dict
    created_at: datetime
    updated_at: datetime


# ---------- Pipeline / Stage ----------
class StageIn(BaseModel):
    name: str
    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]*$")
    position: int = 0
    probability: float = 0
    is_won: bool = False
    is_lost: bool = False


class StageOut(ORMBase):
    id: str
    name: str
    slug: str
    position: int
    probability: float
    is_won: bool
    is_lost: bool


class PipelineIn(BaseModel):
    name: str
    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]*$")
    is_default: bool = False
    stages: list[StageIn] = []
    data: dict = {}


class PipelineOut(ORMBase):
    id: str
    name: str
    slug: str
    is_default: bool
    stages: list[StageOut]
    data: dict
    created_at: datetime


# ---------- Deal ----------
class DealIn(BaseModel):
    external_id: str | None = None
    name: str
    pipeline_id: str | None = None
    stage_id: str | None = None
    status: DealStatus = DealStatus.open
    amount: float | None = None
    currency: str = "USD"
    expected_close_date: datetime | None = None
    primary_contact_id: str | None = None
    company_id: str | None = None
    owner_user_id: str | None = None
    tags: list[str] = []
    data: dict = {}


class DealPatch(BaseModel):
    external_id: str | None = None
    name: str | None = None
    stage_id: str | None = None
    status: DealStatus | None = None
    amount: float | None = None
    currency: str | None = None
    expected_close_date: datetime | None = None
    primary_contact_id: str | None = None
    company_id: str | None = None
    owner_user_id: str | None = None
    tags: list[str] | None = None
    data: dict | None = None


class DealOut(ORMBase):
    id: str
    external_id: str | None
    name: str
    pipeline_id: str
    stage_id: str
    status: DealStatus
    amount: float | None
    currency: str
    expected_close_date: datetime | None
    closed_at: datetime | None
    primary_contact_id: str | None
    company_id: str | None
    owner_user_id: str | None
    tags: list[str]
    data: dict
    created_at: datetime
    updated_at: datetime


# ---------- Product / Deal Line Item ----------
class ProductIn(BaseModel):
    external_id: str | None = None
    name: str
    sku: str | None = None
    description: str | None = None
    unit_price: float | None = None
    currency: str = "USD"
    is_active: bool = True
    tags: list[str] = []
    data: dict = {}


class ProductPatch(BaseModel):
    external_id: str | None = None
    name: str | None = None
    sku: str | None = None
    description: str | None = None
    unit_price: float | None = None
    currency: str | None = None
    is_active: bool | None = None
    tags: list[str] | None = None
    data: dict | None = None


class ProductOut(ORMBase):
    id: str
    external_id: str | None
    name: str
    sku: str | None
    description: str | None
    unit_price: float | None
    currency: str
    is_active: bool
    tags: list[str]
    data: dict
    created_at: datetime
    updated_at: datetime


class DealLineItemIn(BaseModel):
    """Either supply ``product_id`` to snapshot from the catalog, or pass
    ``name`` + ``unit_price`` directly for an ad-hoc line."""

    product_id: str | None = None
    name: str | None = None
    sku: str | None = None
    quantity: float = 1
    unit_price: float | None = None
    currency: str | None = None
    position: int = 0
    data: dict = {}


class DealLineItemPatch(BaseModel):
    name: str | None = None
    sku: str | None = None
    quantity: float | None = None
    unit_price: float | None = None
    currency: str | None = None
    position: int | None = None
    data: dict | None = None


class DealLineItemOut(ORMBase):
    id: str
    deal_id: str
    product_id: str | None
    name: str
    sku: str | None
    quantity: float
    unit_price: float
    currency: str
    position: int
    data: dict
    created_at: datetime
    updated_at: datetime


# ---------- Activity / Note / Task ----------
class ActivityIn(BaseModel):
    external_id: str | None = None
    kind: str
    subject: str | None = None
    body: str | None = None
    occurred_at: datetime | None = None
    entity_type: EntityType | None = None
    entity_id: str | None = None
    data: dict = {}


class ActivityOut(ORMBase):
    id: str
    external_id: str | None
    kind: str
    subject: str | None
    body: str | None
    occurred_at: datetime
    entity_type: EntityType | None
    entity_id: str | None
    actor_user_id: str | None
    data: dict
    created_at: datetime


class NoteIn(BaseModel):
    entity_type: EntityType
    entity_id: str
    body: str
    data: dict = {}


class NoteOut(ORMBase):
    id: str
    entity_type: EntityType
    entity_id: str
    body: str
    author_user_id: str | None
    data: dict
    created_at: datetime
    updated_at: datetime


class TaskIn(BaseModel):
    external_id: str | None = None
    title: str
    description: str | None = None
    status: TaskStatus = TaskStatus.open
    due_at: datetime | None = None
    entity_type: EntityType | None = None
    entity_id: str | None = None
    assignee_user_id: str | None = None
    data: dict = {}


class TaskPatch(BaseModel):
    title: str | None = None
    description: str | None = None
    status: TaskStatus | None = None
    due_at: datetime | None = None
    assignee_user_id: str | None = None
    data: dict | None = None


class TaskOut(ORMBase):
    id: str
    external_id: str | None
    title: str
    description: str | None
    status: TaskStatus
    due_at: datetime | None
    completed_at: datetime | None
    entity_type: EntityType | None
    entity_id: str | None
    assignee_user_id: str | None
    data: dict
    created_at: datetime
    updated_at: datetime


# ---------- Relationships ----------
class RelationshipIn(BaseModel):
    source_type: EntityType
    source_id: str
    target_type: EntityType
    target_id: str
    relation_type: str = Field(min_length=1, max_length=64)
    strength: float = 1.0
    data: dict = {}


class RelationshipOut(ORMBase):
    id: str
    source_type: EntityType
    source_id: str
    target_type: EntityType
    target_id: str
    relation_type: str
    strength: float
    data: dict
    created_at: datetime


# ---------- Timeline ----------
class TimelineEventOut(ORMBase):
    id: int
    entity_type: EntityType
    entity_id: str
    event_type: str
    occurred_at: datetime
    actor_user_id: str | None
    actor_api_key_id: str | None
    payload: dict


# ---------- Webhooks ----------
class WebhookIn(BaseModel):
    name: str
    url: str
    events: list[str] = ["*"]
    is_active: bool = True


class WebhookPatch(BaseModel):
    name: str | None = None
    url: str | None = None
    events: list[str] | None = None
    is_active: bool | None = None


class WebhookOut(ORMBase):
    id: str
    name: str
    url: str
    events: list[str]
    is_active: bool
    failure_count: int
    last_delivery_at: datetime | None
    last_error: str | None
    created_at: datetime


class WebhookCreatedOut(WebhookOut):
    secret: str  # returned once


class WebhookDeliveryOut(ORMBase):
    id: int
    webhook_id: str
    event_type: str
    payload: dict
    status_code: int | None
    response_body: str | None
    error: str | None
    attempts: int
    succeeded: bool
    created_at: datetime


# ---------- Files ----------
class FileOut(ORMBase):
    id: str
    filename: str
    content_type: str
    size_bytes: int
    sha256: str | None
    entity_type: EntityType | None
    entity_id: str | None
    uploaded_by_user_id: str | None
    data: dict
    created_at: datetime


# ---------- Bulk ----------
class BulkUpsertResult(BaseModel):
    created: int
    updated: int
    ids: list[str]


# ---------- Generic responses ----------
class OkResponse(BaseModel):
    ok: bool = True
    message: str | None = None


class ErrorResponse(BaseModel):
    error: str
    suggestion: str | None = None


# ---------- Schema-describing endpoint ----------
class EntitySchemaOut(BaseModel):
    """Agents can GET /schema to introspect available entities and their fields."""

    entity: str
    fields: dict[str, str]
    endpoints: dict[str, str]


class SchemaOut(BaseModel):
    version: str
    entities: list[EntitySchemaOut]
    event_types: list[str]


class AnyEntityOut(BaseModel):
    entity_type: EntityType
    entity_id: str
    record: dict[str, Any]


# ---------- Custom fields ----------
_ALLOWED_FIELD_TYPES = {"string", "text", "number", "bool", "date", "url", "email", "select"}


class CustomFieldIn(BaseModel):
    entity_type: EntityType
    name: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")
    label: str
    field_type: str = Field(default="string")
    required: bool = False
    default_value: dict | None = None
    options: list[str] = []
    description: str | None = None

    def _check(self) -> None:
        if self.field_type not in _ALLOWED_FIELD_TYPES:
            raise ValueError(
                f"field_type must be one of: {sorted(_ALLOWED_FIELD_TYPES)}",
            )


class CustomFieldPatch(BaseModel):
    label: str | None = None
    field_type: str | None = None
    required: bool | None = None
    default_value: dict | None = None
    options: list[str] | None = None
    description: str | None = None


class ContactMergeRequest(BaseModel):
    winner_id: str
    loser_id: str
    field_preferences: dict[str, str] | None = None
    dry_run: bool = False


class ContactMergeResponse(BaseModel):
    winner_id: str
    loser_id: str
    changes: dict[str, dict[str, Any]]
    references_rewritten: dict[str, int]
    warnings: list[str]
    dry_run: bool


class ImportRequest(BaseModel):
    doc: dict
    dry_run: bool = False


class ImportResponse(BaseModel):
    created: dict[str, int]
    updated: dict[str, int]
    skipped: dict[str, int]
    warnings: list[str]
    dry_run: bool


class CustomFieldOut(ORMBase):
    id: str
    entity_type: EntityType
    name: str
    label: str
    field_type: str
    required: bool
    default_value: dict
    options: list[str]
    description: str | None
    created_at: datetime
    updated_at: datetime


# ---------- Memory ----------
class MemoryRecallIn(BaseModel):
    query: str
    entity_type: EntityType | None = None
    entity_id: str | None = None
    limit: int = Field(10, ge=1, le=100)
    connectors: list[str] | None = None


class MemoryRecallItem(BaseModel):
    connector: str
    external_id: str
    text: str
    score: float
    metadata: dict
    crm_links: list[str] = []


class MemoryRecallOut(BaseModel):
    items: list[MemoryRecallItem]


class MemoryLinkIn(BaseModel):
    connector: str
    external_id: str
    crm_entity_type: EntityType
    crm_entity_id: str
    note: str | None = None
    data: dict = {}


class MemoryLinkOut(ORMBase):
    id: str
    connector: str
    external_id: str
    crm_entity_type: EntityType
    crm_entity_id: str
    note: str | None
    data: dict
    created_at: datetime


# ---------- Ingest ----------
class IngestIn(BaseModel):
    source: str = Field(description="free-form label: hubspot, apollo, paste, etc.")
    format: str = Field(description="one of: csv, vcard, json, text")
    payload: Any = Field(description="raw data; shape depends on format")
    mapping: dict | None = Field(
        default=None,
        description="optional field map for json/csv: {source_field: target_field}",
    )
    entity: str | None = Field(
        default=None,
        description="optional target entity: contact | company | activity | note",
    )
    dry_run: bool = False


class IngestDiagnostic(BaseModel):
    level: str  # info | warn | error
    message: str
    row: int | None = None
    field: str | None = None


class IngestOut(BaseModel):
    run_id: str
    record_count: int
    created: int
    updated: int
    errors: int
    created_ids: list[str]
    updated_ids: list[str]
    diagnostics: list[IngestDiagnostic]
