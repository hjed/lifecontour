"""add_description_to_calendar_info

Revision ID: 0080
Revises: 0079
Create Date: 2026-05-28 19:12:45.700952

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0080"
down_revision: str | None = "0079"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade database schema."""
    op.add_column(
        "journal_calendar_info",
        sa.Column("description", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    """Downgrade database schema."""
    op.drop_column("journal_calendar_info", "description")
