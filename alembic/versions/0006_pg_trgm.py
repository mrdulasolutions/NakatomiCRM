"""enable pg_trgm + trigram GIN indexes on searchable text

Revision ID: 0006_pg_trgm
Revises: 0005_custom_fields
Create Date: 2026-04-18

Enables the ``pg_trgm`` extension and adds GIN indexes on the text columns
used for fuzzy duplicate detection. Without the indexes, the
``similarity()`` self-join in ``/contacts/duplicates`` is a sequential
scan; with them, it's a fast trigram intersection.
"""

from typing import Sequence, Union

from alembic import op


revision: str = "0006_pg_trgm"
down_revision: Union[str, None] = "0005_custom_fields"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_contact_name_trgm
          ON contacts USING GIN ((coalesce(first_name,'') || ' ' || coalesce(last_name,'')) gin_trgm_ops)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_contact_email_trgm
          ON contacts USING GIN (email gin_trgm_ops)
          WHERE email IS NOT NULL
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_company_name_trgm
          ON companies USING GIN (name gin_trgm_ops)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_company_domain_trgm
          ON companies USING GIN (domain gin_trgm_ops)
          WHERE domain IS NOT NULL
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_contact_name_trgm")
    op.execute("DROP INDEX IF EXISTS ix_contact_email_trgm")
    op.execute("DROP INDEX IF EXISTS ix_company_name_trgm")
    op.execute("DROP INDEX IF EXISTS ix_company_domain_trgm")
    # Leave the extension in place — other tables may rely on it, and
    # dropping it is rarely what the operator actually wants.
