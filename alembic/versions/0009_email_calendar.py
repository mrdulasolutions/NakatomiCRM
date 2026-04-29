"""email + calendar config

Revision ID: 0009_email_calendar
Revises: 0008_products
Create Date: 2026-04-29

Adds the per-workspace email config (IMAP + SMTP creds) and the
per-workspace calendar feed subscription table. Idempotent.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql

revision: str = "0009_email_calendar"
down_revision: Union[str, None] = "0008_products"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _tables() -> set[str]:
    return set(inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    tables = _tables()

    if "email_configs" not in tables:
        op.create_table(
            "email_configs",
            sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
            sa.Column(
                "workspace_id",
                postgresql.UUID(as_uuid=False),
                sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("imap_host", sa.String(255)),
            sa.Column("imap_port", sa.Integer()),
            sa.Column("imap_user", sa.String(255)),
            sa.Column("imap_password", sa.String(255)),
            sa.Column("imap_folder", sa.String(64), nullable=False, server_default="INBOX"),
            sa.Column("imap_use_ssl", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("smtp_host", sa.String(255)),
            sa.Column("smtp_port", sa.Integer()),
            sa.Column("smtp_user", sa.String(255)),
            sa.Column("smtp_password", sa.String(255)),
            sa.Column("smtp_use_tls", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("from_address", sa.String(255)),
            sa.Column("from_name", sa.String(255)),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("last_polled_uid", sa.BigInteger()),
            sa.Column("last_polled_at", sa.DateTime(timezone=True)),
            sa.Column("data", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("deleted_at", sa.DateTime(timezone=True)),
            sa.UniqueConstraint("workspace_id", name="uq_email_config_workspace"),
        )
        op.create_index("ix_email_configs_workspace_id", "email_configs", ["workspace_id"])

    if "calendar_feeds" not in tables:
        op.create_table(
            "calendar_feeds",
            sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
            sa.Column(
                "workspace_id",
                postgresql.UUID(as_uuid=False),
                sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("ics_url", sa.Text(), nullable=False),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("last_polled_at", sa.DateTime(timezone=True)),
            sa.Column("last_etag", sa.String(255)),
            sa.Column("seen_uids", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
            sa.Column("data", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("deleted_at", sa.DateTime(timezone=True)),
        )
        op.create_index("ix_calendar_feed_workspace", "calendar_feeds", ["workspace_id"])
        op.create_index("ix_calendar_feeds_workspace_id", "calendar_feeds", ["workspace_id"])


def downgrade() -> None:
    tables = _tables()
    if "calendar_feeds" in tables:
        op.drop_table("calendar_feeds")
    if "email_configs" in tables:
        op.drop_table("email_configs")
