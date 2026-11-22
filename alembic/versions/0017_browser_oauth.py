"""Add dashboard sessions and bind OAuth codes to their resource."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0017_browser_oauth"
down_revision = "0016_email_secrets_widen"
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("browser_sessions"):
        op.create_table(
            "browser_sessions",
            sa.Column("digest", sa.String(64), primary_key=True),
            sa.Column("user_id", postgresql.UUID(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("workspace_id", postgresql.UUID(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_browser_sessions_expires_at", "browser_sessions", ["expires_at"])
    if "resource" not in {column["name"] for column in inspector.get_columns("oauth_codes")}:
        op.add_column("oauth_codes", sa.Column("resource", sa.String(2048)))
    # Old access tokens had wildcard permissions and no resource binding.
    op.execute(
        sa.text("UPDATE api_keys SET revoked_at = now() WHERE name ~ :legacy_name AND revoked_at IS NULL")
        .bindparams(legacy_name=r"^oauth:[0-9a-f]{8}:access$")
    )


def downgrade():
    op.drop_column("oauth_codes", "resource")
    op.drop_table("browser_sessions")
