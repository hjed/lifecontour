"""Fix corrupted journal_calendar_info rows

Revision ID: 0040
Revises: 0039
Create Date: 2026-04-09 08:00:00.000000

This migration fixes data integrity issues in journal_calendar_info where:
1. is_all_day=true but start_time/end_time are non-null (invalid: all-day events should not have times)
2. is_all_day=false but start_time and end_time are both null (invalid: timed events must have times)

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

    # Fix case 1: is_all_day=true but times are set → clear times
    op.execute(
        """
        UPDATE journal_calendar_info
        SET start_time = NULL, end_time = NULL
        WHERE is_all_day = true
          AND (start_time IS NOT NULL OR end_time IS NOT NULL)
        """
    )

    # Fix case 2: is_all_day=false but both times are null → set to all-day
    op.execute(
        """
        UPDATE journal_calendar_info
        SET is_all_day = true
        WHERE is_all_day = false
          AND start_time IS NULL
          AND end_time IS NULL
        """
    )


def downgrade() -> None:
    """No-op: data fix cannot be reversed automatically."""
    pass
