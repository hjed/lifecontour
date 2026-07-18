"""add description to journal tags

Revision ID: 0102
Revises: 0101
Create Date: 2026-07-17 19:56:35.137582

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0102"
down_revision: str | None = "0101"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Give journal tags the free-text description contact tags already have.

    Nullable and unbounded to match ``tags.description``: existing rows keep
    NULL, which reads as "no description" rather than an empty one.
    """
    op.add_column(
        "journal_tags",
        sa.Column("description", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    """Drop the journal tag description column."""
    op.drop_column("journal_tags", "description")
