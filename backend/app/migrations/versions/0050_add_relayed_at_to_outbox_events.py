"""add_relayed_at_to_outbox_events

Revision ID: 0050
Revises: 0049
Create Date: 2026-04-28 08:42:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0050"
down_revision: str | None = "0049"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add relayed_at column to outbox_events table.

    This column tracks when an event was published to the Redis Stream
    by the OutboxRelay process. It is independent of processed_at which
    tracks when the legacy OutboxProcessor handled the event.
    """
    op.execute(
        """
        ALTER TABLE outbox_events
        ADD COLUMN relayed_at TIMESTAMP WITH TIME ZONE;

        CREATE INDEX idx_outbox_events_relayed_at
            ON outbox_events (relayed_at)
            WHERE relayed_at IS NULL;
        """
    )


def downgrade() -> None:
    """Remove relayed_at column from outbox_events table."""
    op.execute(
        """
        DROP INDEX IF EXISTS idx_outbox_events_relayed_at;
        ALTER TABLE outbox_events DROP COLUMN IF EXISTS relayed_at;
        """
    )
