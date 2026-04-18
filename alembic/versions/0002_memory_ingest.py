"""memory links + ingest runs

Revision ID: 0002_memory_ingest
Revises: 0001_initial
Create Date: 2026-04-18

Since 0001 bootstraps via ``metadata.create_all``, fresh databases already have
these tables. This migration covers *existing* 0.1.0 databases that were
created before v1.3 (memory) and v1.4 (ingest) landed.
"""

from typing import Sequence, Union

from alembic import op
from sqlalchemy import inspect

from app.db import Base
from app import models  # noqa: F401


revision: str = "0002_memory_ingest"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    existing = set(inspector.get_table_names())
    for table_name in ("memory_links", "ingest_runs"):
        if table_name in existing:
            continue
        table = Base.metadata.tables[table_name]
        table.create(bind=bind)


def downgrade() -> None:
    bind = op.get_bind()
    for table_name in ("ingest_runs", "memory_links"):
        if table_name in Base.metadata.tables:
            Base.metadata.tables[table_name].drop(bind=bind, checkfirst=True)
