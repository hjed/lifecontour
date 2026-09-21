"""add integration_source to calendars

Revision ID: 0115
Revises: 0114
Create Date: 2026-09-21 09:30:00.000000

A journal's external event links are the only record of what it put in other
systems, and nothing on them says which system that is. ``JournalDeleted``
therefore filed every identifier under a hardcoded ``"google"`` key, so a
worker could not find its own -- and the Google worker was handed Snipe-IT and
Strava identifiers it then tried to delete from a Google calendar.

The calendar a link hangs off is what knows: the backend is told the
integration source when it creates the row (``_ensure_calendar_exists``). This
records it. Calendars that already exist are backfilled -- from
``google_calendar_id`` for Google, and for the synthetic calendars of the
non-calendar integrations from the shape of the external event ids they hold,
which is the only evidence those rows carry.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0115"
down_revision: str | None = "0114"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# External event id prefix → the integration source that writes it. Only the
# synthetic calendars need this: Google's own calendars are named by
# ``google_calendar_id``. It is a one-off reading of rows written before the
# column existed, which is why the knowledge lives here and not in the app.
_SOURCE_BY_EXTERNAL_ID_PREFIX = {
    "snipeit_maint:": "snipeit_maintenance",
    "strava:": "strava",
}


def upgrade() -> None:
    """Add the column and classify the calendars already in the database."""
    op.add_column(
        "calendars",
        sa.Column(
            "integration_source",
            sa.String(length=50),
            nullable=True,
            comment="Integration that owns this calendar, e.g. google, strava",
        ),
    )

    connection = op.get_bind()
    connection.execute(
        sa.text("""
            UPDATE calendars
            SET integration_source = 'google'
            WHERE google_calendar_id IS NOT NULL
        """)
    )
    for prefix, source in _SOURCE_BY_EXTERNAL_ID_PREFIX.items():
        connection.execute(
            sa.text("""
                UPDATE calendars c
                SET integration_source = :source
                WHERE c.integration_source IS NULL
                  AND EXISTS (
                      SELECT 1
                      FROM journal_external_event_links l
                      WHERE l.calendar_id = c.id
                        AND l.external_event_id LIKE :pattern
                  )
            """),
            {"source": source, "pattern": f"{prefix}%"},
        )


def downgrade() -> None:
    """Drop the column; deletion identifiers go back to one hardcoded key."""
    op.drop_column("calendars", "integration_source")
