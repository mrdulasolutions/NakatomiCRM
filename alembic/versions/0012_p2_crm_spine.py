"""P2 CRM spine: leads, quotes, views, participants, channels, parent company

Revision ID: 0012_p2_crm_spine
Revises: 0011_a2a_tasks
Create Date: 2026-08-06
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql

revision: str = "0012_p2_crm_spine"
down_revision: Union[str, None] = "0011_a2a_tasks"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _tables() -> set[str]:
    return set(inspect(op.get_bind()).get_table_names())


def _columns(table: str) -> set[str]:
    return {c["name"] for c in inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    tables = _tables()

    if "companies" in tables and "parent_company_id" not in _columns("companies"):
        op.add_column(
            "companies",
            sa.Column(
                "parent_company_id",
                postgresql.UUID(as_uuid=False),
                sa.ForeignKey("companies.id", ondelete="SET NULL"),
                nullable=True,
            ),
        )
        op.create_index("ix_companies_parent_company_id", "companies", ["parent_company_id"])

    if "contact_channels" not in tables:
        op.create_table(
            "contact_channels",
            sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
            sa.Column(
                "workspace_id",
                postgresql.UUID(as_uuid=False),
                sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "contact_id",
                postgresql.UUID(as_uuid=False),
                sa.ForeignKey("contacts.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("channel_type", sa.String(32), nullable=False),
            sa.Column("value", sa.String(512), nullable=False),
            sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("label", sa.String(64), nullable=True),
            sa.Column("data", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index("ix_contact_channel_contact", "contact_channels", ["contact_id"])
        op.create_index("ix_contact_channel_ws_value", "contact_channels", ["workspace_id", "value"])

    if "leads" not in tables:
        op.create_table(
            "leads",
            sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
            sa.Column(
                "workspace_id",
                postgresql.UUID(as_uuid=False),
                sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("external_id", sa.String(255), nullable=True),
            sa.Column("first_name", sa.String(255), nullable=True),
            sa.Column("last_name", sa.String(255), nullable=True),
            sa.Column("email", sa.String(320), nullable=True),
            sa.Column("phone", sa.String(64), nullable=True),
            sa.Column("title", sa.String(255), nullable=True),
            sa.Column("company_name", sa.String(255), nullable=True),
            sa.Column("company_domain", sa.String(255), nullable=True),
            sa.Column("source", sa.String(128), nullable=True),
            sa.Column("status", sa.String(32), nullable=False, server_default="new"),
            sa.Column("score", sa.Numeric(8, 2), nullable=True),
            sa.Column(
                "owner_user_id",
                postgresql.UUID(as_uuid=False),
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column(
                "converted_contact_id",
                postgresql.UUID(as_uuid=False),
                sa.ForeignKey("contacts.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column(
                "converted_company_id",
                postgresql.UUID(as_uuid=False),
                sa.ForeignKey("companies.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column(
                "converted_deal_id",
                postgresql.UUID(as_uuid=False),
                sa.ForeignKey("deals.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("converted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("tags", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
            sa.Column("data", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint("workspace_id", "external_id", name="uq_lead_external_id"),
        )
        op.create_index("ix_lead_workspace_deleted", "leads", ["workspace_id", "deleted_at"])
        op.create_index("ix_lead_email", "leads", ["workspace_id", "email"])
        op.create_index("ix_lead_status", "leads", ["workspace_id", "status"])

    if "deal_participants" not in tables:
        op.create_table(
            "deal_participants",
            sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
            sa.Column(
                "workspace_id",
                postgresql.UUID(as_uuid=False),
                sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "deal_id",
                postgresql.UUID(as_uuid=False),
                sa.ForeignKey("deals.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "contact_id",
                postgresql.UUID(as_uuid=False),
                sa.ForeignKey("contacts.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("role", sa.String(32), nullable=False, server_default="other"),
            sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("data", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint("deal_id", "contact_id", "role", name="uq_deal_participant_role"),
        )
        op.create_index("ix_deal_participant_deal", "deal_participants", ["deal_id"])
        op.create_index("ix_deal_participant_contact", "deal_participants", ["contact_id"])

    if "quotes" not in tables:
        op.create_table(
            "quotes",
            sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
            sa.Column(
                "workspace_id",
                postgresql.UUID(as_uuid=False),
                sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "deal_id",
                postgresql.UUID(as_uuid=False),
                sa.ForeignKey("deals.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("external_id", sa.String(255), nullable=True),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("status", sa.String(32), nullable=False, server_default="draft"),
            sa.Column("currency", sa.String(3), nullable=False, server_default="USD"),
            sa.Column("subtotal", sa.Numeric(18, 2), nullable=False, server_default="0"),
            sa.Column("total", sa.Numeric(18, 2), nullable=False, server_default="0"),
            sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
            sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "file_id",
                postgresql.UUID(as_uuid=False),
                sa.ForeignKey("files.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("data", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint("workspace_id", "external_id", name="uq_quote_external_id"),
        )
        op.create_index("ix_quote_deal", "quotes", ["deal_id"])
        op.create_index("ix_quote_ws_status", "quotes", ["workspace_id", "status"])

    if "quote_line_items" not in tables:
        op.create_table(
            "quote_line_items",
            sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
            sa.Column(
                "quote_id",
                postgresql.UUID(as_uuid=False),
                sa.ForeignKey("quotes.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "product_id",
                postgresql.UUID(as_uuid=False),
                sa.ForeignKey("products.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("sku", sa.String(64), nullable=True),
            sa.Column("quantity", sa.Numeric(18, 4), nullable=False, server_default="1"),
            sa.Column("unit_price", sa.Numeric(18, 2), nullable=False, server_default="0"),
            sa.Column("currency", sa.String(3), nullable=False, server_default="USD"),
            sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("data", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index("ix_quote_line_quote", "quote_line_items", ["quote_id"])

    if "saved_views" not in tables:
        op.create_table(
            "saved_views",
            sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
            sa.Column(
                "workspace_id",
                postgresql.UUID(as_uuid=False),
                sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("slug", sa.String(64), nullable=False),
            sa.Column("entity_type", sa.String(32), nullable=False),
            sa.Column("filters", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
            sa.Column("sort", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
            sa.Column(
                "owner_user_id",
                postgresql.UUID(as_uuid=False),
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("data", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint("workspace_id", "slug", name="uq_saved_view_slug"),
        )
        op.create_index("ix_saved_view_ws_entity", "saved_views", ["workspace_id", "entity_type"])


def downgrade() -> None:
    tables = _tables()
    for t in ("saved_views", "quote_line_items", "quotes", "deal_participants", "leads", "contact_channels"):
        if t in tables:
            op.drop_table(t)
    if "companies" in tables and "parent_company_id" in _columns("companies"):
        op.drop_index("ix_companies_parent_company_id", table_name="companies")
        op.drop_column("companies", "parent_company_id")
