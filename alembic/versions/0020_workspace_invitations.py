"""Add email invitations to workspaces."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0020_workspace_invitations"
down_revision = "0019_password_recovery"
branch_labels = None
depends_on = None


def upgrade():
    if sa.inspect(op.get_bind()).has_table("workspace_invitations"):
        return
    op.create_table(
        "workspace_invitations",
        sa.Column("workspace_id", postgresql.UUID(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("email", sa.String(320), primary_key=True),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("digest", sa.String(64), unique=True, nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade():
    op.drop_table("workspace_invitations")
