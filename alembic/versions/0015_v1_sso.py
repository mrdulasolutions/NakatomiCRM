"""SSO columns on users (Google / GitHub optional login)

Revision ID: 0015_v1_sso
Revises: 0014_p4_import_custom_objects
Create Date: 2026-08-07
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "0015_v1_sso"
down_revision: Union[str, None] = "0014_p4_import_custom_objects"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _columns(table: str) -> set[str]:
    bind = op.get_bind()
    return {c["name"] for c in inspect(bind).get_columns(table)}


def upgrade() -> None:
    cols = _columns("users")
    if "sso_provider" not in cols:
        op.add_column("users", sa.Column("sso_provider", sa.String(32), nullable=True))
    if "sso_subject" not in cols:
        op.add_column("users", sa.Column("sso_subject", sa.String(255), nullable=True))
    # SSO-only users may have no local password.
    op.alter_column("users", "password_hash", existing_type=sa.String(255), nullable=True)

    # Unique provider+subject when both set (partial unique via index).
    bind = op.get_bind()
    indexes = {ix["name"] for ix in inspect(bind).get_indexes("users")}
    if "uq_users_sso_provider_subject" not in indexes:
        op.create_index(
            "uq_users_sso_provider_subject",
            "users",
            ["sso_provider", "sso_subject"],
            unique=True,
            postgresql_where=sa.text("sso_provider IS NOT NULL AND sso_subject IS NOT NULL"),
        )


def downgrade() -> None:
    bind = op.get_bind()
    indexes = {ix["name"] for ix in inspect(bind).get_indexes("users")}
    if "uq_users_sso_provider_subject" in indexes:
        op.drop_index("uq_users_sso_provider_subject", table_name="users")
    # Fill null passwords before re-tightening NOT NULL.
    op.execute("UPDATE users SET password_hash = '!' WHERE password_hash IS NULL")
    op.alter_column("users", "password_hash", existing_type=sa.String(255), nullable=False)
    cols = _columns("users")
    if "sso_subject" in cols:
        op.drop_column("users", "sso_subject")
    if "sso_provider" in cols:
        op.drop_column("users", "sso_provider")
