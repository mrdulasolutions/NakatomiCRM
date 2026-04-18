"""oauth clients + auth codes

Revision ID: 0007_oauth
Revises: 0006_pg_trgm
Create Date: 2026-04-18
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql


revision: str = "0007_oauth"
down_revision: Union[str, None] = "0006_pg_trgm"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _tables() -> set[str]:
    return set(inspect(op.get_bind()).get_table_names())


def _cols(table: str) -> set[str]:
    return {c["name"] for c in inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    tables = _tables()

    # ApiKey.data — OAuth refresh tokens stash their client_id + scope here.
    if "data" not in _cols("api_keys"):
        with op.batch_alter_table("api_keys") as batch:
            batch.add_column(
                sa.Column(
                    "data",
                    postgresql.JSONB(),
                    nullable=False,
                    server_default=sa.text("'{}'::jsonb"),
                )
            )
        with op.batch_alter_table("api_keys") as batch:
            batch.alter_column("data", server_default=None)

    if "oauth_clients" not in tables:
        op.create_table(
            "oauth_clients",
            sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
            sa.Column("name", sa.String(length=255), nullable=False),
            sa.Column("redirect_uris", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
            sa.Column("client_secret_hash", sa.String(length=255)),
            sa.Column("grant_types", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
            sa.Column("response_types", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
            sa.Column("scopes", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
            sa.Column("data", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("deleted_at", sa.DateTime(timezone=True)),
        )

    if "oauth_codes" not in tables:
        op.create_table(
            "oauth_codes",
            sa.Column("code_hash", sa.String(length=128), primary_key=True),
            sa.Column(
                "client_id",
                postgresql.UUID(as_uuid=False),
                sa.ForeignKey("oauth_clients.id", ondelete="CASCADE"),
                nullable=False,
                index=True,
            ),
            sa.Column(
                "user_id",
                postgresql.UUID(as_uuid=False),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "workspace_id",
                postgresql.UUID(as_uuid=False),
                sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("redirect_uri", sa.String(length=2048), nullable=False),
            sa.Column("code_challenge", sa.String(length=255), nullable=False),
            sa.Column("code_challenge_method", sa.String(length=16), nullable=False),
            sa.Column("scope", sa.String(length=255), nullable=False, server_default="mcp"),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("used_at", sa.DateTime(timezone=True)),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        )
        op.create_index("ix_oauth_code_expires", "oauth_codes", ["expires_at"])


def downgrade() -> None:
    tables = _tables()
    if "oauth_codes" in tables:
        op.drop_index("ix_oauth_code_expires", table_name="oauth_codes")
        op.drop_table("oauth_codes")
    if "oauth_clients" in tables:
        op.drop_table("oauth_clients")
