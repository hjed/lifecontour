"""Add event_state column to journal_calendar_info

Revision ID: 0035
Revises: 0034
Create Date: 2025-03-15

Adds an event_state column to journal_calendar_info to track the
participation/status state of calendar event journals. Valid states
are: invited, tentative, confirmed, cancelled.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0035"
down_revision: str | None = "0034"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

VALID_EVENT_STATES = ("invited", "tentative", "confirmed", "cancelled")


def upgrade() -> None:
    """Add event_state column with check constraint."""
    op.add_column(
        "journal_calendar_info",
        sa.Column(
            "event_state",
            sa.VARCHAR(length=20),
            nullable=False,
            server_default="confirmed",
            comment="Event participation state (invited, tentative, confirmed, cancelled)",
        ),
    )

    # Add check constraint for valid event_state values
    states_list = ", ".join(f"'{s}'" for s in VALID_EVENT_STATES)
    op.create_check_constraint(
        "ck_journal_calendar_info_event_state",
        "journal_calendar_info",
        f"event_state IN ({states_list})",
    )


def downgrade() -> None:
    """Remove event_state column and constraint."""
    op.drop_constraint(
        "ck_journal_calendar_info_event_state",
        "journal_calendar_info",
        type_="check",
    )
    op.drop_column("journal_calendar_info", "event_state")
