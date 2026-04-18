"""durable webhook deliveries

Revision ID: 0003_durable_webhooks
Revises: 0002_memory_ingest
Create Date: 2026-04-18

Adds ``status``, ``next_attempt_at``, and ``updated_at`` to ``webhook_deliveries``
so the background worker can persist retry scheduling durably.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0003_durable_webhooks"
down_revision: Union[str, None] = "0002_memory_ingest"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("webhook_deliveries") as batch:
        batch.add_column(
            sa.Column(
                "status",
                sa.String(length=16),
                nullable=False,
                server_default="succeeded",
            )
        )
        batch.add_column(sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            )
        )

    # Backfill existing rows: pre-worker deliveries are terminal, so mark them
    # succeeded or dead based on the legacy ``succeeded`` bool.
    op.execute(
        """
        UPDATE webhook_deliveries
        SET status = CASE WHEN succeeded THEN 'succeeded' ELSE 'dead' END
        """
    )

    # Drop the server_default now that data is backfilled; application owns it.
    with op.batch_alter_table("webhook_deliveries") as batch:
        batch.alter_column("status", server_default=None)

    op.create_index(
        "ix_wd_status_next",
        "webhook_deliveries",
        ["status", "next_attempt_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_wd_status_next", table_name="webhook_deliveries")
    with op.batch_alter_table("webhook_deliveries") as batch:
        batch.drop_column("updated_at")
        batch.drop_column("next_attempt_at")
        batch.drop_column("status")
