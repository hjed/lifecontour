"""add recurring_event_id to journal_external_event_links

Revision ID: 0100
Revises: 0099
Create Date: 2026-07-14 09:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0100"
down_revision: str | None = "0099"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Record the recurring master event id on external event links.

    Google Calendar expands recurring events into instances (``singleEvents=true``);
    each instance carries a ``recurringEventId`` pointing at the series master.
    Storing it lets the sync fan out series-level operations (e.g. deleting
    far-future instances when the series is cancelled) and auto-link instances
    into a journal series.
    """
    op.add_column(
        "journal_external_event_links",
        sa.Column("recurring_event_id", sa.String(length=255), nullable=True),
    )
    op.create_index(
        "ix_journal_external_event_links_recurring",
        "journal_external_event_links",
        ["calendar_id", "recurring_event_id"],
        postgresql_where=sa.text("recurring_event_id IS NOT NULL"),
    )


def downgrade() -> None:
    """Drop the recurring_event_id column and its index."""
    op.drop_index(
        "ix_journal_external_event_links_recurring",
        table_name="journal_external_event_links",
    )
    op.drop_column("journal_external_event_links", "recurring_event_id")
