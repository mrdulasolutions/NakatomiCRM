"""durable webhook deliveries

Revision ID: 0003_durable_webhooks
Revises: 0002_memory_ingest
Create Date: 2026-04-18

Adds ``status``, ``next_attempt_at``, and ``updated_at`` to ``webhook_deliveries``
so the background worker can persist retry scheduling durably.

Idempotent: migration 0001 bootstraps the schema via ``Base.metadata.create_all``
against the current model definition, which already carries these columns on
fresh installs. For upgrades from v0.1.0 the columns don't exist yet and need
to be added here. We inspect before writing so both paths converge on the same
end state.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect


revision: str = "0003_durable_webhooks"
down_revision: Union[str, None] = "0002_memory_ingest"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _existing_columns(table: str) -> set[str]:
    return {c["name"] for c in inspect(op.get_bind()).get_columns(table)}


def _existing_indexes(table: str) -> set[str]:
    return {ix["name"] for ix in inspect(op.get_bind()).get_indexes(table)}


def upgrade() -> None:
    cols = _existing_columns("webhook_deliveries")
    to_add: list[sa.Column] = []
    if "status" not in cols:
        to_add.append(
            sa.Column("status", sa.String(length=16), nullable=False, server_default="succeeded")
        )
    if "next_attempt_at" not in cols:
        to_add.append(sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True))
    if "updated_at" not in cols:
        to_add.append(
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            )
        )

    if to_add:
        with op.batch_alter_table("webhook_deliveries") as batch:
            for col in to_add:
                batch.add_column(col)

        # Backfill only if we just added the status column; otherwise values are
        # already correct.
        if any(c.name == "status" for c in to_add):
            op.execute(
                """
                UPDATE webhook_deliveries
                SET status = CASE WHEN succeeded THEN 'succeeded' ELSE 'dead' END
                WHERE status = 'succeeded' AND NOT succeeded
                """
            )
            with op.batch_alter_table("webhook_deliveries") as batch:
                batch.alter_column("status", server_default=None)

    if "ix_wd_status_next" not in _existing_indexes("webhook_deliveries"):
        op.create_index(
            "ix_wd_status_next",
            "webhook_deliveries",
            ["status", "next_attempt_at"],
        )


def downgrade() -> None:
    indexes = _existing_indexes("webhook_deliveries")
    if "ix_wd_status_next" in indexes:
        op.drop_index("ix_wd_status_next", table_name="webhook_deliveries")
    cols = _existing_columns("webhook_deliveries")
    with op.batch_alter_table("webhook_deliveries") as batch:
        if "updated_at" in cols:
            batch.drop_column("updated_at")
        if "next_attempt_at" in cols:
            batch.drop_column("next_attempt_at")
        if "status" in cols:
            batch.drop_column("status")
