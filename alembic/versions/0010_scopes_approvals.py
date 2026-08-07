"""api key scopes + approval requests

Revision ID: 0010_scopes_approvals
Revises: 0009_email_calendar
Create Date: 2026-08-06

Adds capability scopes on api_keys and the approval_requests HITL table.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql

revision: str = "0010_scopes_approvals"
down_revision: Union[str, None] = "0009_email_calendar"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _tables() -> set[str]:
    return set(inspect(op.get_bind()).get_table_names())


def _columns(table: str) -> set[str]:
    return {c["name"] for c in inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    tables = _tables()

    if "api_keys" in tables and "scopes" not in _columns("api_keys"):
        op.add_column("api_keys", sa.Column("scopes", postgresql.JSONB(), nullable=True))

    if "approval_requests" not in tables:
        op.create_table(
            "approval_requests",
            sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
            sa.Column(
                "workspace_id",
                postgresql.UUID(as_uuid=False),
                sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("action", sa.String(128), nullable=False),
            sa.Column("payload", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
            sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
            sa.Column(
                "requested_by_user_id",
                postgresql.UUID(as_uuid=False),
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column(
                "requested_by_api_key_id",
                postgresql.UUID(as_uuid=False),
                sa.ForeignKey("api_keys.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column(
                "decided_by_user_id",
                postgresql.UUID(as_uuid=False),
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column(
                "decided_by_api_key_id",
                postgresql.UUID(as_uuid=False),
                sa.ForeignKey("api_keys.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("entity_type", sa.String(64), nullable=True),
            sa.Column("entity_id", sa.String(64), nullable=True),
            sa.Column("reason", sa.Text(), nullable=True),
            sa.Column("decision_note", sa.Text(), nullable=True),
            sa.Column("result", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
            sa.Column("data", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index("ix_approval_ws_status", "approval_requests", ["workspace_id", "status"])
        op.create_index("ix_approval_ws_created", "approval_requests", ["workspace_id", "created_at"])
        op.create_index("ix_approval_entity", "approval_requests", ["entity_type", "entity_id"])
        op.create_index(
            op.f("ix_approval_requests_workspace_id"),
            "approval_requests",
            ["workspace_id"],
        )


def downgrade() -> None:
    tables = _tables()
    if "approval_requests" in tables:
        op.drop_table("approval_requests")
    if "api_keys" in tables and "scopes" in _columns("api_keys"):
        op.drop_column("api_keys", "scopes")
