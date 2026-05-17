"""Invalidate Strava sync_metadata version hashes for type data backfill

Revision ID: 0071
Revises: 0070
Create Date: 2026-05-17 18:37:11.957930

Sets version_hash to NULL for all Strava-sourced sync_metadata rows.
This forces the next full Strava sync to re-process each activity,
triggering the newly added _ensure_type_data_rows logic that creates
missing type-specific data rows (e.g. journal_bushwalking_data).

After re-processing, the version_hash is repopulated and future syncs
will skip unchanged activities as before.
"""

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0071"
down_revision: str | None = "0070"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Set version_hash to 'invalidated_for_type_backfill' for all Strava sync_metadata entries."""
    op.execute(
        """
        UPDATE sync_metadata
        SET version_hash = 'invalidated_for_type_backfill'
        WHERE integration_source = 'strava'
        """
    )


def downgrade() -> None:
    """No-op: cannot restore version hashes, they will be repopulated on next sync."""
    pass
