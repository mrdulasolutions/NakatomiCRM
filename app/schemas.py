"""Pydantic request/response schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Generic, Optional, TypeVar

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models import DealStatus, EntityType, MemberRole, TaskStatus

T = TypeVar("T")


class ORMBase(BaseModel):
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)


class Page(BaseModel, Generic[T]):
    items: list[T]
    next_cursor: Optional[str] = None
    count: int


# ---------- Auth ----------
class SignupRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    display_name: Optional[str] = None
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
    display_name: Optional[str]
    is_active: bool


# ---------- Workspace / members ----------
class WorkspaceOut(ORMBase):
    id: str
    name: str
    slug: str
    data: dict
    created_at: datetime


class WorkspaceUpdate(BaseModel):
    name: Optional[str] = None
    data: Optional[dict] = None


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
    expires_at: Optional[datetime] = None
    user_id: Optional[str] = None


class ApiKeyOut(ORMBase):
    id: str
    name: str
    prefix: str
    role: MemberRole
    last_used_at: Optional[datetime]
    expires_at: Optional[datetime]
    revoked_at: Optional[datetime]
    created_at: datetime


class ApiKeyCreatedOut(ApiKeyOut):
    key: str  # shown exactly once


# ---------- Contact ----------
class ContactIn(BaseModel):
    external_id: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    title: Optional[str] = None
    company_id: Optional[str] = None
    tags: list[str] = []
    data: dict = {}


class ContactPatch(BaseModel):
    external_id: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    title: Optional[str] = None
    company_id: Optional[str] = None
    tags: Optional[list[str]] = None
    data: Optional[dict] = None


class ContactOut(ORMBase):
    id: str
    external_id: Optional[str]
    first_name: Optional[str]
    last_name: Optional[str]
    email: Optional[str]
    phone: Optional[str]
    title: Optional[str]
    company_id: Optional[str]
    tags: list[str]
    data: dict
    created_at: datetime
    updated_at: datetime


# ---------- Company ----------
class CompanyIn(BaseModel):
    external_id: Optional[str] = None
    name: str
    domain: Optional[str] = None
    website: Optional[str] = None
    industry: Optional[str] = None
    employee_count: Optional[int] = None
    annual_revenue: Optional[float] = None
    description: Optional[str] = None
    tags: list[str] = []
    data: dict = {}


class CompanyPatch(BaseModel):
    external_id: Optional[str] = None
    name: Optional[str] = None
    domain: Optional[str] = None
    website: Optional[str] = None
    industry: Optional[str] = None
    employee_count: Optional[int] = None
    annual_revenue: Optional[float] = None
    description: Optional[str] = None
    tags: Optional[list[str]] = None
    data: Optional[dict] = None


class CompanyOut(ORMBase):
    id: str
    external_id: Optional[str]
    name: str
    domain: Optional[str]
    website: Optional[str]
    industry: Optional[str]
    employee_count: Optional[int]
    annual_revenue: Optional[float]
    description: Optional[str]
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
    external_id: Optional[str] = None
    name: str
    pipeline_id: Optional[str] = None
    stage_id: Optional[str] = None
    status: DealStatus = DealStatus.open
    amount: Optional[float] = None
    currency: str = "USD"
    expected_close_date: Optional[datetime] = None
    primary_contact_id: Optional[str] = None
    company_id: Optional[str] = None
    owner_user_id: Optional[str] = None
    tags: list[str] = []
    data: dict = {}


class DealPatch(BaseModel):
    external_id: Optional[str] = None
    name: Optional[str] = None
    stage_id: Optional[str] = None
    status: Optional[DealStatus] = None
    amount: Optional[float] = None
    currency: Optional[str] = None
    expected_close_date: Optional[datetime] = None
    primary_contact_id: Optional[str] = None
    company_id: Optional[str] = None
    owner_user_id: Optional[str] = None
    tags: Optional[list[str]] = None
    data: Optional[dict] = None


class DealOut(ORMBase):
    id: str
    external_id: Optional[str]
    name: str
    pipeline_id: str
    stage_id: str
    status: DealStatus
    amount: Optional[float]
    currency: str
    expected_close_date: Optional[datetime]
    closed_at: Optional[datetime]
    primary_contact_id: Optional[str]
    company_id: Optional[str]
    owner_user_id: Optional[str]
    tags: list[str]
    data: dict
    created_at: datetime
    updated_at: datetime


# ---------- Activity / Note / Task ----------
class ActivityIn(BaseModel):
    external_id: Optional[str] = None
    kind: str
    subject: Optional[str] = None
    body: Optional[str] = None
    occurred_at: Optional[datetime] = None
    entity_type: Optional[EntityType] = None
    entity_id: Optional[str] = None
    data: dict = {}


class ActivityOut(ORMBase):
    id: str
    external_id: Optional[str]
    kind: str
    subject: Optional[str]
    body: Optional[str]
    occurred_at: datetime
    entity_type: Optional[EntityType]
    entity_id: Optional[str]
    actor_user_id: Optional[str]
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
    author_user_id: Optional[str]
    data: dict
    created_at: datetime
    updated_at: datetime


class TaskIn(BaseModel):
    external_id: Optional[str] = None
    title: str
    description: Optional[str] = None
    status: TaskStatus = TaskStatus.open
    due_at: Optional[datetime] = None
    entity_type: Optional[EntityType] = None
    entity_id: Optional[str] = None
    assignee_user_id: Optional[str] = None
    data: dict = {}


class TaskPatch(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    status: Optional[TaskStatus] = None
    due_at: Optional[datetime] = None
    assignee_user_id: Optional[str] = None
    data: Optional[dict] = None


class TaskOut(ORMBase):
    id: str
    external_id: Optional[str]
    title: str
    description: Optional[str]
    status: TaskStatus
    due_at: Optional[datetime]
    completed_at: Optional[datetime]
    entity_type: Optional[EntityType]
    entity_id: Optional[str]
    assignee_user_id: Optional[str]
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
    actor_user_id: Optional[str]
    actor_api_key_id: Optional[str]
    payload: dict


# ---------- Webhooks ----------
class WebhookIn(BaseModel):
    name: str
    url: str
    events: list[str] = ["*"]
    is_active: bool = True


class WebhookPatch(BaseModel):
    name: Optional[str] = None
    url: Optional[str] = None
    events: Optional[list[str]] = None
    is_active: Optional[bool] = None


class WebhookOut(ORMBase):
    id: str
    name: str
    url: str
    events: list[str]
    is_active: bool
    failure_count: int
    last_delivery_at: Optional[datetime]
    last_error: Optional[str]
    created_at: datetime


class WebhookCreatedOut(WebhookOut):
    secret: str  # returned once


class WebhookDeliveryOut(ORMBase):
    id: int
    webhook_id: str
    event_type: str
    payload: dict
    status_code: Optional[int]
    response_body: Optional[str]
    error: Optional[str]
    attempts: int
    succeeded: bool
    created_at: datetime


# ---------- Files ----------
class FileOut(ORMBase):
    id: str
    filename: str
    content_type: str
    size_bytes: int
    sha256: Optional[str]
    entity_type: Optional[EntityType]
    entity_id: Optional[str]
    uploaded_by_user_id: Optional[str]
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
    message: Optional[str] = None


class ErrorResponse(BaseModel):
    error: str
    suggestion: Optional[str] = None


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


# ---------- Memory ----------
class MemoryRecallIn(BaseModel):
    query: str
    entity_type: Optional[EntityType] = None
    entity_id: Optional[str] = None
    limit: int = Field(10, ge=1, le=100)
    connectors: Optional[list[str]] = None


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
    note: Optional[str] = None
    data: dict = {}


class MemoryLinkOut(ORMBase):
    id: str
    connector: str
    external_id: str
    crm_entity_type: EntityType
    crm_entity_id: str
    note: Optional[str]
    data: dict
    created_at: datetime


# ---------- Ingest ----------
class IngestIn(BaseModel):
    source: str = Field(description="free-form label: hubspot, apollo, paste, etc.")
    format: str = Field(description="one of: csv, vcard, json, text")
    payload: Any = Field(description="raw data; shape depends on format")
    mapping: Optional[dict] = Field(
        default=None,
        description="optional field map for json/csv: {source_field: target_field}",
    )
    entity: Optional[str] = Field(
        default=None,
        description="optional target entity: contact | company | activity | note",
    )
    dry_run: bool = False


class IngestDiagnostic(BaseModel):
    level: str  # info | warn | error
    message: str
    row: Optional[int] = None
    field: Optional[str] = None


class IngestOut(BaseModel):
    run_id: str
    record_count: int
    created: int
    updated: int
    errors: int
    created_ids: list[str]
    updated_ids: list[str]
    diagnostics: list[IngestDiagnostic]
