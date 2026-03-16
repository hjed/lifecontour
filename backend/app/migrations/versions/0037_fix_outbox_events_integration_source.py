"""Fix outbox_events with stale google_contacts integration_source

Revision ID: 0037
Revises: 0036
Create Date: 2026-03-17

Migration 0029 renamed 'google_contacts' to 'google' in the sync_metadata
check constraint and updated rows in sync_metadata, external_references, and
sync_jobs.  However, it did NOT update the JSON event_data (stored as TEXT)
inside outbox_events, so any unprocessed events created before the rename
still carry 'google_contacts' and fail the check constraint when processed.

This data-only migration fixes remaining outbox events by performing a text
replacement on the JSON string.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0037"
down_revision: str | None = "0036"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Update stale outbox events from 'google_contacts' to 'google'."""
    op.execute(
        """
        UPDATE outbox_events
        SET event_data = replace(event_data, '"integration_source": "google_contacts"', '"integration_source": "google"')
        WHERE processed_at IS NULL
        AND event_data LIKE '%"integration_source": "google_contacts"%'
        """
    )


def downgrade() -> None:
    """Revert outbox events from 'google' back to 'google_contacts'."""
    op.execute(
        """
        UPDATE outbox_events
        SET event_data = replace(event_data, '"integration_source": "google"', '"integration_source": "google_contacts"')
        WHERE processed_at IS NULL
        AND event_data LIKE '%"integration_source": "google"%'
        """
    )
