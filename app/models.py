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
    product = "product"
    lead = "lead"
    quote = "quote"


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


class ApprovalStatus(str, enum.Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"
    expired = "expired"
    executed = "executed"


class A2ATaskStatus(str, enum.Enum):
    submitted = "submitted"
    working = "working"
    input_required = "input_required"
    completed = "completed"
    failed = "failed"
    canceled = "canceled"


class LeadStatus(str, enum.Enum):
    new = "new"
    working = "working"
    qualified = "qualified"
    unqualified = "unqualified"
    converted = "converted"


class QuoteStatus(str, enum.Enum):
    draft = "draft"
    sent = "sent"
    accepted = "accepted"
    rejected = "rejected"
    expired = "expired"


class DealParticipantRole(str, enum.Enum):
    champion = "champion"
    economic_buyer = "economic_buyer"
    legal = "legal"
    user = "user"
    influencer = "influencer"
    other = "other"


class JobStatus(str, enum.Enum):
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"
    canceled = "canceled"


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
    # Null when the account is SSO-only (Google/GitHub) with no local password.
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    display_name: Mapped[str | None] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # Optional SSO link — unique (provider, subject) when both set.
    sso_provider: Mapped[str | None] = mapped_column(String(32), nullable=True)
    sso_subject: Mapped[str | None] = mapped_column(String(255), nullable=True)

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

    # Capability scopes (see app.scopes). NULL/empty means legacy full access ("*").
    scopes: Mapped[list | None] = mapped_column(JSONB, nullable=True)

    # Free-form metadata. OAuth uses this to mark refresh tokens
    # (``data.oauth.kind = "refresh"``) and carry their client_id + scope.
    data: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


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
    # Account hierarchy (P2) — self-FK; null = top-level
    parent_company_id: Mapped[str | None] = mapped_column(
        ForeignKey("companies.id", ondelete="SET NULL"), index=True, nullable=True
    )

    tags: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    data: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


class ContactChannel(Base, TimestampMixin):
    """Extra emails/phones on a contact (primary still on Contact.email/phone)."""

    __tablename__ = "contact_channels"
    __table_args__ = (
        Index("ix_contact_channel_contact", "contact_id"),
        Index("ix_contact_channel_ws_value", "workspace_id", "value"),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    contact_id: Mapped[str] = mapped_column(ForeignKey("contacts.id", ondelete="CASCADE"), index=True)
    # email | phone | linkedin | other
    channel_type: Mapped[str] = mapped_column(String(32), nullable=False)
    value: Mapped[str] = mapped_column(String(512), nullable=False)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    label: Mapped[str | None] = mapped_column(String(64))
    data: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


class Lead(Base, TimestampMixin):
    """Inbound lead before conversion to contact/company/deal."""

    __tablename__ = "leads"
    __table_args__ = (
        UniqueConstraint("workspace_id", "external_id", name="uq_lead_external_id"),
        Index("ix_lead_workspace_deleted", "workspace_id", "deleted_at"),
        Index("ix_lead_email", "workspace_id", "email"),
        Index("ix_lead_status", "workspace_id", "status"),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    external_id: Mapped[str | None] = mapped_column(String(255))

    first_name: Mapped[str | None] = mapped_column(String(255))
    last_name: Mapped[str | None] = mapped_column(String(255))
    email: Mapped[str | None] = mapped_column(String(320))
    phone: Mapped[str | None] = mapped_column(String(64))
    title: Mapped[str | None] = mapped_column(String(255))
    company_name: Mapped[str | None] = mapped_column(String(255))
    company_domain: Mapped[str | None] = mapped_column(String(255))
    source: Mapped[str | None] = mapped_column(String(128))
    status: Mapped[LeadStatus] = mapped_column(Enum(LeadStatus), default=LeadStatus.new, nullable=False)
    score: Mapped[float | None] = mapped_column(Numeric(8, 2))
    owner_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))

    # Filled on convert
    converted_contact_id: Mapped[str | None] = mapped_column(ForeignKey("contacts.id", ondelete="SET NULL"))
    converted_company_id: Mapped[str | None] = mapped_column(ForeignKey("companies.id", ondelete="SET NULL"))
    converted_deal_id: Mapped[str | None] = mapped_column(ForeignKey("deals.id", ondelete="SET NULL"))
    converted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

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


class DealParticipant(Base, TimestampMixin):
    """Buying-committee role on a deal (champion, economic buyer, …)."""

    __tablename__ = "deal_participants"
    __table_args__ = (
        UniqueConstraint("deal_id", "contact_id", "role", name="uq_deal_participant_role"),
        Index("ix_deal_participant_deal", "deal_id"),
        Index("ix_deal_participant_contact", "contact_id"),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    deal_id: Mapped[str] = mapped_column(ForeignKey("deals.id", ondelete="CASCADE"), index=True)
    contact_id: Mapped[str] = mapped_column(ForeignKey("contacts.id", ondelete="CASCADE"), index=True)
    role: Mapped[DealParticipantRole] = mapped_column(
        Enum(DealParticipantRole), default=DealParticipantRole.other, nullable=False
    )
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    data: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


class Product(Base, TimestampMixin):
    """A sellable item in the workspace catalog. Referenced by ``DealLineItem``
    to compose a deal's value from individual line items.

    Pricing is captured as ``unit_price`` + ``currency`` for the catalog
    default; line items snapshot the price at creation so historical deals
    don't shift when the catalog is updated.
    """

    __tablename__ = "products"
    __table_args__ = (
        UniqueConstraint("workspace_id", "external_id", name="uq_product_external_id"),
        UniqueConstraint("workspace_id", "sku", name="uq_product_sku"),
        Index("ix_product_workspace_deleted", "workspace_id", "deleted_at"),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    external_id: Mapped[str | None] = mapped_column(String(255))

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    sku: Mapped[str | None] = mapped_column(String(64))
    description: Mapped[str | None] = mapped_column(Text)

    unit_price: Mapped[float | None] = mapped_column(Numeric(18, 2))
    currency: Mapped[str] = mapped_column(String(3), default="USD", nullable=False)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    tags: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    data: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


class DealLineItem(Base, TimestampMixin):
    """A line on a deal. Snapshots ``name`` and ``unit_price`` so historical
    deal values don't drift when the catalog updates.

    Quantity is a ``Numeric`` because some workspaces sell hours, fractional
    SKUs, or weight-based goods. Tax + discount stay in ``data`` to avoid
    forcing a tax model on every workspace.
    """

    __tablename__ = "deal_line_items"
    __table_args__ = (
        Index("ix_deal_line_items_deal", "deal_id"),
        Index("ix_deal_line_items_product", "product_id"),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    deal_id: Mapped[str] = mapped_column(ForeignKey("deals.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[str | None] = mapped_column(ForeignKey("products.id", ondelete="SET NULL"))

    # Snapshots from the catalog at the time this line was added. We
    # intentionally don't auto-sync these on product updates — past deals
    # are historical artifacts.
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    sku: Mapped[str | None] = mapped_column(String(64))
    quantity: Mapped[float] = mapped_column(Numeric(18, 4), default=1, nullable=False)
    unit_price: Mapped[float] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="USD", nullable=False)
    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    data: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


class Quote(Base, TimestampMixin):
    """Versioned quote attached to a deal (headless — PDF is a File artifact)."""

    __tablename__ = "quotes"
    __table_args__ = (
        UniqueConstraint("workspace_id", "external_id", name="uq_quote_external_id"),
        Index("ix_quote_deal", "deal_id"),
        Index("ix_quote_ws_status", "workspace_id", "status"),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    deal_id: Mapped[str] = mapped_column(ForeignKey("deals.id", ondelete="CASCADE"), index=True)
    external_id: Mapped[str | None] = mapped_column(String(255))

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    status: Mapped[QuoteStatus] = mapped_column(Enum(QuoteStatus), default=QuoteStatus.draft, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="USD", nullable=False)
    # Rollup of line items; recalculated on line changes
    subtotal: Mapped[float] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    total: Mapped[float] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Optional PDF file
    file_id: Mapped[str | None] = mapped_column(ForeignKey("files.id", ondelete="SET NULL"))
    notes: Mapped[str | None] = mapped_column(Text)
    data: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


class QuoteLineItem(Base, TimestampMixin):
    __tablename__ = "quote_line_items"
    __table_args__ = (Index("ix_quote_line_quote", "quote_id"),)

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    quote_id: Mapped[str] = mapped_column(ForeignKey("quotes.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[str | None] = mapped_column(ForeignKey("products.id", ondelete="SET NULL"))
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    sku: Mapped[str | None] = mapped_column(String(64))
    quantity: Mapped[float] = mapped_column(Numeric(18, 4), default=1, nullable=False)
    unit_price: Mapped[float] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="USD", nullable=False)
    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    data: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


class SavedView(Base, TimestampMixin):
    """Named filter + sort for agents (run via POST /views/{id}/run)."""

    __tablename__ = "saved_views"
    __table_args__ = (
        UniqueConstraint("workspace_id", "slug", name="uq_saved_view_slug"),
        Index("ix_saved_view_ws_entity", "workspace_id", "entity_type"),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(64), nullable=False)
    # contact | company | deal | lead | task | approval
    entity_type: Mapped[str] = mapped_column(String(32), nullable=False)
    # Filter DSL: list of {field, op, value}
    filters: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    # [{field, dir: asc|desc}]
    sort: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    # null = workspace-shared
    owner_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    data: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


class EmailConfig(Base, TimestampMixin):
    """Per-workspace email credentials.

    One row per workspace (1:1). IMAP fields are optional — workspaces
    that only need outbound (agents sending email through Nakatomi) can
    fill SMTP only and leave IMAP unset.

    Passwords are stored in plaintext for now. v0.4 will add
    application-level encryption keyed off ``SECRET_KEY``. Until then,
    treat them like any other workspace secret — DB row-level access is
    already gated by FK + workspace_id checks.
    """

    __tablename__ = "email_configs"
    __table_args__ = (
        UniqueConstraint("workspace_id", name="uq_email_config_workspace"),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)

    imap_host: Mapped[str | None] = mapped_column(String(255))
    imap_port: Mapped[int | None] = mapped_column(Integer)
    imap_user: Mapped[str | None] = mapped_column(String(255))
    imap_password: Mapped[str | None] = mapped_column(String(255))
    imap_folder: Mapped[str] = mapped_column(String(64), default="INBOX", nullable=False)
    imap_use_ssl: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    smtp_host: Mapped[str | None] = mapped_column(String(255))
    smtp_port: Mapped[int | None] = mapped_column(Integer)
    smtp_user: Mapped[str | None] = mapped_column(String(255))
    smtp_password: Mapped[str | None] = mapped_column(String(255))
    smtp_use_tls: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    from_address: Mapped[str | None] = mapped_column(String(255))
    from_name: Mapped[str | None] = mapped_column(String(255))

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_polled_uid: Mapped[int | None] = mapped_column(BigInteger)
    last_polled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    data: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


class CalendarFeed(Base, TimestampMixin):
    """Per-workspace iCal feed (.ics URL) the calendar poller subscribes to.

    Multiple feeds per workspace are allowed — typical pattern is one feed
    per calendar (work + personal + shared team calendar) so attendee
    matching can be scoped by source if needed.
    """

    __tablename__ = "calendar_feeds"
    __table_args__ = (
        Index("ix_calendar_feed_workspace", "workspace_id"),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    ics_url: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    last_polled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_etag: Mapped[str | None] = mapped_column(String(255))
    # Map of {ics_uid: activity_id} so the poller can update existing
    # activities rather than create duplicates when an event is edited.
    seen_uids: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

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


class OAuthClient(Base, TimestampMixin):
    """An MCP client that registered itself via /oauth/register (RFC 7591).

    Claude Desktop, Cursor, ChatGPT's custom connectors — each registers
    once and gets back a client_id. Public clients (no secret) rely on
    PKCE for the authorization-code flow.
    """

    __tablename__ = "oauth_clients"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    redirect_uris: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    # Optional — confidential clients authenticate with a secret; public
    # clients (Claude Desktop, browser-based) use PKCE only.
    client_secret_hash: Mapped[str | None] = mapped_column(String(255))
    grant_types: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    response_types: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    scopes: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    data: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


class OAuthCode(Base):
    """Short-lived authorization code — single-use, ~60s TTL.

    Stored as SHA-256 of the plaintext so a leaked DB snapshot doesn't
    yield usable codes.
    """

    __tablename__ = "oauth_codes"
    __table_args__ = (Index("ix_oauth_code_expires", "expires_at"),)

    code_hash: Mapped[str] = mapped_column(String(128), primary_key=True)
    client_id: Mapped[str] = mapped_column(ForeignKey("oauth_clients.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    redirect_uri: Mapped[str] = mapped_column(String(2048), nullable=False)
    code_challenge: Mapped[str] = mapped_column(String(255), nullable=False)
    code_challenge_method: Mapped[str] = mapped_column(String(16), nullable=False)
    scope: Mapped[str] = mapped_column(String(255), default="mcp", nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
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


class ApprovalRequest(Base, TimestampMixin):
    """Human-in-the-loop gate for agent-proposed actions.

    Agents create a pending request; a human or elevated key decides.
    Optional auto-execution runs known actions on approve.
    """

    __tablename__ = "approval_requests"
    __table_args__ = (
        Index("ix_approval_ws_status", "workspace_id", "status"),
        Index("ix_approval_ws_created", "workspace_id", "created_at"),
        Index("ix_approval_entity", "entity_type", "entity_id"),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)

    # Machine-readable action key, e.g. "email.send", "deal.won", "custom"
    action: Mapped[str] = mapped_column(String(128), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    status: Mapped[ApprovalStatus] = mapped_column(
        Enum(ApprovalStatus), default=ApprovalStatus.pending, nullable=False
    )

    requested_by_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    requested_by_api_key_id: Mapped[str | None] = mapped_column(ForeignKey("api_keys.id", ondelete="SET NULL"))
    decided_by_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    decided_by_api_key_id: Mapped[str | None] = mapped_column(ForeignKey("api_keys.id", ondelete="SET NULL"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    entity_type: Mapped[str | None] = mapped_column(String(64))
    entity_id: Mapped[str | None] = mapped_column(String(64))
    reason: Mapped[str | None] = mapped_column(Text)
    decision_note: Mapped[str | None] = mapped_column(Text)
    result: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    data: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


class A2ATask(Base, TimestampMixin):
    """Agent2Agent task — peer-agent work unit with lifecycle.

    REST binding at ``/a2a/tasks`` (documented in docs/A2A.md). Maps to optional
    CRM Task / ApprovalRequest for HITL and human-visible work.
    """

    __tablename__ = "a2a_tasks"
    __table_args__ = (
        Index("ix_a2a_ws_status", "workspace_id", "status"),
        Index("ix_a2a_ws_created", "workspace_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)

    status: Mapped[A2ATaskStatus] = mapped_column(
        Enum(A2ATaskStatus), default=A2ATaskStatus.submitted, nullable=False
    )
    skill: Mapped[str | None] = mapped_column(String(128))
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)

    # Structured input / output
    input: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    result: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    # Message history: [{role, parts, at}]
    messages: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    # Artifacts: [{name, mime_type, data|file_id, at}]
    artifacts: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)

    # Optional CRM links
    entity_type: Mapped[str | None] = mapped_column(String(64))
    entity_id: Mapped[str | None] = mapped_column(String(64))
    linked_task_id: Mapped[str | None] = mapped_column(ForeignKey("tasks.id", ondelete="SET NULL"))
    linked_approval_id: Mapped[str | None] = mapped_column(
        ForeignKey("approval_requests.id", ondelete="SET NULL")
    )

    callback_url: Mapped[str | None] = mapped_column(String(2048))
    context_etag: Mapped[str | None] = mapped_column(String(64))

    requested_by_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    requested_by_api_key_id: Mapped[str | None] = mapped_column(ForeignKey("api_keys.id", ondelete="SET NULL"))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    data: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


class CustomObjectType(Base, TimestampMixin):
    """Workspace-defined object type (moldable CRM model)."""

    __tablename__ = "custom_object_types"
    __table_args__ = (
        UniqueConstraint("workspace_id", "slug", name="uq_custom_object_slug"),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    # Field defs: [{name, label, type, required?, options?}]
    fields: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    data: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


class CustomRecord(Base, TimestampMixin):
    """Instance of a custom object type."""

    __tablename__ = "custom_records"
    __table_args__ = (
        UniqueConstraint("workspace_id", "object_slug", "external_id", name="uq_custom_record_external"),
        Index("ix_custom_record_ws_slug", "workspace_id", "object_slug"),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    object_type_id: Mapped[str] = mapped_column(
        ForeignKey("custom_object_types.id", ondelete="CASCADE"), index=True
    )
    object_slug: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    external_id: Mapped[str | None] = mapped_column(String(255))
    # Display name convenience
    name: Mapped[str | None] = mapped_column(String(512))
    values: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    # Optional link to core CRM entity
    related_entity_type: Mapped[str | None] = mapped_column(String(64))
    related_entity_id: Mapped[str | None] = mapped_column(String(64))
    tags: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    data: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


class Job(Base, TimestampMixin):
    """Async bulk work unit (ingest, import, export, merge, custom)."""

    __tablename__ = "jobs"
    __table_args__ = (
        Index("ix_job_ws_status", "workspace_id", "status"),
        Index("ix_job_ws_created", "workspace_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    # ingest | import | export | merge | a2a_batch | custom
    job_type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[JobStatus] = mapped_column(Enum(JobStatus), default=JobStatus.pending, nullable=False)
    progress: Mapped[float] = mapped_column(Numeric(5, 2), default=0, nullable=False)  # 0-100
    input: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    result: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    error: Mapped[str | None] = mapped_column(Text)
    actor_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    actor_api_key_id: Mapped[str | None] = mapped_column(ForeignKey("api_keys.id", ondelete="SET NULL"))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    data: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
