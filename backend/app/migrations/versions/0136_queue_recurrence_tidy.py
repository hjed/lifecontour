"""queue a tidy of every recurrence left with cancelled upcoming journals

Revision ID: 0136
Revises: 0135
Create Date: 2026-10-13 00:00:00.000000

Before the keep-next rule, a recurrence Google truncated or deleted left every
upcoming occurrence behind as a cancelled journal - the old deletion guard
read a journal merge's ``updated_at`` bump as a local edit and kept them all.

This queues one ``journal_event.recurrence_tidy`` outbox event per
(calendar, recurring event) that still has a cancelled, not-yet-started linked
journal. The processor applies the keep-next rule to each: the first upcoming
occurrence of every cancelled run stays, later ones nobody added to are
deleted, and their review items cascade away with them. Doing it through the
processor rather than here keeps the deletions on the ordinary path, with
their history, search and outbox side effects.

Only a recurrence with at least one link that recorded its recurring id is
queued: the keep-next rule plans a recurrence by that id. When its tidy runs,
links of the same recurrence synced before the id was recorded are found by
their instance-id prefix, backfilled and planned with the rest - so they can be
tidied too. A recurrence none of whose links recorded an id is not queued.

The downgrade removes any of these events not yet relayed; tidied journals
stay deleted.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0136"
down_revision: str | Sequence[str] | None = "0135"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Queue one recurrence tidy per recurrence with upcoming cancellations."""
    op.execute(
        """
        INSERT INTO outbox_events
            (event_id, event_type, aggregate_id, event_data,
             occurred_at, created_at, retry_count)
        SELECT gen_random_uuid()::text,
               'journal_event.recurrence_tidy',
               0,
               jsonb_build_object(
                   'integration_source', 'google',
                   'calendar_id', recurrences.calendar_id::text,
                   'recurring_event_id', recurrences.recurring_event_id
               )::text,
               now(),
               now(),
               0
        FROM (
            SELECT DISTINCT l.calendar_id, l.recurring_event_id
            FROM journal_external_event_links l
            JOIN journals j ON j.id = l.journal_id
            WHERE l.sync_status = 'cancelled'
              AND l.recurring_event_id IS NOT NULL
              AND j.event_date_range_start > now()
        ) AS recurrences
        """
    )


def downgrade() -> None:
    """Drop the tidy events that have not been relayed yet."""
    op.execute(
        """
        DELETE FROM outbox_events
        WHERE event_type = 'journal_event.recurrence_tidy'
          AND relayed_at IS NULL
        """
    )
