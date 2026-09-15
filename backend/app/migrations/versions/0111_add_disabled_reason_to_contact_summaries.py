"""add disabled_reason to contact_summaries

Revision ID: 0111
Revises: 0110
Create Date: 2026-09-15 10:20:00.000000

Records *why* a contact's AI summary is disabled, so the low-activity
auto-disable can stop being permanent. ``user`` is the user's own choice and
stays put; ``low_activity`` is the generator pausing a quiet contact, and is
re-evaluated on every refresh trigger.

Every existing disabled row is backfilled as ``low_activity``. No UI or MCP
path has ever disabled a summary — only the generator's low-activity check and
hand-made API calls — so treating them as auto-paused lets the contacts stuck
behind the old sticky behaviour recover.

The second constraint keeps the flag and the reason from disagreeing:
``is_disabled`` stays (the search indexer and refresh queries read it) and is
true exactly when a reason is recorded.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0111"
down_revision: str | None = "0110"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the reason, backfill disabled rows, then constrain it."""
    op.execute(
        """
        ALTER TABLE contact_summaries
        ADD COLUMN disabled_reason VARCHAR(30)
        """
    )
    op.execute(
        """
        UPDATE contact_summaries
        SET disabled_reason = 'low_activity'
        WHERE is_disabled
        """
    )
    op.execute(
        """
        ALTER TABLE contact_summaries
        ADD CONSTRAINT ck_contact_summaries_disabled_reason
            CHECK (disabled_reason IN ('user', 'low_activity')),
        ADD CONSTRAINT ck_contact_summaries_disabled_reason_matches_flag
            CHECK (is_disabled = (disabled_reason IS NOT NULL))
        """
    )


def downgrade() -> None:
    """Drop the reason; ``is_disabled`` alone still records the state."""
    op.execute(
        """
        ALTER TABLE contact_summaries
        DROP CONSTRAINT ck_contact_summaries_disabled_reason_matches_flag,
        DROP CONSTRAINT ck_contact_summaries_disabled_reason,
        DROP COLUMN disabled_reason
        """
    )
