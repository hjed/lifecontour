"""fix_google_calendar_timezone

Revision ID: b44ca39d0917
Revises: 0044
Create Date: 2026-04-15 21:00:50.170500

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0045"
down_revision: str | None = "0044"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade database schema."""
    op.execute("""
        UPDATE journal_calendar_info jci
        SET
            start_time = (j.event_date_range_start AT TIME ZONE jci.timezone)::time,
            end_time = (j.event_date_range_end AT TIME ZONE jci.timezone)::time
        FROM journals j
        WHERE jci.journal_id = j.id
        AND jci.start_time IS NOT NULL
        AND jci.timezone IS NOT NULL;
    """)


def downgrade() -> None:
    """Downgrade database schema."""
    op.execute("""
        UPDATE journal_calendar_info jci
        SET
            start_time = (j.event_date_range_start AT TIME ZONE 'UTC')::time,
            end_time = (j.event_date_range_end AT TIME ZONE 'UTC')::time
        FROM journals j
        WHERE jci.journal_id = j.id
        AND jci.start_time IS NOT NULL
        AND jci.timezone IS NOT NULL;
    """)
