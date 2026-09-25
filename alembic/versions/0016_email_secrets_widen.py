"""Widen email password columns and encrypt existing plaintext values."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect, text

revision: str = "0016_email_secrets_widen"
down_revision: Union[str, None] = "0015_v1_sso"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _columns(table: str) -> set[str]:
    bind = op.get_bind()
    return {c["name"] for c in inspect(bind).get_columns(table)}


def upgrade() -> None:
    if "email_configs" not in inspect(op.get_bind()).get_table_names():
        return
    cols = _columns("email_configs")
    if "imap_password" in cols:
        op.alter_column(
            "email_configs",
            "imap_password",
            existing_type=sa.String(255),
            type_=sa.Text(),
            existing_nullable=True,
        )
    if "smtp_password" in cols:
        op.alter_column(
            "email_configs",
            "smtp_password",
            existing_type=sa.String(255),
            type_=sa.Text(),
            existing_nullable=True,
        )

    from app.security import encrypt_stored_secret

    conn = op.get_bind()
    rows = conn.execute(
        text("SELECT id, imap_password, smtp_password FROM email_configs")
    ).fetchall()
    for row in rows:
        row_id, imap_pw, smtp_pw = row[0], row[1], row[2]
        new_imap = encrypt_stored_secret(imap_pw) if imap_pw else imap_pw
        new_smtp = encrypt_stored_secret(smtp_pw) if smtp_pw else smtp_pw
        if new_imap != imap_pw or new_smtp != smtp_pw:
            conn.execute(
                text(
                    "UPDATE email_configs SET imap_password = :imap, smtp_password = :smtp WHERE id = :id"
                ),
                {"id": row_id, "imap": new_imap, "smtp": new_smtp},
            )


def downgrade() -> None:
    if "email_configs" not in inspect(op.get_bind()).get_table_names():
        return
    op.alter_column(
        "email_configs",
        "imap_password",
        existing_type=sa.Text(),
        type_=sa.String(255),
        existing_nullable=True,
    )
    op.alter_column(
        "email_configs",
        "smtp_password",
        existing_type=sa.Text(),
        type_=sa.String(255),
        existing_nullable=True,
    )
