"""Add timezone column to journal_calendar_info

Revision ID: 0041
Revises: 0040
Create Date: 2026-04-09 08:10:00.000000

Adds an optional timezone column (IANA timezone string, e.g. 'Australia/Sydney')
to journal_calendar_info for accurate event time display and Google Calendar sync.
NULL means UTC (backward compatible).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0041"
down_revision: str | None = "0040"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MAX_TIMEZONE_LENGTH = 50


def upgrade() -> None:
    """Add timezone column to journal_calendar_info."""
    op.add_column(
        "journal_calendar_info",
        sa.Column(
            "timezone",
            sa.VARCHAR(length=MAX_TIMEZONE_LENGTH),
            nullable=True,
            comment="IANA timezone string (e.g. 'Australia/Sydney'), NULL means UTC",
        ),
    )


def downgrade() -> None:
    """Remove timezone column from journal_calendar_info."""
    op.drop_column("journal_calendar_info", "timezone")
