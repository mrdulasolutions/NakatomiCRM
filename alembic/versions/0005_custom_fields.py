"""custom field definitions

Revision ID: 0005_custom_fields
Revises: 0004_api_key_rate_limit
Create Date: 2026-04-18
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0005_custom_fields"
down_revision: Union[str, None] = "0004_api_key_rate_limit"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "custom_field_definitions",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "workspace_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("entity_type", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("label", sa.String(length=255), nullable=False),
        sa.Column("field_type", sa.String(length=32), nullable=False),
        sa.Column("required", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column(
            "default_value",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "options",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("description", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("workspace_id", "entity_type", "name", name="uq_cfd_ws_et_name"),
    )
    op.create_index(
        "ix_cfd_ws_et",
        "custom_field_definitions",
        ["workspace_id", "entity_type"],
    )


def downgrade() -> None:
    op.drop_index("ix_cfd_ws_et", table_name="custom_field_definitions")
    op.drop_table("custom_field_definitions")
