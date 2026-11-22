"""Persist outbound memory delivery attempts."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0018_memory_deliveries"
down_revision = "0017_browser_oauth"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(sa.text(
        "DELETE FROM idempotency_keys WHERE method = 'POST' AND path IN ('/workspace/api-keys', '/webhooks')"
    ))
    if sa.inspect(op.get_bind()).has_table("memory_deliveries"):
        return
    op.create_table(
        "memory_deliveries",
        sa.Column("id", postgresql.UUID(), primary_key=True),
        sa.Column("workspace_id", postgresql.UUID(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("connector", sa.String(64), nullable=False),
        sa.Column("event_type", sa.String(128), nullable=False),
        sa.Column("entity_type", sa.String(8), nullable=False),
        sa.Column("entity_id", postgresql.UUID(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("error", sa.String(128)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_memory_deliveries_workspace_id", "memory_deliveries", ["workspace_id"])
    op.create_index("ix_memory_deliveries_due", "memory_deliveries", ["status", "next_attempt_at"])


def downgrade():
    op.drop_table("memory_deliveries")
