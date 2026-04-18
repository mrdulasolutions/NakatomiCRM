"""api-key rate-limit columns

Revision ID: 0004_api_key_rate_limit
Revises: 0003_durable_webhooks
Create Date: 2026-04-18
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0004_api_key_rate_limit"
down_revision: Union[str, None] = "0003_durable_webhooks"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("api_keys") as batch:
        batch.add_column(sa.Column("rate_limit_per_minute", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("usage_window_start", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(
            sa.Column("usage_count", sa.Integer(), nullable=False, server_default="0"),
        )
    with op.batch_alter_table("api_keys") as batch:
        batch.alter_column("usage_count", server_default=None)


def downgrade() -> None:
    with op.batch_alter_table("api_keys") as batch:
        batch.drop_column("usage_count")
        batch.drop_column("usage_window_start")
        batch.drop_column("rate_limit_per_minute")
