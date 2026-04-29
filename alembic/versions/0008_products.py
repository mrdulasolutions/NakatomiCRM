"""products + deal line items

Revision ID: 0008_products
Revises: 0007_oauth
Create Date: 2026-04-29

Adds the product catalog and deal line items needed for "real CRM"
deals. Idempotent: safe to re-run against a DB that already has
either table.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql

revision: str = "0008_products"
down_revision: Union[str, None] = "0007_oauth"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _tables() -> set[str]:
    return set(inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    tables = _tables()

    if "products" not in tables:
        op.create_table(
            "products",
            sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
            sa.Column(
                "workspace_id",
                postgresql.UUID(as_uuid=False),
                sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("external_id", sa.String(255)),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("sku", sa.String(64)),
            sa.Column("description", sa.Text()),
            sa.Column("unit_price", sa.Numeric(18, 2)),
            sa.Column("currency", sa.String(3), nullable=False, server_default="USD"),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("tags", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
            sa.Column("data", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("deleted_at", sa.DateTime(timezone=True)),
            sa.UniqueConstraint("workspace_id", "external_id", name="uq_product_external_id"),
            sa.UniqueConstraint("workspace_id", "sku", name="uq_product_sku"),
        )
        op.create_index("ix_product_workspace_deleted", "products", ["workspace_id", "deleted_at"])
        op.create_index("ix_products_workspace_id", "products", ["workspace_id"])

    if "deal_line_items" not in tables:
        op.create_table(
            "deal_line_items",
            sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
            sa.Column(
                "deal_id",
                postgresql.UUID(as_uuid=False),
                sa.ForeignKey("deals.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "product_id",
                postgresql.UUID(as_uuid=False),
                sa.ForeignKey("products.id", ondelete="SET NULL"),
            ),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("sku", sa.String(64)),
            sa.Column("quantity", sa.Numeric(18, 4), nullable=False, server_default="1"),
            sa.Column("unit_price", sa.Numeric(18, 2), nullable=False, server_default="0"),
            sa.Column("currency", sa.String(3), nullable=False, server_default="USD"),
            sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("data", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("deleted_at", sa.DateTime(timezone=True)),
        )
        op.create_index("ix_deal_line_items_deal", "deal_line_items", ["deal_id"])
        op.create_index("ix_deal_line_items_product", "deal_line_items", ["product_id"])


def downgrade() -> None:
    tables = _tables()
    if "deal_line_items" in tables:
        op.drop_table("deal_line_items")
    if "products" in tables:
        op.drop_table("products")
