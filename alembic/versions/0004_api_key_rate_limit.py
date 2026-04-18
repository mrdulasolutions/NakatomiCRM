"""api-key rate-limit columns

Revision ID: 0004_api_key_rate_limit
Revises: 0003_durable_webhooks
Create Date: 2026-04-18

Idempotent: the current model already declares these columns, so fresh
installs via 0001's ``create_all`` have them. Only upgrades from v0.1.0
need this migration to do work.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect


revision: str = "0004_api_key_rate_limit"
down_revision: Union[str, None] = "0003_durable_webhooks"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _cols(table: str) -> set[str]:
    return {c["name"] for c in inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    existing = _cols("api_keys")
    to_add: list[sa.Column] = []
    if "rate_limit_per_minute" not in existing:
        to_add.append(sa.Column("rate_limit_per_minute", sa.Integer(), nullable=True))
    if "usage_window_start" not in existing:
        to_add.append(sa.Column("usage_window_start", sa.DateTime(timezone=True), nullable=True))
    if "usage_count" not in existing:
        to_add.append(sa.Column("usage_count", sa.Integer(), nullable=False, server_default="0"))

    if not to_add:
        return

    with op.batch_alter_table("api_keys") as batch:
        for col in to_add:
            batch.add_column(col)
    if any(c.name == "usage_count" for c in to_add):
        with op.batch_alter_table("api_keys") as batch:
            batch.alter_column("usage_count", server_default=None)


def downgrade() -> None:
    existing = _cols("api_keys")
    with op.batch_alter_table("api_keys") as batch:
        if "usage_count" in existing:
            batch.drop_column("usage_count")
        if "usage_window_start" in existing:
            batch.drop_column("usage_window_start")
        if "rate_limit_per_minute" in existing:
            batch.drop_column("rate_limit_per_minute")
