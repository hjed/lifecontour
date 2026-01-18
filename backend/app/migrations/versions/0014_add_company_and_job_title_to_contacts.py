"""Add company and job_title fields to contacts table

Revision ID: 0014
Revises: 0013
Create Date: 2026-01-18 13:35:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add company and job_title fields to contacts table."""
    # Add company column (nullable, max 200 characters)
    op.add_column(
        "contacts",
        sa.Column("company", sa.String(length=200), nullable=True),
    )

    # Add job_title column (nullable, max 200 characters)
    op.add_column(
        "contacts",
        sa.Column("job_title", sa.String(length=200), nullable=True),
    )


def downgrade() -> None:
    """Remove company and job_title fields from contacts table."""
    # Drop the columns
    op.drop_column("contacts", "job_title")
    op.drop_column("contacts", "company")
