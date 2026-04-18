"""All ORM models in one place.

Conventions
-----------
- UUID v4 primary keys (string repr).
- Every resource row has: id, workspace_id, external_id (nullable, unique per workspace),
  created_at, updated_at, deleted_at (soft delete), and `data` JSONB for free-form custom fields.
- Polymorphic references use (entity_type, entity_id) pairs instead of FKs — agents can point at
  any of the core entity types without schema migrations.
"""

from __future__ import annotations

import enum
import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def Enum(py_enum, **kw):
    """Plain VARCHAR + CHECK constraint. Keeps migrations simple and avoids
    the ``type "x" already exists`` trap when multiple tables share an enum."""
    kw.setdefault("native_enum", False)
    kw.setdefault("length", 32)
    return SAEnum(py_enum, **kw)


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(UTC)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class EntityType(str, enum.Enum):
    contact = "contact"
    company = "company"
    deal = "deal"
    activity = "activity"
    note = "note"
    task = "task"
    file = "file"


class MemberRole(str, enum.Enum):
    owner = "owner"
    admin = "admin"
    member = "member"
    readonly = "readonly"


class DealStatus(str, enum.Enum):
    open = "open"
    won = "won"
    lost = "lost"


class TaskStatus(str, enum.Enum):
    open = "open"
    in_progress = "in_progress"
    done = "done"
    cancelled = "cancelled"


# ---------------------------------------------------------------------------
# Mixins
# ---------------------------------------------------------------------------


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now, nullable=False
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


# ---------------------------------------------------------------------------
# Tenancy + auth
# ---------------------------------------------------------------------------


class Workspace(Base, TimestampMixin):
    __tablename__ = "workspaces"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    data: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    members: Mapped[list[Membership]] = relationship(back_populates="workspace", cascade="all, delete-orphan")


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    memberships: Mapped[list[Membership]] = relationship(back_populates="user", cascade="all, delete-orphan")


class Membership(Base, TimestampMixin):
    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("workspace_id", "user_id", name="uq_membership_ws_user"),)

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    role: Mapped[MemberRole] = mapped_column(Enum(MemberRole), default=MemberRole.member, nullable=False)

    workspace: Mapped[Workspace] = relationship(back_populates="members")
    user: Mapped[User] = relationship(back_populates="memberships")


class ApiKey(Base, TimestampMixin):
    """API keys scoped to a workspace. Optionally associated with a user (acts as that user)."""

    __tablename__ = "api_keys"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    prefix: Mapped[str] = mapped_column(String(16), nullable=False, index=True)  # visible identifier
    key_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[MemberRole] = mapped_column(Enum(MemberRole), default=MemberRole.member, nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Rate limiting — fixed 60-second window. ``rate_limit_per_minute`` overrides
    # the global ``API_KEY_RATE_LIMIT_PER_MINUTE`` setting when non-null.
    rate_limit_per_minute: Mapped[int | None] = mapped_column(Integer)
    usage_window_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    usage_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


# ---------------------------------------------------------------------------
# Core CRM entities
# ---------------------------------------------------------------------------


class _WorkspaceScoped:
    """Mixin-like declarative attrs added to each entity. Not a Base subclass to keep SA happy."""


class Contact(Base, TimestampMixin):
    __tablename__ = "contacts"
    __table_args__ = (
        UniqueConstraint("workspace_id", "external_id", name="uq_contact_external_id"),
        Index("ix_contact_workspace_deleted", "workspace_id", "deleted_at"),
        Index("ix_contact_email", "workspace_id", "email"),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    external_id: Mapped[str | None] = mapped_column(String(255))

    first_name: Mapped[str | None] = mapped_column(String(255))
    last_name: Mapped[str | None] = mapped_column(String(255))
    email: Mapped[str | None] = mapped_column(String(320))
    phone: Mapped[str | None] = mapped_column(String(64))
    title: Mapped[str | None] = mapped_column(String(255))
    company_id: Mapped[str | None] = mapped_column(
        ForeignKey("companies.id", ondelete="SET NULL"), index=True
    )

    tags: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    data: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


class Company(Base, TimestampMixin):
    __tablename__ = "companies"
    __table_args__ = (
        UniqueConstraint("workspace_id", "external_id", name="uq_company_external_id"),
        Index("ix_company_workspace_deleted", "workspace_id", "deleted_at"),
        Index("ix_company_domain", "workspace_id", "domain"),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    external_id: Mapped[str | None] = mapped_column(String(255))

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    domain: Mapped[str | None] = mapped_column(String(255))
    website: Mapped[str | None] = mapped_column(String(512))
    industry: Mapped[str | None] = mapped_column(String(255))
    employee_count: Mapped[int | None] = mapped_column(Integer)
    annual_revenue: Mapped[float | None] = mapped_column(Numeric(18, 2))
    description: Mapped[str | None] = mapped_column(Text)

    tags: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    data: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


class Pipeline(Base, TimestampMixin):
    __tablename__ = "pipelines"
    __table_args__ = (UniqueConstraint("workspace_id", "slug", name="uq_pipeline_slug"),)

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(64), nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    data: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    stages: Mapped[list[Stage]] = relationship(
        back_populates="pipeline", cascade="all, delete-orphan", order_by="Stage.position"
    )


class Stage(Base, TimestampMixin):
    __tablename__ = "stages"
    __table_args__ = (UniqueConstraint("pipeline_id", "slug", name="uq_stage_slug"),)

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    pipeline_id: Mapped[str] = mapped_column(ForeignKey("pipelines.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(64), nullable=False)
    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    probability: Mapped[float] = mapped_column(Numeric(5, 2), default=0, nullable=False)
    is_won: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_lost: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    pipeline: Mapped[Pipeline] = relationship(back_populates="stages")


class Deal(Base, TimestampMixin):
    __tablename__ = "deals"
    __table_args__ = (
        UniqueConstraint("workspace_id", "external_id", name="uq_deal_external_id"),
        Index("ix_deal_workspace_deleted", "workspace_id", "deleted_at"),
        Index("ix_deal_stage", "stage_id"),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    external_id: Mapped[str | None] = mapped_column(String(255))

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    pipeline_id: Mapped[str] = mapped_column(ForeignKey("pipelines.id", ondelete="RESTRICT"), index=True)
    stage_id: Mapped[str] = mapped_column(ForeignKey("stages.id", ondelete="RESTRICT"), index=True)
    status: Mapped[DealStatus] = mapped_column(Enum(DealStatus), default=DealStatus.open, nullable=False)
    amount: Mapped[float | None] = mapped_column(Numeric(18, 2))
    currency: Mapped[str] = mapped_column(String(3), default="USD", nullable=False)
    expected_close_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    primary_contact_id: Mapped[str | None] = mapped_column(ForeignKey("contacts.id", ondelete="SET NULL"))
    company_id: Mapped[str | None] = mapped_column(ForeignKey("companies.id", ondelete="SET NULL"))
    owner_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))

    tags: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    data: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


class Activity(Base, TimestampMixin):
    """Calls, meetings, emails-as-log, and other timestamped touchpoints."""

    __tablename__ = "activities"
    __table_args__ = (
        UniqueConstraint("workspace_id", "external_id", name="uq_activity_external_id"),
        Index("ix_activity_entity", "entity_type", "entity_id"),
        Index("ix_activity_workspace_occurred", "workspace_id", "occurred_at"),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    external_id: Mapped[str | None] = mapped_column(String(255))

    kind: Mapped[str] = mapped_column(String(64), nullable=False)  # e.g. "call", "meeting", "email_log"
    subject: Mapped[str | None] = mapped_column(String(512))
    body: Mapped[str | None] = mapped_column(Text)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)

    entity_type: Mapped[EntityType | None] = mapped_column(Enum(EntityType))
    entity_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False))

    actor_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    data: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


class Note(Base, TimestampMixin):
    __tablename__ = "notes"
    __table_args__ = (Index("ix_note_entity", "entity_type", "entity_id"),)

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)

    entity_type: Mapped[EntityType] = mapped_column(Enum(EntityType), nullable=False)
    entity_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)

    body: Mapped[str] = mapped_column(Text, nullable=False)  # markdown
    author_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    data: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


class Task(Base, TimestampMixin):
    __tablename__ = "tasks"
    __table_args__ = (
        UniqueConstraint("workspace_id", "external_id", name="uq_task_external_id"),
        Index("ix_task_entity", "entity_type", "entity_id"),
        Index("ix_task_due", "workspace_id", "status", "due_at"),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    external_id: Mapped[str | None] = mapped_column(String(255))

    title: Mapped[str] = mapped_column(String(512), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[TaskStatus] = mapped_column(Enum(TaskStatus), default=TaskStatus.open, nullable=False)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    entity_type: Mapped[EntityType | None] = mapped_column(Enum(EntityType))
    entity_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False))

    assignee_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    data: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


# ---------------------------------------------------------------------------
# Relationships graph (typed edges between entities)
# ---------------------------------------------------------------------------


class Relationship(Base, TimestampMixin):
    """A typed edge between any two entities.

    Examples: contact—KNOWS—contact, contact—WORKS_AT—company,
    deal—INVOLVES—contact, company—PARTNER_OF—company.
    """

    __tablename__ = "relationships"
    __table_args__ = (
        Index("ix_rel_source", "workspace_id", "source_type", "source_id"),
        Index("ix_rel_target", "workspace_id", "target_type", "target_id"),
        Index("ix_rel_type", "workspace_id", "relation_type"),
        UniqueConstraint(
            "workspace_id",
            "source_type",
            "source_id",
            "target_type",
            "target_id",
            "relation_type",
            name="uq_relationship_edge",
        ),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)

    source_type: Mapped[EntityType] = mapped_column(Enum(EntityType), nullable=False)
    source_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    target_type: Mapped[EntityType] = mapped_column(Enum(EntityType), nullable=False)
    target_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    relation_type: Mapped[str] = mapped_column(
        String(64), nullable=False
    )  # free-form, e.g. "knows", "works_at"
    strength: Mapped[float] = mapped_column(Numeric(5, 2), default=1.0, nullable=False)
    data: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


# ---------------------------------------------------------------------------
# Timeline (append-only event log)
# ---------------------------------------------------------------------------


class TimelineEvent(Base):
    __tablename__ = "timeline_events"
    __table_args__ = (
        Index("ix_tl_entity", "workspace_id", "entity_type", "entity_id", "occurred_at"),
        Index("ix_tl_workspace_time", "workspace_id", "occurred_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    entity_type: Mapped[EntityType] = mapped_column(Enum(EntityType), nullable=False)
    entity_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)  # e.g. "contact.created"
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
    actor_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    actor_api_key_id: Mapped[str | None] = mapped_column(ForeignKey("api_keys.id", ondelete="SET NULL"))
    payload: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


# ---------------------------------------------------------------------------
# Webhooks
# ---------------------------------------------------------------------------


class Webhook(Base, TimestampMixin):
    __tablename__ = "webhooks"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    secret: Mapped[str] = mapped_column(String(255), nullable=False)  # used to HMAC-sign payloads
    events: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)  # ["contact.created", ...]
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    failure_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_delivery_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)


class WebhookDelivery(Base):
    """Durable per-attempt record for webhook deliveries.

    On emit we insert a row with ``status="pending"`` and ``next_attempt_at=now()``.
    The background worker (``app/services/webhook_delivery.py``) polls for pending
    rows whose ``next_attempt_at`` has passed and attempts HTTP delivery. On a 2xx
    it flips to ``succeeded``; on failure it bumps ``attempts`` and schedules the
    next retry with exponential backoff, or marks ``dead`` after the max.
    """

    __tablename__ = "webhook_deliveries"
    __table_args__ = (
        Index("ix_wd_webhook_time", "webhook_id", "created_at"),
        Index("ix_wd_status_next", "status", "next_attempt_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    webhook_id: Mapped[str] = mapped_column(ForeignKey("webhooks.id", ondelete="CASCADE"), index=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False, index=True)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status_code: Mapped[int | None] = mapped_column(Integer)
    response_body: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    succeeded: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now, nullable=False
    )


# ---------------------------------------------------------------------------
# Files
# ---------------------------------------------------------------------------


class File(Base, TimestampMixin):
    __tablename__ = "files"
    __table_args__ = (Index("ix_file_entity", "entity_type", "entity_id"),)

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)

    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    content_type: Mapped[str] = mapped_column(String(255), default="application/octet-stream", nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    sha256: Mapped[str | None] = mapped_column(String(64), index=True)
    storage_key: Mapped[str] = mapped_column(String(1024), nullable=False)

    entity_type: Mapped[EntityType | None] = mapped_column(Enum(EntityType))
    entity_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False))

    uploaded_by_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    data: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------


class AuditLog(Base):
    __tablename__ = "audit_log"
    __table_args__ = (Index("ix_audit_ws_time", "workspace_id", "created_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    workspace_id: Mapped[str | None] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    actor_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    actor_api_key_id: Mapped[str | None] = mapped_column(ForeignKey("api_keys.id", ondelete="SET NULL"))
    action: Mapped[str] = mapped_column(String(128), nullable=False)
    entity_type: Mapped[str | None] = mapped_column(String(64))
    entity_id: Mapped[str | None] = mapped_column(String(64))
    ip_address: Mapped[str | None] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


class CustomFieldDefinition(Base, TimestampMixin):
    """Workspace-defined named fields on a CRM entity.

    Values still live in each row's ``data`` JSONB column; this table is a
    registry that lets operators declare which keys the workspace *expects*
    to track, so agents can see them via ``GET /custom-fields`` and surface
    them when creating or reading records.
    """

    __tablename__ = "custom_field_definitions"
    __table_args__ = (
        UniqueConstraint("workspace_id", "entity_type", "name", name="uq_cfd_ws_et_name"),
        Index("ix_cfd_ws_et", "workspace_id", "entity_type"),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    entity_type: Mapped[EntityType] = mapped_column(Enum(EntityType), nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False)  # snake_case JSONB key
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    # string | number | bool | date | url | email | select | text
    field_type: Mapped[str] = mapped_column(String(32), nullable=False)
    required: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    default_value: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    options: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)


class MemoryLink(Base, TimestampMixin):
    """Cross-link between a CRM entity and an external memory record."""

    __tablename__ = "memory_links"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "connector",
            "external_id",
            "crm_entity_type",
            "crm_entity_id",
            name="uq_memory_link",
        ),
        Index("ix_ml_crm", "workspace_id", "crm_entity_type", "crm_entity_id"),
        Index("ix_ml_external", "workspace_id", "connector", "external_id"),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    connector: Mapped[str] = mapped_column(String(64), nullable=False)
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    crm_entity_type: Mapped[EntityType] = mapped_column(Enum(EntityType), nullable=False)
    crm_entity_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    data: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


class IngestRun(Base):
    """A single ingest invocation for traceability."""

    __tablename__ = "ingest_runs"
    __table_args__ = (Index("ix_ingest_ws_time", "workspace_id", "created_at"),)

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    format: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    actor_api_key_id: Mapped[str | None] = mapped_column(ForeignKey("api_keys.id", ondelete="SET NULL"))
    record_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    updated_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    diagnostics: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)


class IdempotencyKey(Base):
    __tablename__ = "idempotency_keys"
    __table_args__ = (
        UniqueConstraint("workspace_id", "key", name="uq_idempotency_key"),
        Index("ix_idem_created", "created_at"),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    key: Mapped[str] = mapped_column(String(255), nullable=False)
    method: Mapped[str] = mapped_column(String(10), nullable=False)
    path: Mapped[str] = mapped_column(String(512), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status_code: Mapped[int] = mapped_column(Integer, nullable=False)
    response_body: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
