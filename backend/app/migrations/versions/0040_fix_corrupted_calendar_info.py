"""Fix corrupted journal_calendar_info rows

Revision ID: 0040
Revises: 0039
Create Date: 2026-04-09 08:00:00.000000

This migration fixes data integrity issues in journal_calendar_info where:
- is_all_day=true but start_time/end_time are non-null (invalid: all-day events should not have times)

These invalid states can occur when merging an all-day event journal with a timed event journal.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0040"
down_revision: str | None = "0039"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Fix corrupted calendar_info rows."""

    # Fix: is_all_day=true but times are set → clear times
    op.execute(
        """
        UPDATE journal_calendar_info
        SET start_time = NULL, end_time = NULL
        WHERE is_all_day = true
          AND (start_time IS NOT NULL OR end_time IS NOT NULL)
        """
    )


def downgrade() -> None:
    """No-op: data fix cannot be reversed automatically."""
    pass
