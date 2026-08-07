"""custom object types + records

Revision ID: 0014_p4_import_custom_objects
Revises: 0013_p3_jobs
Create Date: 2026-08-06
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql

revision: str = "0014_p4_import_custom_objects"
down_revision: Union[str, None] = "0013_p3_jobs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _tables() -> set[str]:
    return set(inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    tables = _tables()
    if "custom_object_types" not in tables:
        op.create_table(
            "custom_object_types",
            sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
            sa.Column(
                "workspace_id",
                postgresql.UUID(as_uuid=False),
                sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("slug", sa.String(64), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("fields", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
            sa.Column("data", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint("workspace_id", "slug", name="uq_custom_object_slug"),
        )
        op.create_index(op.f("ix_custom_object_types_workspace_id"), "custom_object_types", ["workspace_id"])

    if "custom_records" not in tables:
        op.create_table(
            "custom_records",
            sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
            sa.Column(
                "workspace_id",
                postgresql.UUID(as_uuid=False),
                sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "object_type_id",
                postgresql.UUID(as_uuid=False),
                sa.ForeignKey("custom_object_types.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("object_slug", sa.String(64), nullable=False),
            sa.Column("external_id", sa.String(255), nullable=True),
            sa.Column("name", sa.String(512), nullable=True),
            sa.Column("values", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
            sa.Column("related_entity_type", sa.String(64), nullable=True),
            sa.Column("related_entity_id", sa.String(64), nullable=True),
            sa.Column("tags", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
            sa.Column("data", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint(
                "workspace_id", "object_slug", "external_id", name="uq_custom_record_external"
            ),
        )
        op.create_index("ix_custom_record_ws_slug", "custom_records", ["workspace_id", "object_slug"])
        op.create_index(op.f("ix_custom_records_workspace_id"), "custom_records", ["workspace_id"])
        op.create_index(op.f("ix_custom_records_object_type_id"), "custom_records", ["object_type_id"])
        op.create_index(op.f("ix_custom_records_object_slug"), "custom_records", ["object_slug"])


def downgrade() -> None:
    tables = _tables()
    if "custom_records" in tables:
        op.drop_table("custom_records")
    if "custom_object_types" in tables:
        op.drop_table("custom_object_types")
