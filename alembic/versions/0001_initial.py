"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-04-18

Bootstrap: creates all tables from SQLAlchemy metadata via ``create_all``.

**Accepted technical debt (P0):** rewriting this revision to explicit
``op.create_table`` calls would break checksums on every already-deployed
database. New columns/tables ship as numbered migrations (0002+) with
explicit ops. CI runs ``alembic upgrade head`` on a clean DB
(``tests/test_migrations.py``) so the chain stays green. Do not edit 0001
in place — add a new revision instead.
"""

from typing import Sequence, Union

from alembic import op

from app.db import Base
from app import models  # noqa: F401  — populate metadata


revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)
